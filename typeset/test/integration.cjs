// AGPL-3.0-only. Run the actual engine with Zotero's PDF.js and browser Web APIs.
// Browser/IO adapters are test infrastructure; no private client or native runtime is required.
const {test,before,after}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),http=require('node:http'),crypto=require('node:crypto'),{spawnSync}=require('node:child_process');
const {chromium}=require('playwright');
const engine=path.resolve(__dirname,'..'),tmp=fs.mkdtempSync(path.join(os.tmpdir(),'twintext-zotero-runtime-')),dataDir=path.join(tmp,'data');fs.mkdirSync(dataDir);
let browser,page,server,origin,pdfRoot,diagnostics=[];
function fixture(){
 const streams=['BT /F1 18 Tf 60 720 Td (Modular PDF document) Tj ET\nBT /F1 12 Tf 60 660 Td (This paragraph tests translation and searchable output.) Tj ET','BT /F1 12 Tf 60 700 Td (Second page remains original for selected page translation.) Tj ET'];
 streams[1]=[
   'BT /F1 12 Tf 60 520 Td (Second page remains original for selected page translation.) Tj ET',
   'BT /F1 12 Tf 0 1 -1 0 190 120 Tm (Counterclockwise sample) Tj ET',
   'q 0 -1 1 0 460 380 cm BT /F1 12 Tf (Clockwise sample) Tj ET Q'
 ].join('\n');
 const objects=['<< /Type /Catalog /Pages 2 0 R >>','<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>',...streams.flatMap((s,i)=>[`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${i?'792 612':'612 792'}] /Resources << /Font << /F1 7 0 R >> >> /Contents ${4+i*2} 0 R >>`,`<< /Length ${Buffer.byteLength(s)} >>\nstream\n${s}\nendstream`]),'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
 let pdf='%PDF-1.7\n';const offsets=[0];objects.forEach((text,i)=>{offsets.push(Buffer.byteLength(pdf));pdf+=`${i+1} 0 obj\n${text}\nendobj\n`;});const start=Buffer.byteLength(pdf);pdf+=`xref\n0 ${objects.length+1}\n0000000000 65535 f \n`+offsets.slice(1).map(n=>`${String(n).padStart(10,'0')} 00000 n \n`).join('')+`trailer\n<< /Size ${objects.length+1} /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`;return Buffer.from(pdf);
}
const input=fixture(),hash=b=>crypto.createHash('sha256').update(b).digest('hex');fs.writeFileSync(path.join(dataDir,'input.pdf'),input);
before(async()=>{
 pdfRoot=process.env.TWINTEXT_ZOTERO_PDF_DIR;
 if(!pdfRoot){
  pdfRoot=path.join(tmp,'pdf');const app=process.env.TWINTEXT_ZOTERO_APP||'/Applications/Zotero.app';
  const extraction=spawnSync('python3',['-c',`import zipfile,sys,pathlib
with zipfile.ZipFile(sys.argv[1]) as z:
 for n in z.namelist():
  if n.startswith('resource/reader/pdf/') and not n.endswith('/'):
   p=pathlib.Path(sys.argv[2])/n[len('resource/reader/pdf/'):];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(n))`,path.join(app,'Contents/Resources/app/omni.ja'),pdfRoot],{encoding:'utf8'});
  assert.equal(extraction.status,0,extraction.stderr);
 }
 server=http.createServer((req,res)=>{
  res.setHeader('Cross-Origin-Opener-Policy','same-origin');res.setHeader('Cross-Origin-Embedder-Policy','require-corp');res.setHeader('Cross-Origin-Resource-Policy','same-origin');
  try{
   const pathname=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
   if(pathname==='/'){res.setHeader('Content-Type','text/html');res.end('<!doctype html><title>Engine QA</title>');return;}
   const prefix=pathname.startsWith('/engine/')?'/engine/':pathname.startsWith('/zotero/')?'/zotero/':null;if(!prefix){res.statusCode=404;res.end();return;}
   const base=prefix==='/engine/'?engine:pdfRoot,file=path.resolve(base,pathname.slice(prefix.length));if(!file.startsWith(path.resolve(base)+path.sep))throw Error('Invalid path');
   res.setHeader('Content-Type',/\.m?js$/.test(file)?'application/javascript':file.endsWith('.wasm')?'application/wasm':'application/octet-stream');res.end(fs.readFileSync(file));
  }catch(error){res.statusCode=404;res.end(String(error.message));}
 });await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));origin=`http://127.0.0.1:${server.address().port}`;
 browser=await chromium.launch({headless:true,executablePath:process.env.TWINTEXT_BROWSER,args:['--disable-gpu']});page=await browser.newPage();page.on('pageerror',error=>diagnostics.push(error.message));await page.goto(origin);
 const local=file=>{assert(file.startsWith('/data/'));const dest=path.resolve(dataDir,file.slice(6));assert(dest.startsWith(dataDir+path.sep));return dest;};
 await page.exposeFunction('readFile',file=>Array.from(fs.readFileSync(local(file))));
 await page.exposeFunction('readJSON',file=>JSON.parse(fs.readFileSync(local(file),'utf8')));
 await page.exposeFunction('writeFile',(file,bytes)=>{const dest=local(file);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.writeFileSync(dest+'.tmp',Buffer.from(bytes));fs.renameSync(dest+'.tmp',dest);});
 await page.exposeFunction('writeJSON',(file,value)=>{fs.writeFileSync(local(file),JSON.stringify(value));});
 const scripts=JSON.parse(fs.readFileSync(path.join(engine,'runtime.json'))).scripts.map(n=>fs.readFileSync(path.join(engine,n),'utf8'));
 await page.evaluate(async({origin,scripts,input})=>{
  const pdfjs=await import(origin+'/zotero/build/pdf.mjs');pdfjs.GlobalWorkerOptions.workerSrc=origin+'/zotero/build/pdf.worker.mjs';window.pdfjs=pdfjs;
  const doc=await pdfjs.getDocument({data:Uint8Array.from(input),disableFontFace:true,useSystemFonts:false,cMapUrl:origin+'/zotero/web/cmaps/',cMapPacked:true,standardFontDataUrl:origin+'/zotero/web/standard_fonts/'}).promise;
  window.PDFViewerApplication={pdfDocument:doc};window.liveWorkers=new Set();window.workerHistory=[];
  class ChromeWorker extends Worker{constructor(url){super(url);liveWorkers.add(this);workerHistory.push(url);}terminate(){liveWorkers.delete(this);super.terminate();}}
  const boundedRequest=(work,{timeout,timeoutError})=>new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(timeoutError()),timeout);Promise.resolve().then(work).then(resolve,reject).finally(()=>clearTimeout(timer));});
  const context={crypto,TextEncoder,TextDecoder,ChromeWorker,setTimeout:setTimeout.bind(window),clearTimeout:clearTimeout.bind(window),TwinTextTypesetEnvironment:{resourceURI:origin+'/engine/',version:pdfjs.version,machine:()=>({cores:4,memoryBytes:4*1024**3}),logError:console.error,boundedRequest,
   path:{join:(...parts)=>parts.join('/').replaceAll('//','/'),parent:p=>p.slice(0,p.lastIndexOf('/')),filename:p=>p.slice(p.lastIndexOf('/')+1)},
   io:{read:async file=>Uint8Array.from(await readFile(file)),write:(file,bytes)=>writeFile(file,Array.from(bytes)),readJSON,writeJSON,makeDirectory:async()=>{}}
  }};
  for(const script of scripts)new Function(script).call(context);
  window.engineModule=context.TwinTextTypesetModule;
  window.readerWindow={eval:script=>(0,eval)(script.replaceAll('resource://zotero/reader/pdf/',origin+'/zotero/'))};
 },{origin,scripts,input:Array.from(input)});
});
after(async()=>{await browser?.close();if(server)await new Promise(resolve=>server.close(resolve));fs.rmSync(tmp,{recursive:true,force:true});});
async function run(mode,options={}){
 return page.evaluate(async({mode,options})=>{
  const controller=new AbortController(),events=[],before=workerHistory.length;
  try{
   const result=await engineModule.run({input:'/data/input.pdf',output:'/data/'+mode+'.pdf',readerWindow,pageCount:2,signal:controller.signal,options:{first:0,last:0,targetLanguage:'zh-CN',...options},
    translate:async text=>{if(mode==='cancel'){controller.abort();throw Object.assign(Error('Cancelled'),{name:'AbortError'});}if(mode==='orientations'){
      if(/counterclockwise/i.test(text))return '逆向译文';
      if(/clockwise/i.test(text))return '顺向译文';
      return '横版译文';
    }if(mode==='failure')throw Error('Synthetic provider failure');return '这是使用现有阅读环境生成的中文译文。';},onEvent:async e=>events.push(e)});
   return {result,events,workers:liveWorkers.size,created:workerHistory.slice(before)};
  }catch(error){return {error:{name:error.name,message:error.message,stack:error.stack},events,workers:liveWorkers.size,created:workerHistory.slice(before)};}
 },{mode,options});
}
test('Zotero PDF.js and browser workers generate a real Chinese PDF with previews and retained pages',{timeout:120000},async()=>{
 const r=await run('success');assert(!r.error,JSON.stringify(r));assert.equal(r.result.stats.failed,0);assert.equal(r.result.pageCount,2);assert(r.result.translatedFragments>0);assert(r.events.some(e=>e.type==='preview'));assert.equal(r.workers,0);
 const bytes=fs.readFileSync(path.join(dataDir,'success.pdf'));assert.equal(hash(bytes),r.result.sha256);assert.equal(hash(fs.readFileSync(path.join(dataDir,'input.pdf'))),hash(input));
 const text=await page.evaluate(async bytes=>{const doc=await pdfjs.getDocument({data:Uint8Array.from(bytes)}).promise;try{return await Promise.all([1,2].map(async n=>(await(await doc.getPage(n)).getTextContent()).items.map(i=>i.str).join('')));}finally{await doc.destroy();}},Array.from(bytes));assert.match(text[0],/中文译文/);assert.match(text[1],/Second page remains original/);assert.deepEqual(diagnostics,[]);
 if(process.env.TWINTEXT_QA_DIR){fs.mkdirSync(process.env.TWINTEXT_QA_DIR,{recursive:true});fs.writeFileSync(path.join(process.env.TWINTEXT_QA_DIR,'translated.pdf'),bytes);}
});
test('cached regions and background translation avoid repeated model work and previews',{timeout:120000},async()=>{
 const r=await run('cached',{backgroundExport:true});assert(!r.error,JSON.stringify(r));assert.equal(r.result.stats.failed,0);assert(!r.created.some(n=>n.endsWith('/layout-worker.js')));assert(!r.events.some(e=>e.type==='preview'));assert.equal(r.workers,0);
});
test('failed paragraphs retain source text in a partial PDF',{timeout:120000},async()=>{
 const r=await run('failure');assert(!r.error,JSON.stringify(r));assert(r.result.stats.failed>0);assert.deepEqual(r.result.failedPages,[0]);assert(r.result.file.endsWith('.partial.pdf'));assert(!fs.existsSync(path.join(dataDir,'failure.pdf')));assert.equal(r.workers,0);
});
test('cancellation releases reader state and all workers without a final PDF',{timeout:120000},async()=>{
 const r=await run('cancel');assert.equal(r.error?.name,'AbortError',JSON.stringify(r));assert(!fs.existsSync(path.join(dataDir,'cancel.pdf')));assert.equal(r.workers,0);assert.deepEqual(diagnostics,[]);
});
test('engine normalization preserves input and export cancellation is checked',async()=>{
 const result=await page.evaluate(async bytes=>{const data=Uint8Array.from(bytes),normalized=await engineModule.normalize(data);let message='';try{await engineModule.normalize(data,()=>{throw Error('export cancelled');});}catch(error){message=error.message;}return {bytes:Array.from(normalized),message};},Array.from(input));
 assert.equal(Buffer.from(result.bytes).subarray(0,5).toString(),'%PDF-');assert.equal(result.message,'export cancelled');assert.equal(hash(fs.readFileSync(path.join(dataDir,'input.pdf'))),hash(input));
});

