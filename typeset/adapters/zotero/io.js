// Font loading and compression use Zotero/Gecko workers; no external executable.
// Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
(function(global){
 'use strict';
 function create(){
  const root=global.TwinTextTypesetEnvironment.resourceURI,worker=new global.ChromeWorker(root+'adapters/zotero/io-worker.js'),pending=new Map();let sequence=0,closed=false,failure=null;
  const fail=error=>{failure=error;for(const job of pending.values()){global.clearTimeout(job.timer);job.reject(error);}pending.clear();};
  worker.onmessage=({data})=>{const job=pending.get(data.id);if(!job)return;pending.delete(data.id);global.clearTimeout(job.timer);data.error?job.reject(Error(data.error)):job.resolve(data.bytes);};
  worker.onerror=event=>{event.preventDefault?.();fail(Error(event.message||'I/O worker failed'));try{worker.terminate();}catch(_){};};
  const call=message=>closed||failure?Promise.reject(failure||Object.assign(Error('Cancelled'),{name:'AbortError'})):new Promise((resolve,reject)=>{
   const id=++sequence,timer=global.setTimeout(()=>{fail(Error('I/O worker timed out'));worker.terminate();},180000);pending.set(id,{resolve,reject,timer});
   try{worker.postMessage({id,...message});}catch(error){fail(error);worker.terminate();}
  });
  return {read:name=>call({kind:'read',url:root+'assets/fonts/'+name}),deflate:bytes=>call({kind:'deflate',bytes}),close(){if(closed)return;closed=true;fail(Object.assign(Error('Cancelled'),{name:'AbortError'}));worker.terminate();}};
 }
 global.TwinTextTypesetIO=Object.freeze({create});
})(this);
