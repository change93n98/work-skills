import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {LAYOUT, reportCategories, totalCategoryLabel} from './report_template.mjs';

const NA = 'n.a.';
const VERSION = 'llm-prof-hardware-comparison-v1';
const CORE_STAGES = new Set(['卷积', '卷积状态更新', '卷积后准备', 'Chunk 主计算', '卷积后准备与递推', '递推主计算']);
const OPERATORS = {
  gdn_conv: 'causal_conv1d_fn',
  gdn_conv_update: 'causal_conv1d_update',
  gdn_rearrange_qkv: 'rearrange_mixed_qkv',
  gdn_gating: 'fused_gdn_gating',
  gdn_qk_norm: 'l2norm',
  gdn_gating_qk_fused: '_fused_post_conv_kernel',
  gdn_recurrent: 'fused_recurrent_gated_delta_rule_fwd',
  gdn_recurrent_fused: 'fused_sigmoid_gating_delta_rule_update_kernel',
  gdn_recurrent_packed: 'fused_recurrent_gated_delta_rule_packed_decode_kernel',
  gdn_output_norm: 'gated RMSNorm',
  gdn_output_layout: 'output layout',
  gdn_metadata: 'metadata preparation',
  gdn_aux: 'indexing/layout helpers',
  gdn_memory: 'Memcpy/Memset',
};
const ms = us => Number.isFinite(us) ? us / 1000 : NA;
const near = (a,b) => Math.abs(a-b) <= Math.max(1e-6, Math.abs(b)*1e-10);

function durations(rows, key) {
  const values = new Map();
  for (const row of rows) {
    if (typeof row[key] !== 'string' || values.has(row[key]) ||
        !Number.isFinite(row.total_duration_us) || row.total_duration_us < 0) {
      throw new Error('Invalid or repeated '+key+': '+row[key]);
    }
    values.set(row[key], row.total_duration_us);
  }
  return values;
}

function readWindow({report,path:inputPath}, name) {
  const m = report.metadata ?? {};
  const selection = m.phase_selection ?? {};
  const stage = m.stage ?? report.stage;
  const anchor = m.device_step?.start?.annotation?.name ?? '';
  const match = /^execute_context_(\d+)\((\d+)\)_generation_(\d+)\((\d+)\)/.exec(anchor);
  const rank = report.rank ?? /_rank(\d+)[._]/.exec(path.basename(report.source ?? ''))?.[1];
  const total = durations(report.summary, 'category');
  const rows = report.gdn_comparison?.rows ?? [];
  const gdn = durations(rows,'group');
  const excluded = report.excluded?.total_duration_us;
  const coverage = m.window_coverage;
  const raw = [...total.values()].reduce((a,b)=>a+b,0)+excluded;
  if (!report.source || !Number.isFinite(excluded) || excluded < 0 ||
      (Number.isFinite(report.raw_total_duration_us) && !near(raw,report.raw_total_duration_us)) ||
      (Number.isFinite(coverage?.selected_duration_sum_us) && !near(raw,coverage.selected_duration_sum_us))) {
    throw new Error(name+' classification times do not reconcile');
  }
  if (coverage && (!Number.isFinite(coverage.device_covered_us) || !Number.isFinite(coverage.window_total_us) ||
      coverage.device_covered_us<0 || coverage.window_total_us<=0 || coverage.device_covered_us>coverage.window_total_us)) {
    throw new Error(name+' has invalid device coverage');
  }
  if (rows.length && !near([...gdn.values()].reduce((a,b)=>a+b,0),total.get('GDN'))) {
    throw new Error(name+' GDN detail does not reconcile');
  }
  const mixed = selection.mixed_count>0 || report.gdn_comparison?.scope==='mixed-or-stage-mismatch' ||
    (match && Number(match[1])>0 && Number(match[3])>0);
  const work = [
    selection.prefill_context_tokens ?? (stage==='prefill'&&match ? Number(match[2]) : null),
    selection.prefill_count,
    selection.mixed_count,
    selection.mixed_generation_tokens,
    stage==='decode'&&match ? Number(match[3]) : null,
    stage==='decode'&&match ? Number(match[4]) : null,
  ];
  return {name,report,inputPath,m,coverage,stage,rank,anchor,mixed,total,rows,gdn,excluded,work};
}

