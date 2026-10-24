// All newly generated native reports use the approved versioned renderer.
// Existing XLSX input sheets keep their supplied structure and formatting.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {createClassificationWorkbook,LAYOUT} from './report_template.mjs';

try {
 const [jsonPath,outputPath,modules]=process.argv.slice(2);
 const require=createRequire(path.join(path.resolve(modules),'__prof_resolver.cjs'));
 const {Workbook,SpreadsheetFile,FileBlob}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
 const report=JSON.parse(await fs.readFile(jsonPath,'utf8'));
 let wb,inspectRange;
 if(report.mode!=='xlsx'){
  wb=createClassificationWorkbook(Workbook,report.reports??[report],{title:report.title??report.group??path.basename(outputPath,'.xlsx')});
  inspectRange="'分类汇总'!A5:K18";
 }else{
  wb=await SpreadsheetFile.importXlsx(await FileBlob.load(report.source));
  let data,summaryName,categoryColumn,durationColumn,countColumn,firstDataRow=2,lastDataRow;
  const existing=new Set(report.metadata.source_sheet_names??[]);
  summaryName='最新分类汇总';
  for(let i=2;existing.has(summaryName);i++)summaryName='最新分类汇总'+i;
  data=wb.worksheets.getItem(report.metadata.source_sheet);
  let header='最新分类结果';
  for(let i=2;report.metadata.headers.includes(header);i++)header='最新分类结果'+i;
  categoryColumn=report.metadata.source_columns;
  durationColumn=report.metadata.headers.indexOf('total_duration_us');
  countColumn=report.metadata.headers.indexOf('record_count');
  data.getCell(0,categoryColumn).values=[[header]];
  for(const r of report.kernels)data.getCell(r.source_row-1,categoryColumn).values=[[r.category]];
  lastDataRow=report.metadata.source_row_count;
  const col=data.getRangeByIndexes(0,categoryColumn,lastDataRow,1);
  col.copyFrom(data.getRangeByIndexes(0,categoryColumn-1,lastDataRow,1),'all');
  // Restore the new contents after copying the neighboring style.
  data.getCell(0,categoryColumn).values=[[header]];
  for(const r of report.kernels)data.getCell(r.source_row-1,categoryColumn).values=[[r.category]];
  col.conditionalFormats.deleteAll();
  col.format.columnWidth=24;
const letter=index=>{let s='';for(let n=index+1;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;};
const quote=s=>"'"+s.replaceAll("'","''")+"'";
const categoryRef=`${quote(data.name)}!$${letter(categoryColumn)}$${firstDataRow}:$${letter(categoryColumn)}$${lastDataRow}`;
const durRef=`${quote(data.name)}!$${letter(durationColumn)}$${firstDataRow}:$${letter(durationColumn)}$${lastDataRow}`;
const countRef=`${quote(data.name)}!$${letter(countColumn)}$${firstDataRow}:$${letter(countColumn)}$${lastDataRow}`;
const sourceWindowColumn=report.metadata.headers?.indexOf('window_absolute_pct')??-1;
const windowRef=sourceWindowColumn<0?null:`${quote(data.name)}!$${letter(sourceWindowColumn)}$${firstDataRow}:$${letter(sourceWindowColumn)}$${lastDataRow}`;
const summary=wb.worksheets.add(summaryName);
summary.showGridLines=false;
summary.getRange('A2').values=[['Kernel 分类耗时']];
summary.getRange('A3').values=[[report.mode!=='xlsx'
  ? `${report.metadata.stage} · ${report.metadata.start_us}–${report.metadata.end_us} µs · 窗口 ${report.metadata.window_duration_us.toFixed(3)} µs`
  : '按最新分类重新汇总。原始文件及既有分类列保留。']];
summary.getRange('A5:F5').values=[['算子类别','调用次数','总耗时 (µs)','总耗时 (ms)','设备 kernel 占比','窗口占比']];
summary.getRange('A6:A11').values=report.summary.map(s=>[s.category]);
for(let r=6;r<=11;r++){
  summary.getRange(`B${r}:F${r}`).formulas=[[
    `=SUMIFS(${countRef},${categoryRef},A${r})`,
    `=SUMIFS(${durRef},${categoryRef},A${r})`,`=C${r}/1000`,
    `=IF($C$12=0,"n.a.",C${r}/$C$12)`,
    report.mode!=='xlsx'?`=C${r}/${report.metadata.window_duration_us}`:
      report.summary[r-6].window_absolute_pct===null?'="n.a."':`=SUMIFS(${windowRef},${categoryRef},A${r})/100`
  ]];
}
summary.getRange('A12').values=[['六类合计']];
summary.getRange('B12:F12').formulas=[['=SUM(B6:B11)','=SUM(C6:C11)','=SUM(D6:D11)',
  '=IF(C12=0,"n.a.",SUM(E6:E11))','=IF(COUNT(F6:F11)=0,"n.a.",SUM(F6:F11))']];
summary.getRange('A14').values=[['排除项（WAIT/SET 等）']];
summary.getRange('B14:F14').values=[[report.excluded.record_count,report.excluded.total_duration_us,
  report.excluded.total_duration_us/1000,null,
  report.excluded.window_absolute_pct===null?null:report.excluded.window_absolute_pct/100]];
const notes=[
  '设备 kernel 占比排除 WAIT/SET。窗口占比以整个选定时间段为分母。',
  '明细前六列保持原 SQL 口径，相对占比包含 WAIT/SET。',
  '按开始时间入窗，保留完整 dur。跨流可能重叠，窗口占比不等于利用率。',
  `规则版本 ${report.classification_rules.version}，平台 ${report.classification_rules.platform}。`,
  `未知类别 ${report.kernels.filter(r=>r.classification.confidence==='unknown').length} 个名字，存在歧义 ${report.kernels.filter(r=>r.classification.ambiguity_reasons.length).length} 个名字。`,
  `来源：${path.basename(report.source)}`
];
summary.getRange('A17:A22').values=notes.map(n=>[n]);
summary.getRange('A2:F22').format.font={name:LAYOUT.font,size:LAYOUT.body_size};
summary.getRange('A2:F22').format.verticalAlignment='center';
summary.getRange('A2').format.font={name:LAYOUT.font,size:LAYOUT.title_size,bold:true};
summary.getRange('A3').format.font={name:LAYOUT.font,size:LAYOUT.body_size,italic:true,color:LAYOUT.note_text};
summary.getRange('A5:F5').format={fill:LAYOUT.header_fill,font:{name:LAYOUT.font,size:LAYOUT.body_size,bold:true,color:LAYOUT.header_text},rowHeight:LAYOUT.header_height,horizontalAlignment:'center'};
summary.getRange('A6:F14').format.rowHeight=LAYOUT.body_height;
summary.getRange('A12:F12').format.font={name:LAYOUT.font,size:LAYOUT.body_size,bold:true};
summary.getRange('A12:F12').format.borders={top:{style:'thin',color:LAYOUT.total_border}};
summary.getRange('A1:A22').format.columnWidth=31;
summary.getRange('B1:B22').format.columnWidth=16;
summary.getRange('C1:D22').format.columnWidth=23;
summary.getRange('E1:F22').format.columnWidth=23;
summary.getRange('B6:B14').setNumberFormat(LAYOUT.integer_format);
summary.getRange('C6:D14').setNumberFormat(LAYOUT.duration_format);
summary.getRange('E6:F14').setNumberFormat(LAYOUT.ratio_format);
if(report.metadata.window_coverage){
  const coverage=report.metadata.window_coverage;
  summary.getRange('A13:F13').copyFrom(summary.getRange('A14:F14'),'all');
  summary.getRange('A14:A18').values=[['设备调用合计（加总）'],['重叠/边界调整'],['设备覆盖时长（去重）'],['空泡'],['窗口总时间']];
  summary.getRange('B14:F18').clear({applyTo:'contents'});
  summary.getRange('C14').formulas=[['=SUM(C12:C13)']];
  summary.getRange('C15').formulas=[['=C16-C14']];
  summary.getRange('C16').values=[[coverage.device_covered_us]];
  summary.getRange('C17').formulas=[['=C18-C16']];
  summary.getRange('C18').values=[[coverage.window_total_us]];
  for(let row=14;row<=18;row++){
    summary.getRange(`D${row}`).formulas=[[`=C${row}/1000`]];
    summary.getRange(`F${row}`).formulas=[[`=C${row}/$C$18`]];
  }
  summary.getRange('A14:F18').format.rowHeight=LAYOUT.body_height;
  summary.getRange('C14:D18').setNumberFormat(LAYOUT.duration_format);
  summary.getRange('F14:F18').setNumberFormat(LAYOUT.ratio_format);
  summary.getRange('A17:F18').format.font={name:LAYOUT.font,size:LAYOUT.body_size,bold:true};
  summary.getRange('A17:A22').clear({applyTo:'contents'});
  summary.getRange('A17:A18').values=[['空泡'],['窗口总时间']];
  summary.getRange('A21:A26').values=[
    ['总时间为片选窗口，空泡 = 窗口总时间 − 设备事件覆盖时长。'],
    ['覆盖时间按逐事件 ts/dur 合并重叠并裁剪到窗口，包含 WAIT/SET。'],
    ['分类耗时仍由明细加总；重叠/边界调整不改变原始分类数据。'],
    [notes[3]],[notes[4]],[notes[5]]];
  summary.getRange('A21:F26').format.font={name:LAYOUT.font,size:LAYOUT.body_size};
}

if(!report.metadata.window_coverage){
 summary.getRange('A13:F13').copyFrom(summary.getRange('A14:F14'),'all');
 summary.getRange('A13').values=[[LAYOUT.time_rows[1]]];
 summary.getRange('A14:A18').values=LAYOUT.time_rows.slice(2).map(s=>[s]);
 summary.getRange('B14:F18').clear({applyTo:'contents'});
 summary.getRange('B14:D14').formulas=[['=SUM(B12:B13)','=SUM(C12:C13)','=C14/1000']];
 summary.getRange('C15:D18').values=Array.from({length:4},()=>['n.a.','n.a.']);
 summary.getRange('A19:A26').clear({applyTo:'contents'});
 summary.getRange('A21:A24').values=[['缺少逐事件 ts/dur 和精确窗口，覆盖及空泡不可计算。'],[notes[3]],[notes[4]],[notes[5]]];
 summary.getRange('A21:F24').format.font={name:LAYOUT.font,size:LAYOUT.body_size};
}
summary.getRange('A17:F18').format.font={name:LAYOUT.font,size:LAYOUT.body_size,bold:true};
summary.freezePanes.freezeRows(5);
summary.tables.add('A5:F18',true,'LatestClassificationSummary').style=LAYOUT.table_style;
inspectRange=`'${summaryName}'!A5:F18`;

  wb.recalculate();
 }
 console.log((await wb.inspect({kind:'table',range:inspectRange,include:'values,formulas',tableMaxRows:14,tableMaxCols:11,maxChars:1800})).ndjson);
 console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},maxChars:1200})).ndjson);
 await fs.mkdir(path.dirname(outputPath),{recursive:true});
 await (await SpreadsheetFile.exportXlsx(wb)).save(outputPath);
 console.log('Saved',outputPath,'layout',LAYOUT.version);
 process.exit(0);
}catch(error){
 console.error('XLSX export failed: '+error.message);
 process.exit(1);
}
