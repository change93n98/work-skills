import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {randomUUID} from 'node:crypto';
import {createClassificationWorkbook,gdnOperators,LAYOUT,reportCategories,totalCategoryLabel} from './report_template.mjs';

function appendSummary(wb,report,rowGroups){
 const existing=new Set(report.metadata.source_sheet_names??[]);let summaryName='最新分类汇总';
 for(let i=2;existing.has(summaryName);i++)summaryName='最新分类汇总'+i;
 const data=wb.worksheets.getItem(report.metadata.source_sheet),column=report.metadata.source_columns,last=report.metadata.source_row_count;
 let label='最新分类结果';for(let i=2;report.metadata.headers.includes(label);i++)label='最新分类结果'+i;
 const newColumn=data.getRangeByIndexes(0,column,last,1);
 newColumn.copyFrom(data.getRangeByIndexes(0,column-1,last,1),'all');newColumn.conditionalFormats.deleteAll();newColumn.format.columnWidth=24;
 data.getCell(0,column).values=[[label]];for(const r of report.kernels)data.getCell(r.source_row-1,column).values=[[r.category]];
 const letter=index=>{let s='';for(let n=index+1;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;};
 const quote=s=>"'"+s.replaceAll("'","''")+"'";
 const ref=index=>`${quote(data.name)}!$${letter(index)}$2:$${letter(index)}$${last}`;
 const categoryRef=ref(column),durationRef=ref(report.metadata.headers.indexOf('total_duration_us')),countRef=ref(report.metadata.headers.indexOf('record_count'));
 const windowIndex=report.metadata.headers.indexOf('window_absolute_pct'),windowRef=windowIndex<0?null:ref(windowIndex);
 const first=6,count=report.summary.length;
 const categories=report.summary.map(s=>s.category);
 if(JSON.stringify(categories)!==JSON.stringify(reportCategories(categories)))throw new Error('Expected ordered report categories');
 const operators=gdnOperators(report),gdnIndex=categories.indexOf('GDN'),gdnRow=first+gdnIndex;
 const lastColumn=operators.length?'H':'F';
 const total=first+count+operators.length,excluded=total+1,accounting=excluded+1,adjust=accounting+1,covered=accounting+2,bubble=accounting+3,window=accounting+4;
 const noteStart=window+3,noteEnd=noteStart+5,summary=wb.worksheets.add(summaryName);
 summary.showGridLines=false;summary.getRange('A2').values=[['Kernel 分类耗时']];
 summary.getRange('A3').values=[[operators.length?'点击行号左侧的「+」展开 GDN 算子。原有分类列保留。':'按最新分类重新汇总。原始文件及既有分类列保留。']];
 const headers=['算子类别','调用次数','总耗时 (µs)','总耗时 (ms)','设备 kernel 占比','窗口占比'];
 if(operators.length)headers.push('kernel种类','GDN 内占比');
 summary.getRange(`A5:${lastColumn}5`).values=[headers];
 for(const [i,item] of report.summary.entries()){
  const row=first+i+(i>gdnIndex?operators.length:0);
  summary.getCell(row-1,0).values=[[item.category]];
  summary.getRange(`B${row}:F${row}`).formulas=[[
   `=SUMIFS(${countRef},${categoryRef},A${row})`,`=SUMIFS(${durationRef},${categoryRef},A${row})`,`=C${row}/1000`,
   `=IF($C$${total}=0,"n.a.",C${row}/$C$${total})`,
   item.window_absolute_pct==null?'="n.a."':`=SUMIFS(${windowRef},${categoryRef},A${row})/100`]];
 }
 if(operators.length){
  rowGroups.push({parent:gdnRow,first:gdnRow+1,last:gdnRow+operators.length});
  summary.getRange(`G${gdnRow}`).values=[[report.summary[gdnIndex].kernel_kinds]];
  for(const [i,item] of operators.entries()){
   const row=gdnRow+i+1;
   summary.getRange(`A${row}:G${row}`).values=[[`    ${item.label}`,item.calls,item.us,item.us/1000,null,null,item.names.size]];
   summary.getRange(`H${row}`).formulas=[[`=IF($C$${gdnRow}=0,"n.a.",C${row}/$C$${gdnRow})`]];
  }
  summary.getRange(`G${gdnRow}:G${gdnRow+operators.length}`).setNumberFormat(LAYOUT.integer_format);
  summary.getRange(`H${gdnRow+1}:H${gdnRow+operators.length}`).setNumberFormat(LAYOUT.ratio_format);
 }
 const categorySum=column=>operators.length?
  `SUM(${column}${first}:${column}${gdnRow},${column}${gdnRow+operators.length+1}:${column}${total-1})`:
  `SUM(${column}${first}:${column}${total-1})`;
 summary.getRange(`A${total}`).values=[[totalCategoryLabel(count)]];
 summary.getRange(`B${total}:F${total}`).formulas=[[
  `=${categorySum('B')}`,`=${categorySum('C')}`,`=C${total}/1000`,
  `=IF(C${total}=0,"n.a.",${categorySum('E')})`,`=IF(COUNT(F${first}:F${total-1})=0,"n.a.",${categorySum('F')})`]];
 summary.getRange(`A${excluded}`).values=[[LAYOUT.time_rows[1]]];
 summary.getRange(`B${excluded}:F${excluded}`).values=[[report.excluded.record_count,report.excluded.total_duration_us,report.excluded.total_duration_us/1000,null,report.excluded.window_absolute_pct==null?null:report.excluded.window_absolute_pct/100]];
 summary.getRange(`A${accounting}:A${window}`).values=LAYOUT.time_rows.slice(2).map(s=>[s]);
 summary.getRange(`B${accounting}:D${accounting}`).formulas=[[
  `=SUM(B${total}:B${excluded})`,`=SUM(C${total}:C${excluded})`,`=C${accounting}/1000`]];
 const coverage=report.metadata.window_coverage;
 if(coverage){
  summary.getRange(`C${covered}`).values=[[coverage.device_covered_us]];summary.getRange(`C${window}`).values=[[coverage.window_total_us]];
  summary.getRange(`C${adjust}`).formulas=[[`=C${covered}-C${accounting}`]];summary.getRange(`C${bubble}`).formulas=[[`=C${window}-C${covered}`]];
  for(let row=accounting;row<=window;row++){summary.getRange(`D${row}`).formulas=[[`=C${row}/1000`]];summary.getRange(`F${row}`).formulas=[[`=C${row}/$C$${window}`]];}
 }else summary.getRange(`C${adjust}:D${window}`).values=Array.from({length:4},()=>['n.a.','n.a.']);
 const notes=[coverage?'空泡＝窗口总时间−裁剪去重后的设备事件区间并集，覆盖包含WAIT/SET。':'缺少逐事件 ts/dur 和精确窗口，覆盖及空泡不可计算。',
  '分类占比包含全部分类，排除WAIT/SET；MoE专家group GEMM单列。',
  '明细前六列保持原SQL口径。多流可能重叠，分类dur加总不等于设备覆盖时长。',
  `规则版本 ${report.classification_rules.version}，平台 ${report.classification_rules.platform}。`,
  `未知类别 ${report.kernels.filter(k=>k.classification.confidence==='unknown').length} 个名字，存在歧义 ${report.kernels.filter(k=>k.classification.ambiguity_reasons.length).length} 个名字。`,
  `来源：${path.basename(report.source)}`];
 summary.getRange(`A${noteStart}:A${noteEnd}`).values=notes.map(n=>[n]);
 summary.getRange(`A2:${lastColumn}${noteEnd}`).format.font={name:LAYOUT.font,size:LAYOUT.body_size};summary.getRange(`A2:${lastColumn}${noteEnd}`).format.verticalAlignment='center';
 summary.getRange('A2').format.font={name:LAYOUT.font,size:LAYOUT.title_size,bold:true};summary.getRange('A3').format.font={name:LAYOUT.font,size:LAYOUT.body_size,color:LAYOUT.note_text,italic:true};
 summary.getRange(`A5:${lastColumn}5`).format={fill:LAYOUT.header_fill,font:{name:LAYOUT.font,size:LAYOUT.body_size,bold:true,color:LAYOUT.header_text},rowHeight:LAYOUT.header_height,horizontalAlignment:'center',wrapText:true};
 summary.getRange(`A${first}:${lastColumn}${window}`).format.rowHeight=LAYOUT.body_height;summary.getRange(`B${first}:B${accounting}`).setNumberFormat(LAYOUT.integer_format);
 summary.getRange(`C${first}:D${window}`).setNumberFormat(LAYOUT.duration_format);summary.getRange(`E${first}:F${window}`).setNumberFormat(LAYOUT.ratio_format);
 summary.getRange(`A${total}:F${total}`).format.font={name:LAYOUT.font,size:LAYOUT.body_size,bold:true};summary.getRange(`A${bubble}:F${window}`).format.font={name:LAYOUT.font,size:LAYOUT.body_size,bold:true};
 summary.getRange(`A${total}:F${total}`).format.borders={top:{style:'thin',color:LAYOUT.total_border}};
 summary.getRange(`A1:A${noteEnd}`).format.columnWidth=operators.length?38:31;summary.getRange(`B1:B${noteEnd}`).format.columnWidth=16;summary.getRange(`C1:${lastColumn}${noteEnd}`).format.columnWidth=23;
 summary.freezePanes.freezeRows(5);summary.tables.add(`A5:${lastColumn}${window}`,true,'LatestClassificationSummary').style=LAYOUT.table_style;
 return `'${summaryName}'!A5:${lastColumn}${window}`;
}

const outlineTag='<x:outlinePr summaryBelow="0" showOutlineSymbols="1" />';
const summaryPart=number=>`xl/worksheets/sheet${number}.xml`;

async function applySummaryOutline(zip,part,attributes){
 let xml=await zip.file(part).async('string');
 if(!xml.includes('<x:sheetViews>')||!xml.includes('<x:sheetFormatPr ')||xml.includes('<x:sheetPr')){
  throw new Error('Unexpected generated summary XML for row outlines');
 }
 xml=xml.replace('<x:sheetViews>',`<x:sheetPr>${outlineTag}</x:sheetPr><x:sheetViews>`)
  .replace('<x:sheetFormatPr ','<x:sheetFormatPr outlineLevelRow="1" ');
 let patched=0;
 xml=xml.replace(/(<x:row r="(\d+)")([^>]*>)/g,(tag,head,index,rest)=>{
  const attr=attributes.get(Number(index));
  if(!attr)return tag;
  patched++;
  return head+' '+attr+rest.replace(/\s(?:hidden|outlineLevel|collapsed)="[^"]*"/g,'');
 });
 if(patched!==attributes.size)throw new Error('Missing generated rows for GDN outline');
 zip.file(part,xml);
}

async function saveOutlinedSummary(file, outputPath, sheetNumber, rowGroups, JSZip, sourcePath) {
 // Artifact Tool authors and calculates the workbook. Add only the outline
 // metadata to its generated worksheets, leaving cached cells intact.
 const tempPath=outputPath+'.'+randomUUID()+'.xlsx';
 try {
  await file.save(tempPath);
  const zip=await JSZip.loadAsync(await fs.readFile(tempPath));
  if(sourcePath){
   const sourceZip=await JSZip.loadAsync(await fs.readFile(sourcePath));
   for(let i=1;i<sheetNumber;i++){
    const part=summaryPart(i),original=await sourceZip.file(part)?.async('string');
    // Keep outlines on summaries produced by this exporter before reclassification.
    if(!original?.includes(outlineTag))continue;
    const existing=new Map([...original.matchAll(/<x:row r="(\d+)" (collapsed="1"|outlineLevel="1" hidden="1")/g)]
     .map(([,index,attr])=>[Number(index),attr]));
    if(existing.size)await applySummaryOutline(zip,part,existing);
   }
  }
  const attributes=new Map();
  for(const {parent,first,last} of rowGroups){
   attributes.set(parent,'collapsed="1"');
   for(let row=first;row<=last;row++)attributes.set(row,'outlineLevel="1" hidden="1"');
  }
  await applySummaryOutline(zip,summaryPart(sheetNumber),attributes);
  await fs.writeFile(tempPath,await zip.generateAsync({type:'nodebuffer',compression:'DEFLATE'}));
  await fs.rename(tempPath,outputPath);
 } finally {
  await fs.rm(tempPath,{force:true});
  await fs.rm(tempPath+'.inspect.ndjson',{force:true});
 }
}

try{
 const [jsonPath,outputPath,modules]=process.argv.slice(2),require=createRequire(path.join(path.resolve(modules),'__prof_resolver.cjs'));
 const {Workbook,SpreadsheetFile,FileBlob}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
 const report=JSON.parse(await fs.readFile(jsonPath,'utf8'));let wb,inspectRange;
 const rowGroups=[];
 let summarySheetNumber=1;
 if(report.mode==='xlsx'){
  wb=await SpreadsheetFile.importXlsx(await FileBlob.load(report.source));
  inspectRange=appendSummary(wb,report,rowGroups);
  summarySheetNumber=wb.worksheets.items.length;
 }
 else{
  const reports=report.reports??[report],categoryCount=reportCategories(reports.flatMap(r=>r.summary.map(s=>s.category))).length;
  wb=createClassificationWorkbook(Workbook,reports,{title:report.title??report.group??path.basename(outputPath,'.xlsx'),rowGroups});
  const children=rowGroups.reduce((count,group)=>count+group.last-group.first+1,0);
  inspectRange=`'分类汇总'!A5:${rowGroups.length?'L':'K'}${5+reports.length*(categoryCount+7)+children}`;
 }
 wb.recalculate();console.log((await wb.inspect({kind:'table',range:inspectRange,include:'values,formulas',tableMaxRows:15,tableMaxCols:11,maxChars:1800})).ndjson);
 console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},maxChars:1200})).ndjson);
 await fs.mkdir(path.dirname(outputPath),{recursive:true});
 const file=await SpreadsheetFile.exportXlsx(wb);
 if(rowGroups.length)await saveOutlinedSummary(file,outputPath,summarySheetNumber,rowGroups,require('jszip'),
  report.mode==='xlsx'?report.source:null);
 else await file.save(outputPath);
 console.log('Saved',outputPath,'layout',LAYOUT.version);process.exit(0);
}catch(error){console.error('XLSX export failed: '+error.message);process.exit(1);}
