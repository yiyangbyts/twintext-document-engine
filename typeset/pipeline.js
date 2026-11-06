// Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
(function(global){
'use strict';
const ENV=global.TwinTextTypesetEnvironment,IOUtils=ENV.io,PathUtils=ENV.path;
const REVISION='typeset-public-2.2.17-1';
const hexDigest=async bytes=>Array.from(new Uint8Array(await global.crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');
const atomicWrite=(file,bytes)=>IOUtils.write(file,bytes,{tmpPath:file+'.tmp'});
const regionsKey=()=>JSON.stringify([REVISION,ENV.resourceURI,ENV.version]);
async function readRegions(file){try{const d=await IOUtils.readJSON(file);if(d.key===regionsKey())return new Map(Object.entries(d.pages).filter(([,v])=>Array.isArray(v)).map(([n,v])=>[Number(n),v]));}catch(_){}return new Map();}
const writeRegions=(file,regions)=>IOUtils.writeJSON(file,{key:regionsKey(),pages:Object.fromEntries(regions)},{tmpPath:file+'.tmp'});
class DocumentTask {
 constructor({input,output,readerWindow,pageCount,options={},translate,signal,onEvent=()=>{}}){
  Object.assign(this,{input,output,readerWindow,pageCount,settings:options,translate,signal,active:true,first:options.first||0,last:options.last,requestConcurrency:options.translationConcurrency||3,errors:new Map()});
  this.emit=event=>{if(event.type==='preview')return onEvent(event);try{Promise.resolve(onEvent(event)).catch(error=>{this.eventError=error;this.stop();});}catch(error){this.eventError=error;this.stop();}};
  this.whenCancelled=new Promise(resolve=>{this.stop=()=>{this.active=false;resolve();};signal?.addEventListener('abort',this.stop,{once:true});});
 }
 check(){if(this.eventError)throw this.eventError;if(!this.active||this.signal?.aborted)throw Object.assign(Error('Cancelled'),{name:'AbortError'});}
 label(text){this.emit({type:'status',text,stage:this.stage});}
 report(fraction,title,detail,note=''){this.progressPercent=Math.max(this.progressPercent||0,Math.min(99,Math.round(fraction*100)));this.emit({type:'progress',percent:this.progressPercent,title,detail,note,stage:this.stage,translatedFragments:this.translatedFragments||0});}
 async run(){
  this.check();
  if(this.input===this.output)throw Error('Input and output must be different paths');
  const core=global;
  const E=core.TwinTextTypesetEngine,bytes=await IOUtils.read(this.input),folder=PathUtils.parent(this.output),outputFile=this.output;
  await IOUtils.makeDirectory(folder,{createAncestors:true,ignoreExisting:true});
  const source=await hexDigest(bytes),digest=PathUtils.filename(this.output).replace(/\.pdf$/,'');
  const win=this.readerWindow;if(!win||!Number.isInteger(this.pageCount)||this.pageCount<1)throw Error('PDF reader is not ready');
  this.last=this.last==null?this.pageCount-1:Math.min(this.last,this.pageCount-1);
  if(this.first<0||this.first>this.last){await core.TwinTextTypesetChars.close(win);throw Error('Invalid page range');}
      const pageIndexes=[];for(let i=this.first;i<=this.last;i++)pageIndexes.push(i);
      const count=pageIndexes.length;
      this.stage='typeset-layout';this.label(`正在分析版面 0/${count}`);this.report(0,'正在解析版面',`正在读取页面文字与字形，共${count}页；`,'读取完成后识别版面。');
      const regionsPath=PathUtils.join(folder,source+'.regions.json'),stored=await readRegions(regionsPath),fresh=new Map();
      const known=new Map(pageIndexes.filter(index=>stored.has(index)).map(index=>[index,stored.get(index)]));
      let pool=null,timer=null,translation=null,writing=null,completed=false,stopped=false;
      const io=core.TwinTextTypesetIO.create(),feed=core.TwinTextTypesetTranslator.feed();
      try{
        // The layout model loads while the pages' text is read (the pool says in what order it takes the pages).
        if(known.size<count){pool=core.TwinTextTypesetLayoutPool.create();pool.load().catch(()=>{});}
        const F=core.TwinTextTypesetFonts,W=core.TwinTextTypesetWriter,Y=core.TwinTextTypesetLayout;
        const objects=await core.TwinTextTypesetPdfObjects.createPdfObjects(bytes,async b=>core.TwinTextTypesetPdfObjects.inflateSync(b),core.TwinTextTypesetFontData).open().catch(()=>{throw new Error('这篇 PDF 的加密方式暂不支持全文精排，请使用解除密码保护后的 PDF。');});
        this.check();
        const book=F.createBook(io.read,{primary:this.settings.fontFamily==='sans'?'sans':'serif'});
        const fontInfo={},pages=[];
        const writer=W.createWriter({objects,bytes,deflate:io.deflate,book,fontInfo});
        let read=0,recognized=0,analyzed=0,listed=0,done=0,layoutStarted=0,lastBuild=0,buildCost=0;
        // The layout model answers late, so until it does the layout's share moves on an estimate of 2.2 s a page; each answer puts it right.
        const share=()=>{
          if(read<count)return .03*read/count;
          const all=analyzed===count,expected=all?listed:analyzed?listed/analyzed*count:0;
          const layout=Math.max(recognized/count,(known.size+Math.min(.95*(count-known.size),(Date.now()-layoutStarted)/2200))/count);
          return .03+.42*layout+.52*(expected?Math.min(all?1:.95,done/expected):0);
        };
        const progress=()=>{
          const shown=this.previewUpdates?'现为预览版面，全部译完后统一排版。':'当前页译完即显示。';
          if(read<count)this.report(share(),'正在解析版面',`正在读取页面文字与字形，已读取${read}/${count}页；`,'读取完成后识别版面。');
          else if(!analyzed)this.report(share(),'正在解析版面',`正在识别段落、标题、公式、图表与表格区域，已识别${recognized}/${count}页；`,'第一页识别完即开始翻译。');
          else if(analyzed<count)this.report(share(),'正在翻译',`正在翻译已识别的页面，已译${done}段，已识别${recognized}/${count}页；`,shown);
          else this.report(share(),'正在翻译',`正在翻译正文，已译${done}/${listed}段；`,shown);
        };
        const tick=()=>{timer=setTimeout(()=>{if(this.active&&this.stage!=='typeset-final'){progress();tick();}},700);};
        const preview=()=>{
          if(writing||this.settings.backgroundExport)return;
          const now=Date.now();
          if(lastBuild&&now-lastBuild<Math.max(8000,buildCost*6))return;
          const ready=pages.filter(page=>!page.unsupported&&page.paragraphs.every(p=>p.finished));
          if(!ready.length)return;
          lastBuild=now;
          writing=(async()=>{
            const started=Date.now();
            Y.typesetPages(ready,{book,fontsById:fontInfo,document:false});
            const pdf=await writer.build(ready);
            const previewPath=PathUtils.join(folder,digest+'.preview.pdf');
            await atomicWrite(previewPath,pdf,{tmpPath:previewPath+'.tmp'});
            this.check();
            await this.emit({type:'preview',file:previewPath,sha256:await hexDigest(pdf)});
            this.previewUpdates=(this.previewUpdates||0)+1;
            this.label(`预览：已译 ${done} 段，全部译完后切换为最终版面`);
            buildCost=Date.now()-started;lastBuild=Date.now();
          })().catch(error=>{if(error?.name==='AbortError')throw error;this.previewFailure=String(error?.message||error);this.emit({type:'warning',message:String(error.message||error)});}).finally(()=>{writing=null;});
          writing.catch(()=>{});
        };
        const ask=text=>this.translate(text,{signal:this.signal,sourceLanguage:this.settings.sourceLanguage,targetLanguage:this.settings.targetLanguage});
        // The fonts load while the first page is recognized; the paragraphs fed in before then wait for them.
        translation=(async()=>{
          await book.ready;this.check();
          return E.translateDocument(feed,ask,{
            concurrency:Math.max(1,Math.min(this.requestConcurrency||4,Number(this.settings.translationConcurrency)||3)),cancelled:()=>!this.active||stopped,
            onParagraph:p=>{p.finished=true;done++;this.translatedFragments=done;if(done%8===0)this.label(analyzed<count?`正在翻译 ${done} 段`:`正在翻译 ${done}/${listed} 段`);progress();preview();}
          });
        })();
        // Settled below: a failure before then is not an unhandled one.
        translation.catch(()=>{});
        tick();
        // A stop closes the pool at once: the pages being recognized are dropped, not waited for (eight at a time, 15 s each on an M2).
        this.whenCancelled?.then(()=>{pool?.close();io.close();});
        try{
          await E.analyzeDocument(win,pageIndexes,{pool,known,background:Boolean(this.settings.backgroundExport),cancelled:()=>!this.active,
            onCapture:()=>{read++;if(read===count)layoutStarted=Date.now();progress();},
            onLayout:page=>{recognized++;if(!page.known)fresh.set(page.pageIndex,page.boxes);progress();},
            onPage:work=>{
              analyzed++;pages.push(work);listed+=work.paragraphs.length;
              for(const f of work.fontInfo||[])fontInfo[f.id]=f;
              this.stage='typeset-translate';this.label(`正在分析版面 ${analyzed}/${count}`);
              feed.push(work.paragraphs);progress();
            }});
        }catch(error){
          // The closed pool's error, after a stop, is the stop.
          this.check();
          throw error;
        }finally{
          feed.close();
          // What was recognized is kept, even when this start goes no further.
          if(fresh.size)await writeRegions(regionsPath,new Map([...stored,...fresh])).catch(error=>this.emit({type:'warning',message:String(error.message||error)}));
        }
        this.check();
        pool?.close();pool=null;
        const stats=await translation;
        this.check();
        this.typesetStats=stats;
        await writing;
        this.stage='typeset-final';this.label('正在生成最终版面');this.report(.97,'正在生成最终版面','正在统一全文字号与行距，生成译文 PDF；','完成后自动切换为最终版面。');
        Y.typesetPages(pages,{book,fontsById:fontInfo,document:true});
        this.documentScale=pages[0]?.documentScale;
        const pdf=await writer.build(pages.filter(page=>!page.unsupported));this.check();
        this.unsupportedPages=pages.filter(page=>page.unsupported).map(page=>page.pageIndex);
        // A result with failed paragraphs is shown but not kept as the final one: the next start asks again for those alone, the rest being in the chunk store.
        for(const page of pages)if(page.paragraphs.some(p=>p.failed))this.errors.set(page.pageIndex,Object.assign(new Error('此页有段落翻译失败，已保留原文，重新开始翻译可补译。'),{code:'document_page_failed'}));
        const output=this.errors.size?PathUtils.join(folder,digest+'.partial.pdf'):outputFile;
        await atomicWrite(output,pdf,{tmpPath:output+'.tmp'});
        this.nativePDFPath=output;this.nativePDFChecksum=await hexDigest(pdf);
        completed=true;
      }finally{
        clearTimeout(timer);
        // A start that fails or is stopped asks for nothing more, and the requests still running end before the store closes under them.
        if(!completed)stopped=true;
        feed.close();pool?.close();
        if(translation)try{await translation;}catch(_){}
        if(writing)try{await writing;}catch(_){}
        io.close();
        await Promise.resolve().then(()=>core.TwinTextTypesetChars.close(win)).catch(()=>{});
      }
  this.signal?.removeEventListener('abort',this.stop);
  return {file:this.nativePDFPath,sha256:this.nativePDFChecksum,stats:this.typesetStats,unsupportedPages:this.unsupportedPages||[],failedPages:[...this.errors.keys()],translatedFragments:this.translatedFragments||0,previewUpdates:this.previewUpdates||0,documentScale:this.documentScale,pageCount:this.pageCount};
 }
}
async function run(request){const task=new DocumentTask(request);try{return await task.run();}finally{request.signal?.removeEventListener('abort',task.stop);}}
async function normalize(bytes,check=()=>{}){check();const result=await global.TwinTextPDFNormalize.decryptedPDF(bytes);check();return result;}
global.TwinTextTypesetModule=Object.freeze({REVISION,run,normalize});
})(this);
