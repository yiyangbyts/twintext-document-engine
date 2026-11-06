// Typeset engine: one page at a time on one worker. Several workers make the pages run side by side.
// SPDX-License-Identifier: AGPL-3.0-only
importScripts('../../vendor/ort/ort.wasm.min.js','../../core/layout-model.js');
const isolated=Boolean(self.crossOriginIsolated&&typeof SharedArrayBuffer==='function');
ort.env.wasm.wasmPaths=new URL('../../vendor/ort/',self.location.href).href;
ort.env.logLevel='warning';
let session=null;
self.onmessage=async({data})=>{
  const started=performance.now();
  try{
    if(data.kind==='load'){
      ort.env.wasm.numThreads=isolated?Math.max(1,Number(data.threads)||1):1;
      const reply=await fetch(data.url),model=new Uint8Array(await reply.arrayBuffer());
      session=await ort.InferenceSession.create(model,{executionProviders:['wasm'],graphOptimizationLevel:'all'});
      self.postMessage({id:data.id,ready:true,isolated,threads:ort.env.wasm.numThreads,ms:performance.now()-started});
      return;
    }
    if(data.kind!=='predict'||!session)throw new Error('Layout model is not loaded');
    const model=TwinTextTypesetLayoutModel,side=model.SIDE,binary=atob(data.rgb),rgb=new Uint8Array(binary.length);
    for(let i=0;i<binary.length;i++)rgb[i]=binary.charCodeAt(i);
    const input=new ort.Tensor('float32',model.tensor(rgb,data.layout),[1,3,side,side]);
    const output=await session.run({images:input}),rows=output[session.outputNames[0]].data;
    self.postMessage({id:data.id,boxes:model.decode(rows,data.layout),ms:performance.now()-started});
  }catch(error){self.postMessage({id:data.id,error:{message:error?.message||String(error)}});}
};