test('landscape text and both directions of sideways text translate back to their own baselines', {timeout:120000}, async()=>{
 const r=await run('orientations',{first:1,last:1,backgroundExport:true});
 assert(!r.error,JSON.stringify(r));assert.equal(r.result.stats.failed,0);
 const bytes=fs.readFileSync(path.join(dataDir,'orientations.pdf'));
 const items=await page.evaluate(async bytes=>{
   const doc=await pdfjs.getDocument({data:Uint8Array.from(bytes)}).promise;
   try {return (await (await doc.getPage(2)).getTextContent()).items.filter(i=>i.str.trim());}
   finally {await doc.destroy();}
 },Array.from(bytes));
 for(const [word,angle,x,y] of [['横版译文',0,60,520],['逆向译文',90,190,120],['顺向译文',-90,460,380]]){
   const glyph=items.find(i=>i.str.includes(word[0]));
   assert.ok(glyph,word+' missing from '+JSON.stringify(items));
   const [a,b,,,tx,ty]=glyph.transform;
   assert.ok(Math.abs(Math.atan2(b,a)*180/Math.PI-angle)<.1);
   assert.ok(Math.hypot(tx-x,ty-y)<18,word+' displaced to '+[tx,ty]);
 }
 assert.doesNotMatch(items.map(i=>i.str).join(''),/clockwise|remains original/i);
});
