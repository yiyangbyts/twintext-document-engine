const test=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),vm=require('vm');
const root=path.resolve(__dirname,'..');
const load=(file,context={})=>{context.globalThis=context;context.TwinTextTypesetEnvironment||={resourceURI:'test://engine/',machine:()=>({cores:context.Zotero?.getMainWindow().navigator.hardwareConcurrency||1,memoryBytes:context.Services?.sysinfo.getProperty('memsize')||0}),boundedRequest:work=>work(),logError(){}};vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'),context);return context;};
const model=load('core/layout-model.js').TwinTextTypesetLayoutModel;
test('a letter page is drawn at 72 dpi, fitted to the model side and centred',()=>{
  const p=model.plan(612,792);
  assert.equal(p.dpi,72);assert.deepEqual([p.pixelWidth,p.pixelHeight],[612,792]);
  assert.deepEqual([p.width,p.height],[791,1024]);assert.deepEqual([p.left,p.top],[116,0]);
});
test('a huge page draws at a lower dpi',()=>{
  const p=model.plan(4000,3000);
  assert.equal(p.dpi,Math.floor(1024*72/4000));assert.equal(p.width,1024);assert.equal(p.top,Math.floor((1024-p.height)/2));
});
test('rounding follows Python',()=>{assert.equal(model.round(2.5),2);assert.equal(model.round(3.5),4);assert.equal(model.round(2.51),3);});
test('the tensor is blue, green, red on grey padding',()=>{
  const layout={width:1,height:1,left:2,top:3},out=model.tensor(Uint8Array.of(255,0,51),layout),at=3*1024+2,n=1024*1024;
  assert.ok(Math.abs(out[at]-.2)<1e-6);assert.equal(out[n+at],0);assert.equal(out[2*n+at],1);
  assert.ok(Math.abs(out[0]-114/255)<1e-6);
  assert.throws(()=>model.tensor(new Uint8Array(2),layout),/raster length/);
});
test('boxes come back in page points and weak ones drop',()=>{
  const p=model.plan(612,792),g=1024/792,boxes=model.decode([116,0,116+612*g,1024,.9,1, 0,0,1,1,.25,0],p);
  assert.equal(boxes.length,1);assert.equal(boxes[0].name,'plain text');
  assert.ok(Math.abs(boxes[0].x0)<1e-3);assert.ok(Math.abs(boxes[0].x1-612)<1);assert.ok(Math.abs(boxes[0].y1-792)<1e-3);
});
test('the pool takes the cap, the cores and the memory, whichever is least',()=>{
  const pool=load('adapters/zotero/layout-pool.js',{TwinTextTypesetLayoutModel:model}).TwinTextTypesetLayoutPool,GB=1024**3;
  assert.equal(pool.workerCount(8,16*GB),8);assert.equal(pool.workerCount(64,128*GB),20);
  assert.equal(pool.workerCount(16,8*GB),8);assert.equal(pool.workerCount(4,1*GB),1);assert.equal(pool.workerCount(0,0),1);
});
// Workers that answer at once: a load with the threads they can run (no more than most), a page with its layout given back as its boxes.
const fakeMachine=({cores=8,memory=16*1024**3,most=Infinity}={})=>{
  const started=[];
  class Worker{
    constructor(){started.push(this);}
    postMessage(message){Promise.resolve().then(()=>{
      if(this.gone)return;
      if(message.kind==='load'){this.threads=Math.min(message.threads,most);this.onmessage({data:{id:message.id,ready:true,threads:this.threads}});}
      else{(this.pages||=[]).push(message.layout);this.onmessage({data:{id:message.id,boxes:[message.layout],ms:1}});}
    });}
    terminate(){this.gone=true;}
  }
  const context={TwinTextTypesetLayoutModel:model,ChromeWorker:Worker,setTimeout,clearTimeout,Services:{sysinfo:{getProperty:()=>memory}},Zotero:{getMainWindow:()=>({navigator:{hardwareConcurrency:cores}})}};
  return {started,pool:load('adapters/zotero/layout-pool.js',context).TwinTextTypesetLayoutPool};
};
const settle=()=>new Promise(resolve=>setTimeout(resolve,0));
test('the first page goes alone to a worker of four threads, then one-thread workers take over, one a core',async()=>{
  const {started,pool:P}=fakeMachine(),pool=P.create();
  assert.equal(pool.size,8);
  await pool.load();
  assert.deepEqual(started.map(w=>w.threads),[4]);
  assert.deepEqual((await pool.predict({rgb:'',layout:0})).boxes,[0]);
  await settle();
  assert.equal(started[0].gone,true);
  assert.deepEqual(started.slice(1).map(w=>w.threads),[1,1,1,1,1,1,1,1]);
  const answers=await Promise.all([1,2,3,4,5,6,7,8,9].map(layout=>pool.predict({rgb:'',layout})));
  assert.deepEqual(answers.map(a=>a.boxes[0]),[1,2,3,4,5,6,7,8,9]);
  assert.deepEqual(started[0].pages,[0]);
  pool.close();
  assert.ok(started.every(w=>w.gone));
});
test('a lead that can run one thread only stays, and memory for one worker keeps the lead alone',async()=>{
  const one=fakeMachine({most:1}),pool=one.pool.create();
  await pool.predict({rgb:'',layout:0});await settle();
  assert.equal(one.started.length,8);assert.ok(!one.started[0].gone);assert.ok(one.started.every(w=>w.threads===1));
  pool.close();
  const small=fakeMachine({memory:1024**3}),alone=small.pool.create();
  assert.equal(alone.size,1);
  await alone.predict({rgb:'',layout:0});await alone.predict({rgb:'',layout:1});
  assert.equal(small.started.length,1);assert.deepEqual(small.started[0].pages,[0,1]);assert.equal(small.started[0].threads,4);
  alone.close();
});
test('a count starts that many workers of that many threads at once',async()=>{
  const {started,pool:P}=fakeMachine(),pool=P.create(2,4);
  await pool.load();
  assert.deepEqual(started.map(w=>w.threads),[4,4]);
  await pool.predict({rgb:'',layout:0});await settle();
  assert.equal(started.length,2);assert.ok(!started[0].gone);
  pool.close();
});
test('pages whose regions an earlier run kept are given back at once and not drawn or recognized again',async()=>{
  const context={TwinTextTypesetLayoutModel:model,TwinTextServices:{boundedRequest:work=>work()}};
  const P=load('adapters/zotero/layout-pool.js',context).TwinTextTypesetLayoutPool,drawn=[],asked=[],order=[];
  const win={eval:script=>{const page=Number(/getPage\((\d+)\)/.exec(script)[1])-1;drawn.push(page);return Promise.resolve({rgb:'',layout:page});}};
  const pool={size:2,predict:async input=>{asked.push(input.layout);return {boxes:['new '+input.layout],ms:1};}};
  const results=await P.analyzePages(win,[0,1,2,3],{pool,known:new Map([[0,['kept 0']],[2,['kept 2']]]),onPage:page=>order.push(`${page.pageIndex} ${page.boxes[0]}`)});
  assert.deepEqual(drawn.sort(),[1,3]);assert.deepEqual(asked.sort(),[1,3]);
  assert.deepEqual(order.slice(0,2),['0 kept 0','2 kept 2']);
  assert.equal(results.get(3).boxes[0],'new 3');assert.equal(results.size,4);
});
test('a page is built as soon as its regions and those of every page before it are in, whatever order the model answers in',async()=>{
  const events=[];
  const context={
    TwinTextTypesetChars:{capture:async()=>({mediaBox:[0,0,612,792],source:'content',fonts:{},curves:[],links:[]}),toCharacters:()=>[],readingTurns:()=>[0],close:async()=>{}},
    TwinTextTypesetStructure:{pageLayoutFromModel:boxes=>boxes,analyzePage:work=>{work.paragraphs=[];}},
    TwinTextTypesetLayoutPool:{create:()=>({close(){}}),analyzePages:async(win,pages,{onPage})=>{for(const pageIndex of [2,0,3,1])onPage({pageIndex,boxes:[]});}}
  };
  const E=load('core/engine.js',context).TwinTextTypesetEngine;
  const pages=await E.analyzeDocument({},[0,1,2,3],{onLayout:page=>events.push('regions '+page.pageIndex),onPage:work=>events.push('page '+work.pageIndex)});
  assert.deepEqual(events,['regions 2','regions 0','page 0','regions 3','regions 1','page 1','page 2','page 3']);
  assert.deepEqual([...pages.map(page=>page.pageIndex)],[0,1,2,3]);
});
test('stopped, failed or done, the reader lets go of its copy of the document once',async()=>{
  const closes=[];
  const engine=analyzePages=>load('core/engine.js',{
    TwinTextTypesetChars:{capture:async()=>({mediaBox:[0,0,612,792],source:'content',fonts:{},curves:[],links:[]}),toCharacters:()=>[],readingTurns:()=>[0],close:async()=>{closes.push(1);}},
    TwinTextTypesetStructure:{pageLayoutFromModel:boxes=>boxes,analyzePage:work=>{work.paragraphs=[];}},
    TwinTextTypesetLayoutPool:{create:()=>({close(){}}),analyzePages}
  }).TwinTextTypesetEngine;
  await assert.rejects(engine(async()=>{throw new Error('layout pool is closed');}).analyzeDocument({},[0,1]),/pool is closed/);
  assert.equal(closes.length,1);
  let stopped=false;
  assert.equal(await engine(async(win,pages,{onPage})=>{onPage({pageIndex:0,boxes:[]});stopped=true;}).analyzeDocument({},[0,1],{cancelled:()=>stopped}),null);
  assert.equal(closes.length,2);
  assert.equal((await engine(async(win,pages,{onPage})=>{for(const pageIndex of pages)onPage({pageIndex,boxes:[]});}).analyzeDocument({},[0,1])).length,2);
  assert.equal(closes.length,3);
});
test('the reader script carries its own copy of the page plan',()=>{
  const context={TwinTextTypesetLayoutModel:model};
  context.TwinTextServices={boundedRequest:work=>work()};
  const pool=load('adapters/zotero/layout-pool.js',context).TwinTextTypesetLayoutPool;let script='';
  pool.raster({eval:text=>{script=text;return null;}},0);
  const source=/const layout=\((.*?)\)\(width,height\);/su.exec(script)[1];
  const plan=vm.runInNewContext(source);
  assert.deepEqual(JSON.parse(JSON.stringify(plan(612,792))),JSON.parse(JSON.stringify(model.plan(612,792))));
});
