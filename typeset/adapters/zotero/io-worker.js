// Typeset engine: font files and compression off the main thread.
// SPDX-License-Identifier: AGPL-3.0-only
self.onmessage=async({data})=>{
  try{
    if(data.kind==='read'){
      const reply=await fetch(data.url),bytes=new Uint8Array(await reply.arrayBuffer());
      self.postMessage({id:data.id,bytes},[bytes.buffer]);
    }else if(data.kind==='deflate'){
      const reader=new Blob([data.bytes]).stream().pipeThrough(new CompressionStream('deflate')).getReader(),parts=[];let size=0;
      for(;;){const {done,value}=await reader.read();if(done)break;parts.push(value);size+=value.length;}
      const out=new Uint8Array(size);let at=0;for(const part of parts){out.set(part,at);at+=part.length;}
      self.postMessage({id:data.id,bytes:out},[out.buffer]);
    }
  }catch(error){self.postMessage({id:data.id,error:String(error?.message||error)});}
};
