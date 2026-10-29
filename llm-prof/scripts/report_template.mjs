// Canonical approved classification layout. Do not reconstruct native styles in callers.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
const layoutBytes=await fs.readFile(new URL('../assets/report-layout.json',import.meta.url));
export const LAYOUT=JSON.parse(layoutBytes.toString('utf8'));
export const LAYOUT_SHA256=createHash('sha256').update(layoutBytes).digest('hex');
if(LAYOUT.schema_version!==1)throw new Error('Unsupported report layout schema');
const rawKeys=['name','record_count','total_duration_us','avg_duration_us','kernel_relative_pct','window_absolute_pct'];
const sourceName=r=>path.basename(r.source);
const header=(sheet,range)=>{sheet.getRange(range).format={fill:LAYOUT.header_fill,font:{name:LAYOUT.font,size:LAYOUT.body_size,bold:true,color:LAYOUT.header_text},rowHeight:LAYOUT.header_height,wrapText:true,horizontalAlignment:'center',verticalAlignment:'center'};};
function normalize(r){
 const match=path.basename(r.source).match(/_rank(\d+)[._]/);
 return {...r,metadata:{...r.metadata,stage:r.metadata.stage??r.stage},rank:r.rank??(match?Number(match[1]):'未指定'),label:r.label??r.metadata.label??(r.metadata.device_step?`${r.metadata.stage??r.stage}-step${r.metadata.step_number??2}-device`:`${r.metadata.stage??r.stage??'selected'}-window`)};
}
function boundary(r,side){
 if(r.metadata.device_step)return r.metadata.device_step[side];
 return {annotation:{id:null},first_event:{name:'用户给定时间',category:'',offset_us:side==='start'?r.metadata.start_us:r.metadata.end_us,device:r.metadata.device_id,stream:null,correlation:null,association_basis:'user-time'},boundary_confidence:'caller-provided',unlinked_near_boundary_count:0,later_ambiguous_event_count:0};
}
export function createClassificationWorkbook(Workbook,reports,{title}={}){
 if(!Array.isArray(reports)||!reports.length)throw new Error('Report needs at least one selected window');
 const list=reports.map(normalize);
 const hasGroupGemm=list.some(r=>r.summary.some(s=>s.category==='group gemm'));
 const categories=LAYOUT.category_order.filter(c=>c!=='group gemm'||hasGroupGemm);
 const categoryCount=categories.length,rowsPerRank=categoryCount+LAYOUT.time_rows.length;
 const totalLabel=hasGroupGemm?LAYOUT.moe_total_label:LAYOUT.time_rows[0];
 if(new Set(list.map(r=>r.label)).size!==1)throw new Error('Fixed default layout requires one selected window label, not mixed prefill/decode/steps');
 if(new Set(list.map(r=>String(r.rank))).size!==list.length)throw new Error('Duplicate rank/window block');
 for(const r of list){
  const names=r.summary.map(s=>s.category),allowed=LAYOUT.category_order.filter(c=>c!=='group gemm'||names.includes(c));
  if(!r.kernels.length||JSON.stringify(names)!==JSON.stringify(allowed))throw new Error('Expected ordered dense or MoE categories and kernel detail');
  if(r.kernels.some(k=>k.classification.category==='group gemm')&&!names.includes('group gemm'))throw new Error('Group GEMM is missing from the category summary');
  if(!r.metadata.window_coverage)throw new Error('Exact window coverage missing; rerun prof.py against the trace before exporting this native report');
 }
 const group=title??list[0].group??list[0].label;
  const wb=Workbook.create();
  const summary=wb.worksheets.add(LAYOUT.sheet_names[0]);
  const detail=wb.worksheets.add(LAYOUT.sheet_names[1]);
  const audit=wb.worksheets.add(LAYOUT.sheet_names[2]);
  const values=[...list.flatMap(r=>r.kernels.map(k=>[...rawKeys.map(key=>k[key]),k.category,k.classification.rule_id,
    k.classification.semantic_type,k.classification.confidence,k.classification.ambiguity_reasons.join('; '),
    r.rank,r.label,`${r.rank}:${r.label}`,sourceName(r)]))];
  const n=values.length+1;
  detail.getRange('A1').write([[...rawKeys,'类别','分类规则','语义子类','置信度','歧义','rank','窗口','窗口ID','来源trace'],...values]);
  detail.showGridLines=false;
  detail.getRange(`A1:O${n}`).format.font={name:LAYOUT.font,size:LAYOUT.body_size};
  detail.getRange(`A1:O${n}`).format.verticalAlignment='center';
  header(detail,'A1:O1');
  const widths=LAYOUT.detail_widths;
  for(let i=0;i<15;i++)detail.getRangeByIndexes(0,i,n,1).format.columnWidth=widths[i];
  detail.getRange(`B2:B${n}`).setNumberFormat(LAYOUT.integer_format);
  detail.getRange(`C2:D${n}`).setNumberFormat(LAYOUT.duration_format);
  detail.getRange(`E2:F${n}`).setNumberFormat(LAYOUT.raw_pct_format);
  detail.getRange(`J2:J${n}`).conditionalFormats.add('containsText',{text:'unknown',format:{fill:LAYOUT.unknown_fill,font:{color:LAYOUT.unknown_text,bold:true}}});
  detail.freezePanes.freezeRows(1);
  detail.tables.add(`A1:O${n}`,true,'KernelDetail').style=LAYOUT.table_style;
  summary.showGridLines=false;
  summary.getRange('A2').values=[[group+' kernel 分类']];
  summary.getRange('A3').values=[['总时间为片选窗口；空泡=窗口−设备事件去重覆盖。分类仍按子表2加总，包含 WAIT/SET。']];
  const ruleVersions=[...new Set(list.map(r=>r.classification_rules.version))].join(', ');
  const platforms=[...new Set(list.map(r=>r.classification_rules.platform))].join(', ');
  summary.getRange('A4').values=[[`规则 ${ruleVersions}，平台 ${platforms}。device 为关联首设备事件选窗，含 WAIT/SET；边界见“选窗依据”。`]];
  summary.getRange('A5:K5').values=[['rank','窗口','类别/时间项','调用次数','kernel种类','总耗时 (µs)','总耗时 (ms)',hasGroupGemm?'七类内占比':'六类内占比','窗口占比','窗口 (ms)','未知种类']];
  const rowCount=list.length*rowsPerRank+LAYOUT.summary_header_row;
  const scope=`'Kernel明细'!$N$2:$N$${n}`,category=`'Kernel明细'!$G$2:$G$${n}`,
    duration=`'Kernel明细'!$C$2:$C$${n}`,calls=`'Kernel明细'!$B$2:$B$${n}`,confidence=`'Kernel明细'!$J$2:$J$${n}`;
  for(let i=0;i<list.length;i++){
    const report=list[i],start=LAYOUT.summary_first_row+i*rowsPerRank,total=start+categoryCount,excluded=total+1,key=`${report.rank}:${report.label}`;
    const blockStart=2+list.slice(0,i).reduce((total,r)=>total+r.kernels.length,0);
    const blockEnd=blockStart+report.kernels.length-1;
    const scope=`'Kernel明细'!$N$${blockStart}:$N$${blockEnd}`,category=`'Kernel明细'!$G$${blockStart}:$G$${blockEnd}`,
      duration=`'Kernel明细'!$C$${blockStart}:$C$${blockEnd}`,calls=`'Kernel明细'!$B$${blockStart}:$B$${blockEnd}`,
      confidence=`'Kernel明细'!$J$${blockStart}:$J$${blockEnd}`;
    for(let c=0;c<categoryCount+2;c++){
      const row=start+c,label=c<categoryCount?categories[c]:c===categoryCount?totalLabel:LAYOUT.time_rows[1];
      summary.getRange(`A${row}:C${row}`).values=[[report.rank,report.label,label]];
      summary.getRange(`J${row}`).values=[[report.metadata.window_duration_us/1000]];
      if(c<categoryCount){
        summary.getRange(`D${row}:I${row}`).formulas=[[
          `=SUMIFS(${calls},${scope},"${key}",${category},C${row})`,
          `=COUNTIFS(${scope},"${key}",${category},C${row})`,
          `=SUMIFS(${duration},${scope},"${key}",${category},C${row})`,
          `=F${row}/1000`,`=IF($F$${total}=0,"n.a.",F${row}/$F$${total})`,`=G${row}/J${row}`]];
        summary.getRange(`K${row}`).formulas=[[`=COUNTIFS(${scope},"${key}",${category},C${row},${confidence},"unknown")`]];
      }else if(c===categoryCount){
        summary.getRange(`D${row}:I${row}`).formulas=[[`=SUM(D${start}:D${row-1})`,`=SUM(E${start}:E${row-1})`,
          `=SUM(F${start}:F${row-1})`,`=F${row}/1000`,`=IF(F${row}=0,"n.a.",SUM(H${start}:H${row-1}))`,`=G${row}/J${row}`]];
        summary.getRange(`K${row}`).formulas=[[`=SUM(K${start}:K${row-1})`]];
        summary.getRange(`A${row}:K${row}`).format.font={name:LAYOUT.font,size:LAYOUT.body_size,bold:true};
      }else{
        summary.getRange(`D${row}:G${row}`).formulas=[[
          `=SUMIFS(${calls},${scope},"${key}")-D${total}`,`=COUNTIFS(${scope},"${key}")-E${total}`,
          `=SUMIFS(${duration},${scope},"${key}")-F${total}`,`=F${row}/1000`]];
        summary.getRange(`I${row}`).formulas=[[`=G${row}/J${row}`]];
      }
    }
    const accounting=excluded+1,metricSource=list.length*2+4+i;
    const labels=LAYOUT.time_rows.slice(2);
    for(let k=0;k<5;k++){
      const row=accounting+k;
      summary.getRange(`A${row}:C${row}`).values=[[report.rank,report.label,labels[k]]];
      summary.getRange(`J${row}`).values=[[report.metadata.window_duration_us/1000]];
      summary.getRange(`G${row}`).formulas=[[`=F${row}/1000`]];
      summary.getRange(`I${row}`).formulas=[[`=G${row}/J${row}`]];
    }
    summary.getRange(`D${accounting}:F${accounting}`).formulas=[[
      `=SUM(D${total}:D${excluded})`,`=SUM(E${total}:E${excluded})`,`=SUM(F${total}:F${excluded})`]];
    summary.getRange(`F${accounting+1}`).formulas=[[`=F${accounting+2}-F${accounting}`]];
    summary.getRange(`F${accounting+2}`).formulas=[[`='选窗依据'!D${metricSource}`]];
    summary.getRange(`F${accounting+3}`).formulas=[[`=F${accounting+4}-F${accounting+2}`]];
    summary.getRange(`F${accounting+4}`).formulas=[[`='选窗依据'!C${metricSource}`]];
  }
  summary.getRange(`A2:K${rowCount}`).format.font={name:LAYOUT.font,size:LAYOUT.body_size};
  summary.getRange('A2').format.font={name:LAYOUT.font,size:LAYOUT.title_size,bold:true};
  summary.getRange('A3:A4').format.font={name:LAYOUT.font,size:LAYOUT.body_size,color:LAYOUT.note_text,italic:true};
  header(summary,'A5:K5');
  const summaryWidths=LAYOUT.summary_widths;
  for(let i=0;i<11;i++)summary.getRangeByIndexes(0,i,rowCount,1).format.columnWidth=summaryWidths[i];
  summary.getRange(`A6:K${rowCount}`).format.rowHeight=LAYOUT.body_height;
  summary.getRange(`D6:E${rowCount}`).setNumberFormat(LAYOUT.integer_format);
  summary.getRange(`F6:G${rowCount}`).setNumberFormat(LAYOUT.duration_format);
  summary.getRange(`H6:I${rowCount}`).setNumberFormat(LAYOUT.ratio_format);
  summary.getRange(`J6:J${rowCount}`).setNumberFormat(LAYOUT.duration_format);
  for(let i=0;i<list.length;i++){
    const start=LAYOUT.summary_first_row+i*rowsPerRank,last=start+rowsPerRank-1;
    summary.getRange(`A${last-1}:K${last}`).format.font={name:LAYOUT.font,size:LAYOUT.body_size,bold:true};
    summary.getRange(`A${last}:K${last}`).format.borders={top:{style:'thin',color:LAYOUT.total_border}};
  }
  summary.freezePanes.freezeRows(5);
  summary.tables.add(`A5:K${rowCount}`,true,'CategorySummary').style=LAYOUT.table_style;
  const auditRows=list.flatMap(r=>[['开始',boundary(r,'start')],['结束',boundary(r,'end')]].map(([side,b])=>[
    r.rank,r.label,side,b.annotation.id,b.first_event.name,b.first_event.category,Number(b.first_event.offset_us),
    String(b.first_event.device??''),String(b.first_event.stream??''),String(b.first_event.correlation??''),
    b.first_event.association_basis,b.boundary_confidence,b.unlinked_near_boundary_count,
    r.metadata.device_step?.owned_events_crossing_end??0,r.metadata.device_step?.window_events_not_confirmed_owned_by_current??0,b.later_ambiguous_event_count]));
  audit.getRange('A1').write([['rank','窗口','边界','annotation ID','首设备事件','category','开始偏移 (µs)','device','stream','correlation','关联方式','置信度','前方未关联事件','本步跨窗末尾事件','窗口内未确认归属本步','后续关联歧义数'],...auditRows]);
  audit.showGridLines=false;
  audit.getRange(`A1:P${auditRows.length+1}`).format.font={name:LAYOUT.font,size:LAYOUT.body_size};
  const auditWidths=LAYOUT.evidence_widths;
  for(let i=0;i<auditWidths.length;i++)audit.getRangeByIndexes(0,i,auditRows.length+1,1).format.columnWidth=auditWidths[i];
  audit.getRange(`G2:G${auditRows.length+1}`).setNumberFormat(LAYOUT.duration_format);
  header(audit,'A1:P1');audit.freezePanes.freezeRows(1);
  const metricsHeader=auditRows.length+3;
  audit.getRange(`A${metricsHeader}:J${metricsHeader}`).values=[['rank','窗口','窗口总时间 (µs)','覆盖 (µs)','空泡 (µs)','调用加总 (µs)','重叠跨窗扣减 (µs)','跨入覆盖 (µs)','边界调整 (µs)','跨入事件数']];
  const metricRows=list.map(r=>{const c=r.metadata.window_coverage??{};return [r.rank,r.label,c.window_total_us,c.device_covered_us,c.bubble_us,c.selected_duration_sum_us,c.overlap_or_outside_deduction_us,c.carry_in_extra_coverage_us,c.net_boundary_adjustment_us,c.carry_in_event_count];});
  audit.getRange(`A${metricsHeader+1}`).write(metricRows);
  audit.getRange(`A${metricsHeader}:J${metricsHeader+list.length}`).format.font={name:LAYOUT.font,size:LAYOUT.body_size};
  audit.getRange(`C${metricsHeader+1}:I${metricsHeader+list.length}`).setNumberFormat(LAYOUT.duration_format);
  header(audit,`A${metricsHeader}:J${metricsHeader}`);
  audit.getRange(`P2:P${auditRows.length+1}`).conditionalFormats.add('CellValue',{operator:'greaterThan',formula:0,format:{fill:LAYOUT.unknown_fill,font:{color:LAYOUT.unknown_text}}});
  const versionRow=metricsHeader+list.length+3;
  audit.getRange(`A${versionRow}:B${versionRow+1}`).values=[['模板版本',LAYOUT.version],['模板SHA256',LAYOUT_SHA256]];
  audit.getRange(`A${versionRow}:B${versionRow+1}`).format.font={name:LAYOUT.font,size:LAYOUT.body_size};
  wb.recalculate();
  return wb;
}
