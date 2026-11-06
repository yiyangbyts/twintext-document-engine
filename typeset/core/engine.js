// Typeset engine: the stages in order, for a whole document before anything is laid out.
// SPDX-License-Identifier: AGPL-3.0-only
(function(global){
  'use strict';
  // Run the existing paragraph and table algorithms in each text direction's own
  // reading frame. A horizontal header and a sideways table can share one page.
  function analyzeFrames(work,turns,boxes){
    const S=global.TwinTextTypesetStructure,G=global.TwinTextTypesetLayoutModel;
    const [,,width,height]=work.media;
    if(turns.length===1&&!turns[0]){
      work.layouts=S.pageLayoutFromModel(boxes,width,height);
      S.analyzePage(work);
      return work;
    }
    const layers=turns.map(turn=>{
      const regions=boxes.filter(b=>(b.turn||0)===turn);
      if(!turn){
        const layer={...work,chars:work.chars.filter(c=>!c.turn),layouts:S.pageLayoutFromModel(regions,width,height)};
        S.analyzePage(layer);
        return layer;
      }
      const {toLocal,toPage}=G.readingFrame(turn,width,height);
      const local=b=>G.transformBox(b,toLocal);
      const curves=work.curves.map(c=>{
        const [a,b,d,e,x,y]=c.ctm,[u,v,k,l,dx,dy]=toLocal;
        return {...c,box:local(c.box),ctm:[u*a+k*b,v*a+l*b,u*d+k*e,v*d+l*e,u*x+k*y+dx,v*x+l*y+dy]};
      });
      const layer={...work,turn,toPage,media:[0,0,height,width],curves,
        layouts:S.pageLayoutFromModel(regions,height,width),
        chars:work.chars.filter(c=>c.turn===turn).map(c=>({...c,box:local(c.box),visual:local(c.visual)}))};
      S.analyzePage(layer);
      return layer;
    });
    return {...work,chars:[],layers,paragraphs:layers.flatMap(l=>l.paragraphs),removedCurves:layers.flatMap(l=>l.removedCurves||[])};
  }
  // Pages are read in page order: BabelDOC's rules depend on it. Regions come from the pool, paragraphs from the structure stage. A page is built as soon as its
  // regions and those of every page before it are in, so its translation can start while later pages are still being recognized.
  // known: regions kept from an earlier run of the same file (pageIndex -> boxes); those pages are not drawn or recognized again.
  async function analyzeDocument(win,pageIndexes,{pool,onPage,onCapture,onLayout,cancelled,known,background=false}={}){
    const C=global.TwinTextTypesetChars,L=global.TwinTextTypesetLayoutPool,captured=new Map();
    let closed=false;
    try{
      for(const index of pageIndexes){
        if(cancelled?.())return null;
        const page=await C.capture(win,index);
        page.turns=C.readingTurns(page);
        captured.set(index,page);onCapture?.(index);
      }
      const ownPool=!pool;
      pool=pool||L.create();
      const pages=[],regions=new Map();let next=0,failed=false;
      const build=()=>{
        // After a page fails, the workers still answering build no page after it.
        if(failed)return;
        try{
          while(next<pageIndexes.length&&regions.has(pageIndexes[next])&&!cancelled?.()){
            const index=pageIndexes[next++];
            const page=captured.get(index),media=page.mediaBox||page.view;
            let work={pageIndex:index,media,source:page.source,fontInfo:Object.values(page.fonts),fonts:Object.fromEntries(Object.values(page.fonts).map(f=>[f.id,f.name])),chars:C.toCharacters(page).filter(c=>!c.hidden),curves:page.curves||[]};
            // A page the content stream could not be read for stays as printed.
            if(page.source==='content')work=analyzeFrames(work,page.turns,regions.get(index).boxes);
            else{work.paragraphs=[];work.chars=[];work.unsupported=true;}
            captured.delete(index);regions.delete(index);
            pages.push(work);onPage?.(work);
          }
        }catch(error){failed=true;throw error;}
      };
      try{
        await L.analyzePages(win,pageIndexes,{pool,cancelled,known,background,turnsOf:index=>captured.get(index).turns,mediaBoxOf:index=>captured.get(index).mediaBox,onPage:page=>{regions.set(page.pageIndex,page);onLayout?.(page);build();}});
        if(cancelled?.())return null;
      }finally{if(ownPool)pool.close();}
      await C.close(win);closed=true;
      return pages;
    }finally{
      // Stopped or failed, the reader still lets go of its copy of the document.
      if(!closed)await Promise.resolve().then(()=>C.close(win)).catch(()=>{});
    }
  }
  // pages: every page, or a feed of their paragraphs (TwinTextTypesetTranslator.feed) that pages join as they are built.
  async function translateDocument(pages,translate,options){
    const T=global.TwinTextTypesetTranslator;
    return T.translateParagraphs(Array.isArray(pages)?pages.flatMap(page=>page.paragraphs):pages,translate,options);
  }
  global.TwinTextTypesetEngine=Object.freeze({analyzeDocument,translateDocument});
})(this);