function compareBlockers([left,right]) {
  const blockers=[];
  if (!['prefill','decode'].includes(left.stage) || left.stage!==right.stage) blockers.push('阶段未确认一致');
  if (left.mixed || right.mixed) blockers.push('窗口含混合轮次或阶段冲突');
  if (left.rank!=null&&right.rank!=null&&String(left.rank)!==String(right.rank)) blockers.push('rank 不同');
  const rules = r=>r.report.classification_rules;
  if (!(rules(left)?.sha256 && rules(left).sha256===rules(right)?.sha256)) blockers.push('分类规则校验值未确认一致');
  // Pure prefill chunk count can differ at equal token workload.
  if ([0,2,3,4,5].some(i=>Number.isFinite(left.work[i])&&Number.isFinite(right.work[i])&&left.work[i]!==right.work[i]))
    blockers.push('实际窗口工作量不同');
  return blockers;
}

function operatorLabel(w,group) {
  const types=w.rows.find(r=>r.group===group)?.semantic_types ?? [];
  if (group==='Chunk 主计算') {
    if(types.includes('gdn_chunk_prefill'))return 'FlashInfer chunk_gated_delta_rule';
    if(types.length)return 'chunk_gated_delta_rule_fwd';
  }
  if (group==='元数据准备') {
    const names=(w.report.kernels??[]).flatMap(k=>k.category_parts??[k])
      .filter(k=>k.classification?.semantic_type==='gdn_metadata').map(k=>k.name);
    if(names.some(n=>n.includes('gdn_prepare_cudagraph_impl')))return 'gdn_prepare_cudagraph_impl';
    if(names.some(n=>n.startsWith('Memcpy HtoD')))return 'Memcpy HtoD';
  }
  return [...new Set(types.map(t=>OPERATORS[t]).filter(Boolean))].join('、');
}

function gdnLabel(windows,group) {
  const [left,right]=windows.map(w=>operatorLabel(w,group));
  const cn=group==='Chunk 主计算'?'分块主计算':group;
  const operators=left&&right&&left!==right ? windows[0].name+': '+left+'\n'+windows[1].name+': '+right : left||right;
  return operators?cn+'（'+operators+'）':cn;
}

function header(s,row,last='E') {
  s.getRange('A'+row+':'+last+row).format={fill:LAYOUT.header_fill,font:{name:LAYOUT.font,size:LAYOUT.body_size,bold:true,color:LAYOUT.header_text},
    rowHeight:LAYOUT.header_height,wrapText:true,horizontalAlignment:'center',verticalAlignment:'center'};
}
function note(s,row,text) {
  const range=s.getRange('A'+row+':E'+row);
  range.merge();
  s.getRange('A'+row).values=[[text]];
  range.format.wrapText=true;
  range.format.rowHeight=text.length>112?39:28;
}
function formatMetrics(s,first,last) {
  s.getRange('A'+first+':E'+last).format.rowHeight=LAYOUT.body_height;
  s.getRange('B'+first+':C'+last).setNumberFormat(LAYOUT.duration_format);
  s.getRange('D'+first+':D'+last).setNumberFormat('0.00"×"');
  s.getRange('E'+first+':E'+last).setNumberFormat(LAYOUT.ratio_format);
  s.getRange('D'+first+':E'+last).format.horizontalAlignment='center';
}
function ratios(s,row,performance) {
  const prefix='=IF(OR(COUNT(B'+row+':C'+row+')<2,B'+row+'<=0,C'+row+'<=0),"n.a.",';
  s.getRange('D'+row).formulas=[[prefix+'B'+row+'/C'+row+')']];
  if(performance)s.getRange('E'+row).formulas=[[prefix+'C'+row+'/B'+row+')']];
  else s.getRange('E'+row).values=[[NA]];
}

