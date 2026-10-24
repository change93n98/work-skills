// XLSX authoring through artifact-tool. Python performs analysis and read-only extraction.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';

try {
const [jsonPath, outputPath, modules]=process.argv.slice(2);
const require=createRequire(path.join(path.resolve(modules),'__prof_resolver.cjs'));
const {Workbook,SpreadsheetFile,FileBlob}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const report=JSON.parse(await fs.readFile(jsonPath,'utf8'));
const wb=report.mode==='xlsx' ? await SpreadsheetFile.importXlsx(await FileBlob.load(report.source)) : Workbook.create();
const rawKeys=['name','record_count','total_duration_us','avg_duration_us','kernel_relative_pct','window_absolute_pct'];
let data, categoryColumn, durationColumn, countColumn, firstDataRow=2, lastDataRow;
let summaryName='分类汇总';
const existing=new Set(report.metadata.source_sheet_names??[]);
if(report.mode==='xlsx'){
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
}else{
  // Create the summary first so the main answer opens before the raw detail.
  wb.worksheets.add(summaryName);
  data=wb.worksheets.add('数据');
  const headers=[...rawKeys,'llm-prof分类','classification_rule','semantic_type','confidence','ambiguity'];
  const rows=report.kernels.map(r=>[...rawKeys.map(k=>r[k]??null),r.category,
    r.classification.rule_id,r.classification.semantic_type,r.classification.confidence,
    r.classification.ambiguity_reasons.join('; ')]);
  data.getRange('A1').write([headers,...rows]);
  categoryColumn=6;durationColumn=2;countColumn=1;lastDataRow=rows.length+1;
  data.showGridLines=false;
  data.getRange(`A1:K${lastDataRow}`).format.font={name:'Arial',size:10};
  data.getRange(`A1:K${lastDataRow}`).format.verticalAlignment='center';
  data.getRange('A1:K1').format={fill:'#253B58',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:36,wrapText:true};
  data.getRange('A1:A'+lastDataRow).format.columnWidth=86;
  data.getRange('B1:B'+lastDataRow).format.columnWidth=16;
  data.getRange('C1:F'+lastDataRow).format.columnWidth=23;
  data.getRange('G1:G'+lastDataRow).format.columnWidth=24;
  data.getRange('H1:I'+lastDataRow).format.columnWidth=38;
  data.getRange('J1:J'+lastDataRow).format.columnWidth=15;
  data.getRange('K1:K'+lastDataRow).format.columnWidth=58;
  data.getRange(`B2:B${lastDataRow}`).setNumberFormat('#,##0');
  data.getRange(`C2:D${lastDataRow}`).setNumberFormat('#,##0.000');
  data.getRange(`E2:F${lastDataRow}`).setNumberFormat('0.00');
  data.freezePanes.freezeRows(1);
}
const letter=index=>{let s='';for(let n=index+1;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;};
const quote=s=>"'"+s.replaceAll("'","''")+"'";
const categoryRef=`${quote(data.name)}!$${letter(categoryColumn)}$${firstDataRow}:$${letter(categoryColumn)}$${lastDataRow}`;
const durRef=`${quote(data.name)}!$${letter(durationColumn)}$${firstDataRow}:$${letter(durationColumn)}$${lastDataRow}`;
const countRef=`${quote(data.name)}!$${letter(countColumn)}$${firstDataRow}:$${letter(countColumn)}$${lastDataRow}`;
const sourceWindowColumn=report.metadata.headers?.indexOf('window_absolute_pct')??-1;
const windowRef=sourceWindowColumn<0?null:`${quote(data.name)}!$${letter(sourceWindowColumn)}$${firstDataRow}:$${letter(sourceWindowColumn)}$${lastDataRow}`;
const summary=report.mode==='xlsx'?wb.worksheets.add(summaryName):wb.worksheets.getItem(summaryName);
summary.showGridLines=false;
summary.getRange('A2').values=[['Kernel 分类耗时']];
summary.getRange('A3').values=[[report.mode==='window'
  ? `${report.metadata.stage} · ${report.metadata.start_us}–${report.metadata.end_us} µs · 窗口 ${report.metadata.window_duration_us.toFixed(3)} µs`
  : '按最新分类重新汇总。原始文件及既有分类列保留。']];
summary.getRange('A5:F5').values=[['算子类别','调用次数','总耗时 (µs)','总耗时 (ms)','设备 kernel 占比','窗口占比']];
summary.getRange('A6:A11').values=report.summary.map(s=>[s.category]);
for(let r=6;r<=11;r++){
  summary.getRange(`B${r}:F${r}`).formulas=[[
    `=SUMIFS(${countRef},${categoryRef},A${r})`,
    `=SUMIFS(${durRef},${categoryRef},A${r})`,`=C${r}/1000`,
    `=IF($C$12=0,"n.a.",C${r}/$C$12)`,
    report.mode==='window'?`=C${r}/${report.metadata.window_duration_us}`:
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
summary.getRange('A2:F22').format.font={name:'Arial',size:10};
summary.getRange('A2:F22').format.verticalAlignment='center';
summary.getRange('A2').format.font={name:'Arial',size:14,bold:true};
summary.getRange('A3').format.font={name:'Arial',size:10,italic:true,color:'#5C6570'};
summary.getRange('A5:F5').format={fill:'#253B58',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:30,horizontalAlignment:'center'};
summary.getRange('A6:F14').format.rowHeight=24;
summary.getRange('A12:F12').format.font={name:'Arial',size:10,bold:true};
summary.getRange('A12:F12').format.borders={top:{style:'thin',color:'#AEB9C7'}};
summary.getRange('A1:A22').format.columnWidth=31;
summary.getRange('B1:B22').format.columnWidth=16;
summary.getRange('C1:D22').format.columnWidth=23;
summary.getRange('E1:F22').format.columnWidth=23;
summary.getRange('B6:B14').setNumberFormat('#,##0');
summary.getRange('C6:D14').setNumberFormat('#,##0.000');
summary.getRange('E6:F14').setNumberFormat('0.00%');
wb.recalculate();
const check=await wb.inspect({kind:'table',range:`${quote(summary.name)}!A5:F14`,include:'values,formulas',tableMaxRows:10,tableMaxCols:6,maxChars:3500});
console.log(check.ndjson);
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},maxChars:1500});
console.log(errors.ndjson);
await (await SpreadsheetFile.exportXlsx(wb)).save(outputPath);
console.log('Saved',outputPath);
process.exit(0);
} catch(error) {
  console.error('XLSX export failed: '+error.message);
  process.exit(1);
}
