// Typeset engine: page rasters from the reader and a pool of layout workers.
// SPDX-License-Identifier: AGPL-3.0-only
(function(global){
  'use strict';
  const ENV=global.TwinTextTypesetEnvironment;
  const WORKER=ENV.resourceURI+'adapters/zotero/layout-worker.js';
  const MODEL=ENV.resourceURI+'assets/models/doclayout_yolo_docstructbench_imgsz1024_u8.onnx';
  const CAP=20,WORKER_BYTES=500*1024*1024,MEMORY_SHARE=.5,JOB_TIMEOUT=180000,RASTER_TIMEOUT=60000,THREADS=4;
  // As many as asked, as long as each has a core and all of them fit in half the memory: past that, more only run slower.
  function workerCount(cores,memoryBytes,cap=CAP){
    const fit=Math.floor((Number(memoryBytes)||0)*MEMORY_SHARE/WORKER_BYTES);
    return Math.max(1,Math.min(cap,Number(cores)||1,fit));
  }
  const machine=()=>ENV.machine();
  // With no count given, one worker of four threads takes the first page alone; once it has answered, workers of one thread take over, one a core as memory allows.
  // On an M2 (4 + 4 cores) the first page comes in 3 s, where eight workers started at once and contending give it in 16-22 s, and the whole document as soon as
  // before (PLOS 14 pages 34 s, JHEP 28 pages 52 s). Workers of four threads all along are slower over many pages, since a run waits for its slowest thread and half
  // the cores are efficiency cores (two of them: JHEP 61 s). The boxes are the same whatever the threads. A count: that many workers of that many threads from the start.
  function create(count=null,threads=1){
    const {cores,memoryBytes}=machine(),planned=count==null,size=count||workerCount(cores,memoryBytes),slots=[],waiting=[];
    let sequence=0,closed=false,loading=null,grown=!planned;
    const startSlot=()=>{
      const slot={worker:new global.ChromeWorker(WORKER),job:null,threads:1};
      slot.fail=error=>{
        const job=slot.job;slot.job=null;
        if(job){global.clearTimeout(job.timer);job.reject(error);}
        try{slot.worker.terminate();}catch(_){}
        const at=slots.indexOf(slot);if(at>=0)slots.splice(at,1);
        if(!closed&&!slots.length)for(const next of waiting.splice(0))next.reject(error);
      };
      slot.worker.onmessage=({data})=>{
        const job=slot.job;if(!job||job.id!==data?.id)return;
        slot.job=null;global.clearTimeout(job.timer);
        data.error?job.reject(new Error(data.error.message)):job.resolve(data);
        pump();
      };
      slot.worker.onerror=event=>{event.preventDefault?.();slot.fail(new Error(event.message||'layout worker failed'));};
      slots.push(slot);
      return slot;
    };
    const send=(slot,job)=>{
      slot.job=job;job.id=++sequence;
      job.timer=global.setTimeout(()=>slot.fail(new Error('layout worker timed out')),JOB_TIMEOUT);
      try{slot.worker.postMessage({id:job.id,...job.message});}catch(error){slot.fail(error);}
    };
    function pump(){
      for(const slot of slots){
        if(!waiting.length)return;
        if(!slot.job)send(slot,waiting.shift());
      }
    }
    const loadSlot=threads=>{
      const slot=startSlot();
      return new Promise((resolve,reject)=>send(slot,{message:{kind:'load',url:MODEL,threads},resolve:data=>{slot.threads=Number(data.threads)||1;resolve(data);},reject}));
    };
    // Called as the first page's answer comes in, before the lead is given another page. Its threads would contend with the others', so it goes; a lead that could
    // run only one thread (no shared memory), or that memory leaves alone, stays.
    const grow=()=>{
      if(grown||closed)return;
      grown=true;
      const lead=slots[0];
      if(lead&&lead.threads>1&&!lead.job&&size>1){try{lead.worker.terminate();}catch(_){}slots.splice(0,1);}
      // One that cannot start leaves the pages to the others.
      for(let i=slots.length;i<size;i++)loadSlot(1).catch(error=>{if(!closed)ENV.logError?.(error);});
    };
    const load=()=>loading||(loading=planned?loadSlot(Math.max(1,Math.min(THREADS,cores||1))):Promise.all(Array.from({length:size},()=>loadSlot(threads))));
    return {size,load,
      async predict(input){
        await load();
        if(closed)throw new Error('layout pool is closed');
        if(!slots.length)throw new Error('layout workers are gone');
        return new Promise((resolve,reject)=>{waiting.push({message:{kind:'predict',rgb:input.rgb,layout:input.layout},resolve:data=>{grow();resolve(data);},reject});pump();});
      },
      close(){
        closed=true;
        const error=new Error('layout pool is closed');
        for(const next of waiting.splice(0))next.reject(error);
        for(const slot of slots.splice(0)){
          if(slot.job){global.clearTimeout(slot.job.timer);slot.job.reject(error);slot.job=null;}
          try{slot.worker.terminate();}catch(_){}
        }
      }};
  }
  // Runs in the reader's window. Rotation is taken off the page, as BabelDOC does before drawing it.
  function raster(win,pageIndex,mediaBox=null,background=false,turn=0){
    return ENV.boundedRequest(()=>win.eval(`(async()=>{
      const page=await PDFViewerApplication.pdfDocument.getPage(${Number(pageIndex)+1}),frame=${JSON.stringify(mediaBox)}||page.view;
      const turn=${Number(turn)},width=turn?frame[3]:frame[2],height=turn?frame[2]:frame[3];
      const layout=(${planSource()})(width,height);
      const scale=layout.dpi/72,view=page.getViewport({scale,rotation:0});
      const dx=page.view[0]*scale,dy=(frame[3]-page.view[3])*scale;
      let transform=[1,0,0,1,dx,dy];
      if(turn===90)transform=[0,1,-1,0,frame[3]*scale-dy,dx];
      if(turn===-90)transform=[0,-1,1,0,dy,frame[2]*scale-dx];
      const source=document.createElement('canvas');source.width=layout.pixelWidth;source.height=layout.pixelHeight;
      // Display rendering waits for animation frames. Zotero may suspend those
      // in the private background tab; PDF.js print rendering schedules its own work.
      await page.render({intent:${background?"'print'":"'display'"},canvasContext:source.getContext('2d',{alpha:false}),viewport:view,background:'#fff',transform}).promise;
      const target=document.createElement('canvas');target.width=layout.width;target.height=layout.height;
      const context=target.getContext('2d',{alpha:false,willReadFrequently:true});context.imageSmoothingEnabled=true;context.imageSmoothingQuality='low';
      context.drawImage(source,0,0,layout.width,layout.height);
      const rgba=context.getImageData(0,0,layout.width,layout.height).data,rgb=new Uint8Array(layout.width*layout.height*3);
      for(let i=0,j=0;i<rgba.length;i+=4){rgb[j++]=rgba[i];rgb[j++]=rgba[i+1];rgb[j++]=rgba[i+2];}
      let text='';for(let i=0;i<rgb.length;i+=32768)text+=String.fromCharCode(...rgb.subarray(i,i+32768));
      source.width=0;target.width=0;
      return {rgb:btoa(text),layout};
    })()`),{timeout:RASTER_TIMEOUT,timeoutError:()=>Object.assign(new Error(`第 ${pageIndex+1} 页版面图像绘制超时，请重新翻译以接续缓存。`),{code:'page_raster_timeout'})});
  }
  const planSource=()=>`(${global.TwinTextTypesetLayoutModel.plan.toString().replace(/\bround\(/g,'pyRound(')})`.replace(/^\(function plan/,`((pyRound,SIDE,DEFAULT_DPI)=>function plan`).replace(/\)$/,`)(${global.TwinTextTypesetLayoutModel.round.toString()},${global.TwinTextTypesetLayoutModel.SIDE},72)`);
  // Every page's regions. The reader draws one page at a time; each worker that comes free takes the next.
  // known: regions kept from an earlier run (pageIndex -> boxes), given back at once in page order instead of drawn and recognized.
  async function analyzePages(win,pages,{pool,onPage,cancelled,mediaBoxOf,turnsOf,known,background=false}={}){
    const results=new Map(),queue=[];let drawing=Promise.resolve();
    for(const pageIndex of pages){
      const boxes=known?.get(pageIndex);
      if(!boxes){queue.push(pageIndex);continue;}
      const page={pageIndex,boxes,known:true};
      results.set(pageIndex,page);onPage?.(page);
    }
    const run=async()=>{
      while(queue.length&&!cancelled?.()){
        const pageIndex=queue.shift();
        const boxes=[];
        let rasterMs=0,computeMs=0;
        for(const turn of turnsOf?.(pageIndex)||[0]){
          if(cancelled?.())return;
          const job=drawing.then(async()=>raster(win,pageIndex,await mediaBoxOf?.(pageIndex),background,turn));
          drawing=job.catch(()=>{});
          const started=Date.now(),input=await job;
          rasterMs+=Date.now()-started;
          const result=await pool.predict(input);
          computeMs+=result.ms;
          for(const region of result.boxes)boxes.push(turn?{...region,turn}:region);
        }
        const page={pageIndex,boxes,rasterMs,computeMs};
        results.set(pageIndex,page);onPage?.(page);
      }
    };
    await Promise.all(Array.from({length:pool.size},run));
    return results;
  }
  global.TwinTextTypesetLayoutPool=Object.freeze({CAP,MODEL,workerCount,machine,create,raster,analyzePages});
})(this);