function build(Workbook,{reports,names,title,workload_verified,workload_note}) {
  if (names.some(n=>!n.trim()) || names[0]===names[1]) throw new Error('Use distinct, nonempty hardware labels');
  const windows=reports.map((r,i)=>readWindow(r,names[i]));
  const blockers=compareBlockers(windows);
  if (!workload_verified) blockers.push('工作量尚未核实');
  const performance=!blockers.length;
  const known=[...new Set(windows.flatMap(w=>[...w.total.keys()]))];
  const categories=reportCategories(known);
  if (known.some(k=>!categories.includes(k))) throw new Error('Unknown report category');
  const groups=[...new Set([...Object.keys(LAYOUT.gdn_comparison_groups),'卷积后准备与递推','未对齐 GDN 子项',
    ...windows.flatMap(w=>[...w.gdn.keys()])])].filter(k=>windows.some(w=>w.gdn.has(k)));
  const gdnCoverage=windows.every(w=>!w.report.gdn_comparison?.graph_candidates?.length &&
    !w.gdn.has('未对齐 GDN 子项') && (!w.total.get('GDN')||w.rows.length)) &&
    groups.filter(k=>CORE_STAGES.has(k)).every(k=>windows.every(w=>w.gdn.has(k)));
  const stage=windows[0].stage;
  const gdnPhase=windows.every(w=>w.report.gdn_comparison?.scope===stage);

  const first=6, sum=first+categories.length, wait=sum+1, device=sum+2, adjust=sum+3, cover=sum+4, idle=sum+5, last=sum+6;
  const gdHead=last+2, gdLast=gdHead+groups.length;
  const workHead=(groups.length?gdLast:last)+2;
  const wb=Workbook.create(), s=wb.worksheets.add('性能对比');
  s.showGridLines=false;
  const style=s.getRange('A1:E'+(workHead+25)).format;
  style.font={name:LAYOUT.font,size:LAYOUT.body_size};
  style.verticalAlignment='center';
  s.getRange('A:A').format.columnWidth=groups.length?56:33;
  s.getRange('B:E').format.columnWidth=21;
  note(s,2,title);
  s.getRange('A2').format.font={name:LAYOUT.font,size:LAYOUT.title_size,bold:true,color:LAYOUT.header_fill};
  note(s,3,names.join(' / ')+' · '+windows.map(w=>w.stage??'未标阶段').join(' / '));
  note(s,4,'耗时比＝'+names[0]+'/'+names[1]+'。观测性能比取倒数，以 '+names[1]+' 为 100%。'+
    (performance?'':'性能比 n.a.（'+blockers.join('、')+'）。'));
  const columns=[names[0]+' (ms)',names[1]+' (ms)','耗时比 左/右','观测性能比'];
  s.getRange('A5:E5').values=[['类别 / 时间项',...columns]];
  header(s,5);
  s.getRange('A'+first+':A'+last).values=[...categories.map(k=>k==='GDN'&&!gdnCoverage?'GDN（已确认子集）':k),
    totalCategoryLabel(categories.length),...LAYOUT.time_rows.slice(1)].map(k=>[k]);
  for(const [i,w] of windows.entries()){
    const c='BC'[i];
    s.getRange(c+first+':'+c+(sum-1)).values=categories.map(k=>[ms(w.total.get(k)??0)]);
    s.getRange(c+sum).formulas=[['=SUM('+c+first+':'+c+(sum-1)+')']];
    s.getRange(c+wait).values=[[ms(w.excluded)]];
    s.getRange(c+device).formulas=[['=SUM('+c+sum+':'+c+wait+')']];
    s.getRange(c+cover).values=[[ms(w.coverage?.device_covered_us)]];
    s.getRange(c+last).values=[[ms(w.coverage?.window_total_us)]];
    if(w.coverage){
      s.getRange(c+adjust).formulas=[['='+c+cover+'-'+c+device]];
      s.getRange(c+idle).formulas=[['='+c+last+'-'+c+cover]];
    }else{
      s.getRange(c+adjust).values=[[NA]];
      s.getRange(c+idle).values=[[NA]];
    }
  }
  for(let row=first;row<=last;row++){
    const gdn=categories[row-first]==='GDN';
    ratios(s,row,performance&&(row<=sum||row===last)&&(!gdn||(gdnCoverage&&gdnPhase)));
  }
  metricsMain(s,first,last);
  s.tables.add('A5:E'+last,true,'CategoryPerformance').style=LAYOUT.table_style;
  s.freezePanes.freezeRows(5);

  if(groups.length){
    s.getRange('A'+gdHead+':E'+gdHead).values=[['GDN 分项（按逻辑阶段对齐）',...columns]];
    header(s,gdHead);
    formatMetrics(s,gdHead+1,gdLast);
    groups.forEach((k,i)=>{
      const row=gdHead+i+1,label=gdnLabel(windows,k);
      s.getRange('A'+row+':C'+row).values=[[label,...windows.map(w=>w.gdn.has(k)?ms(w.gdn.get(k)):'未单独归因')]];
      ratios(s,row,performance&&gdnPhase&&CORE_STAGES.has(k));
      s.getRange('A'+row).format.wrapText=true;
      s.getRange('A'+row+':E'+row).format.rowHeight=label.length>92?58:label.length>45?39:28;
      if(i%2===0)s.getRange('A'+row+':E'+row).format.fill='#EBF4F9';
    });
  }

  const workLabels=['上下文 token','含 Prefill 的轮次','其中混合轮次','混合轮的 generation token','Decode 请求数','Decode token'];
  const workRows=workLabels.flatMap((k,i)=>windows.some(w=>Number.isFinite(w.work[i])) ? [[k,...windows.map(w=>w.work[i]??NA)]] : []);
  if(!workRows.length)workRows.push(['实际工作量未记录',NA,NA]);
  s.getRange('A'+workHead+':C'+workHead).values=[['实际窗口工作量',...names]];
  header(s,workHead,'C');
  const workLast=workHead+workRows.length;
  s.getRange('A'+(workHead+1)+':C'+workLast).values=workRows;
  s.getRange('B'+(workHead+1)+':C'+workLast).setNumberFormat(LAYOUT.integer_format);
  if(workRows[0][0]==='上下文 token'){
    const row=workLast+1;
    s.getRange('A'+row).values=[['窗口上下文处理率 (token/s)']];
    for(const c of 'BC')s.getRange(c+row).formulas=[['=IF(OR(COUNT('+c+(workHead+1)+','+c+last+')<2,'+c+last+'<=0),"n.a.",'+c+(workHead+1)+'*1000/'+c+last+')']];
    s.getRange('B'+row+':C'+row).setNumberFormat('#,##0.00');
  }

  let line=workLast+3;
  if(workload_note)note(s,line++,workload_note);
  note(s,line++,'分类合计排除 WAIT/SET，GDN 分项已计入主行。设备覆盖按区间并集计算，空泡为窗口减去覆盖。');
  if(groups.length)note(s,line++,'GDN 依逻辑阶段对齐。实现辅助和元数据单列，融合核整笔计入，未单独归因的分项不填性能比。');
  for(const w of windows){
    note(s,line++,w.name+' · 规则 '+(w.report.classification_rules?.version??'未记录')+
      ' · rank '+(w.rank??'未记录')+' · 窗口 '+(w.m.start_us??NA)+' 至 '+(w.m.end_us??NA)+' µs');
    note(s,line++,w.name+' 分类：'+w.inputPath);
    note(s,line++,w.name+' 来源：'+w.report.source);
  }
  note(s,line,VERSION);
  wb.recalculate();
  for(const [i,w] of windows.entries()){
    const c='BC'[i], value=row=>s.getRange(c+row).values[0][0];
    if(!near(value(device),ms([...w.total.values()].reduce((a,b)=>a+b,0)+w.excluded)))throw Error('Workbook device total mismatch');
    if(w.coverage&&(!near(value(adjust)+value(device),value(cover))||!near(value(idle)+value(cover),value(last))))
      throw Error('Workbook coverage mismatch');
  }
  return wb;
}

function metricsMain(sheet,first,last) {
  formatMetrics(sheet,first,last);
  const labels=sheet.getRange('A'+first+':A'+last).values;
  labels.forEach(([label],i)=>{
    if(label.startsWith('GDN')||label.endsWith('类合计')||label==='空泡'||label==='窗口总时间')
      sheet.getRange('A'+(first+i)+':E'+(first+i)).format.font={name:LAYOUT.font,size:LAYOUT.body_size,bold:true};
  });
}

try {
  const [input,output,modules]=process.argv.slice(2);
  const require=createRequire(path.join(path.resolve(modules),'__prof_resolver.cjs'));
  const {Workbook,SpreadsheetFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
  const wb=build(Workbook,JSON.parse(await fs.readFile(input,'utf8')));
  await(await SpreadsheetFile.exportXlsx(wb)).save(output);
  process.exit(0);
} catch(error) {
  console.error('Comparison XLSX export failed: '+error.message);
  process.exit(1);
}
