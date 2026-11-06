// Typeset engine, characters in drawing order. Ported from BabelDOC 0.6.4 new_parser (interpreter, text_positioning),
// awlt_char and document_il/frontend/il_creater_active, reading PDF.js's operator list in place of the content stream.
// Copyright (C) 2026 TwinText; BabelDOC by its authors. SPDX-License-Identifier: AGPL-3.0-only
(function(global){
  'use strict';
  const FIELDS=Object.freeze(['unicode','x','y','x2','y2','vx','vy','vx2','vy2','size','font','cid','vertical','advance','xobj','renderOrder','state']);
  // The captured rows as the structure stage reads them.
  const toCharacters=page=>page.chars.map(r=>({unicode:r[0],box:{x:r[1],y:r[2],x2:r[3],y2:r[4]},visual:{x:r[5],y:r[6],x2:r[7],y2:r[8]},style:{font:r[10],size:r[9],state:r[16]},cid:r[11],vertical:r[12],advance:r[13],xobj:r[14],renderOrder:r[15],...(r[17]?{hidden:true}:{}),...(r[18]?{turn:r[18]}:{})}));
  function readingTurns(page){
    const turns=new Set();
    for(const row of page.chars)if(!row[17])turns.add(row[18]||0);
    return turns.size?[...turns].sort((a,b)=>Math.abs(a)-Math.abs(b)):[0];
  }
  // Self-contained: its source is evaluated in the reader's window as well.
  function decode(list,getFont,opsById,view){
    const multiply=(m,n)=>[m[0]*n[0]+m[1]*n[2],m[0]*n[1]+m[1]*n[3],m[2]*n[0]+m[3]*n[2],m[2]*n[1]+m[3]*n[3],m[4]*n[0]+m[5]*n[2]+n[4],m[4]*n[1]+m[5]*n[3]+n[5]];
    const apply=(m,x,y)=>[m[0]*x+m[2]*y+m[4],m[1]*x+m[3]*y+m[5]];
    const moved=(m,x,y)=>[m[0],m[1],m[2],m[3],x*m[0]+y*m[2]+m[4],x*m[1]+y*m[3]+m[5]];
    const pairs=m=>Array.isArray(m)||ArrayBuffer.isView(m)?Array.from(m):null;
    const SPACES=/^[    -​  ⁠　\t]+$/u;
    const rotationOf=m=>Math.atan2(m[1],m[0])*180/Math.PI;
    const chars=[],fonts={},stack=[],xobjects=[];
    // Runs wait in their scope's buffer: a form's characters land when the form ends, ahead of what its parent still holds.
    const MAX_BUFFER=2048,scopes=[[]];
    const flush=scope=>{for(const item of scope)if(item)chars.push(item);scope.length=0;};
    const buffer=item=>{const scope=scopes.at(-1);scope.push(item);if(scope.length>=MAX_BUFFER)flush(scope);};
    let xobjectSerial=0,renderOrder=0;
    let s={ctm:[1,0,0,1,0,0],text:[1,0,0,1,0,0],lineX:0,lineY:0,fontId:null,font:null,size:0,charSpacing:0,wordSpacing:0,hscale:100,leading:0,rise:0,mode:0,state:[]};
    const copy=()=>({...s,ctm:[...s.ctm],state:[...s.state]});
    // What travels with a character besides its font: BabelDOC's per-character operators. A later value replaces an earlier one, except for extended states.
    const setState=(key,value)=>{const at=s.state.findIndex(e=>e[0]===key);if(at>=0&&key!=='gs')s.state[at]=[key,value];else s.state.push([key,value]);};
    const stateKey=()=>s.state.map(e=>e[0]+' '+e[1]).join(' ');
    const fontOf=id=>{
      if(!id)return null;
      if(!(id in fonts)){
        const f=getFont(id)||{};
        fonts[id]={id,name:f.name||'',composite:Boolean(f.composite),vertical:Boolean(f.vertical),type3:Boolean(f.isType3Font||f.type==='Type3'),
          fontMatrix:f.fontMatrix?Array.from(f.fontMatrix):[.001,0,0,.001,0,0],defaultVMetrics:f.defaultVMetrics?Array.from(f.defaultVMetrics):null,
          textOf:f.textOf||null,outline:f.outline||null,specified:Boolean(f.specified),emHeight:f.emHeight||0,descent:f.descent3||0};
      }
      return fonts[id];
    };
    const moveText=(x,y)=>{s.text=moved(s.text,x,y);s.lineX=0;s.lineY=0;};
    const unicodeOf=(font,glyph)=>font.textOf?font.textOf(glyph):String(glyph.unicode||`(cid:${glyph.originalCharCode})`);
    function show(glyphs){
      const font=s.font;
      if(!font||!glyphs)return;
      const scaling=s.hscale*.01,charspace=s.charSpacing*scaling,wordspace=font.composite?0:s.wordSpacing*scaling,dxscale=.001*s.size*scaling;
      const matrix=multiply(s.text,s.ctm),vertical=font.vertical,widthScale=font.type3?Math.abs(font.fontMatrix[0]):.001;
      let x=s.lineX,y=s.lineY,need=false;
      for(const glyph of glyphs){
        if(typeof glyph==='number'){if(vertical)y-=glyph*dxscale;else x-=glyph*dxscale;need=true;continue;}
        if(!glyph)continue;
        if(need){if(vertical)y+=charspace;else x+=charspace;}
        const code=glyph.originalCharCode;
        const width=vertical?(glyph.vmetric?glyph.vmetric[0]:font.defaultVMetrics?font.defaultVMetrics[1]:-1000)*.001:glyph.width*widthScale;
        const advance=width*s.size*scaling,m=moved(matrix,x,y);
        if(s.mode!==7){
          let ll,ur;
          if(vertical){
            const vx=glyph.vmetric?glyph.vmetric[1]*s.size*.001:s.size*.5,vy=(1000-(glyph.vmetric?glyph.vmetric[2]:font.defaultVMetrics?font.defaultVMetrics[0]:880))*s.size*.001;
            ll=[-vx,vy+s.rise+advance];ur=[-vx+s.size,vy+s.rise];
          }else{
            // The box starts at the baseline: BabelDOC sets every font's descent to nothing before it measures.
            ll=[0,s.rise];ur=[advance,s.rise+s.size];
          }
          let [x0,y0]=apply(m,ll[0],ll[1]),[x1,y1]=apply(m,ur[0],ur[1]);
          if(x1<x0)[x0,x1]=[x1,x0];
          if(y1<y0)[y0,y1]=[y1,y0];
          const upright=m[0]===0&&m[3]===0,size=vertical||upright||m[0]===0?x1-x0:y1-y0,angle=rotationOf(m);
          if(size!==0&&(Math.abs(angle)<=.1||Math.abs(angle-90)<=.1)){
            let text=unicodeOf(font,glyph);
            if(SPACES.test(text))text=' ';
            const fontSize=size*(font.emHeight||1),descent=(font.descent||0)*fontSize;
            let visual=upright?[x0-descent,y0,x1-descent,y1]:[x0,y0+descent,x1,y1+descent];
            const box=font.outline&&text!==' '?font.outline(glyph):null;
            if(box){
              const v=[x0+box[0]*fontSize,y0+box[1]*fontSize,x0+box[2]*fontSize,y0+box[3]*fontSize];
              if((v[2]-v[0])*(v[3]-v[1])>1)visual=v;
            }
            buffer([text,x0,y0,x1,y1,visual[0],visual[1],visual[2],visual[3],fontSize,s.fontId,code,upright||vertical,advance,xobjects.at(-1)??0,renderOrder++,stateKey()]);
          }
        }
        if(vertical){y+=advance;if(code===32&&wordspace)y+=wordspace;}
        else{x+=advance;if(code===32&&wordspace)x+=wordspace;}
        need=true;
      }
      s.lineX=x;s.lineY=y;
    }
    for(let i=0;i<list.fnArray.length;i++){
      const op=opsById[list.fnArray[i]],a=list.argsArray[i]||[];
      switch(op){
        case 'save':stack.push(copy());break;
        case 'restore':if(stack.length)s=stack.pop();break;
        case 'transform':s.ctm=multiply(a,s.ctm);break;
        case 'paintFormXObjectBegin':{
          stack.push(copy());xobjects.push(++xobjectSerial);scopes.push([]);s.state=[];
          const m=pairs(a[0]);if(m&&m.length===6)s.ctm=multiply(m,s.ctm);
          break;
        }
        case 'paintFormXObjectEnd':if(stack.length)s=stack.pop();xobjects.pop();if(scopes.length>1)flush(scopes.pop());break;
        case 'constructPath':if(opsById[a[0]]!=='endPath'&&opsById[a[0]]!==undefined)buffer(null);break;
        case 'stroke':case 'closeStroke':case 'fill':case 'eoFill':case 'fillStroke':case 'eoFillStroke':case 'closeFillStroke':case 'closeEOFillStroke':buffer(null);break;
        case 'shadingFill':buffer(null);break;
        case 'beginText':s.text=[1,0,0,1,0,0];s.lineX=0;s.lineY=0;break;
        case 'setTextMatrix':{const m=pairs(a[0])&&a.length===1?pairs(a[0]):Array.from(a);s.text=m;s.lineX=0;s.lineY=0;break;}
        case 'setFont':s.fontId=a[0];s.font=fontOf(a[0]);s.size=a[1];break;
        case 'setCharSpacing':s.charSpacing=a[0];break;
        case 'setWordSpacing':s.wordSpacing=a[0];break;
        case 'setHScale':s.hscale=a[0];break;
        case 'setLeading':s.leading=a[0];break;
        case 'setTextRise':s.rise=a[0];break;
        case 'setTextRenderingMode':s.mode=a[0];break;
        case 'setFillRGBColor':setState('fill',typeof a[0]==='string'?a[0]:Array.from(a).join(','));break;
        case 'setStrokeRGBColor':setState('stroke',typeof a[0]==='string'?a[0]:Array.from(a).join(','));break;
        case 'setFillTransparent':setState('fill','none');break;
        case 'setStrokeTransparent':setState('stroke','none');break;
        case 'setLineWidth':setState('w',a[0]);break;
        case 'setLineCap':setState('J',a[0]);break;
        case 'setLineJoin':setState('j',a[0]);break;
        case 'setMiterLimit':setState('M',a[0]);break;
        case 'setFlatness':setState('i',a[0]);break;
        case 'setRenderingIntent':setState('ri',a[0]);break;
        case 'setGState':setState('gs',JSON.stringify(a[0]));break;
        case 'moveText':moveText(a[0],a[1]);break;
        case 'setLeadingMoveText':s.leading=-a[1];moveText(a[0],a[1]);break;
        case 'nextLine':moveText(0,-s.leading);break;
        case 'showText':case 'showSpacedText':show(a[0]);break;
        case 'nextLineShowText':moveText(0,-s.leading);show(a[0]);break;
        case 'nextLineSetSpacingShowText':s.wordSpacing=a[0];s.charSpacing=a[1];moveText(0,-s.leading);show(a[2]);break;
      }
    }
    while(scopes.length)flush(scopes.pop());
    for(const font of Object.values(fonts)){delete font.textOf;delete font.outline;}
    return {chars,fonts};
  }
  // A glyph's control box from its outline, in ems, with the origin at its place on the baseline.
  function outlineBox(path){
    if(!path?.length)return null;
    let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity,moveX=0,moveY=0,moved=false;
    const see=(x,y)=>{if(x<x0)x0=x;if(x>x1)x1=x;if(y<y0)y0=y;if(y>y1)y1=y;};
    for(let i=0;i<path.length;){
      const op=path[i++],n=[2,2,6,4,0][op];
      if(n===undefined)return null;
      // A move alone draws nothing: only one that leads to a segment counts.
      if(op===0){moveX=path[i];moveY=path[i+1];moved=true;i+=n;continue;}
      if(op===1&&moved&&path[i]===moveX&&path[i+1]===moveY){i+=n;continue;}
      if(n&&moved){see(moveX,moveY);moved=false;}
      for(let k=0;k<n;k+=2)see(path[i+k],path[i+k+1]);
      i+=n;
    }
    return x0===Infinity?null:[x0,y0,x1,y1];
  }
  // Runs in the reader's window, once per document: a short-lived private PDF.js document with outlines kept,
  // so the reader's own fonts and operator lists stay as they are, and the file's own objects beside it.
  function runtimeSource(){
    const data=global.TwinTextTypesetFontData;
    return `(()=>{
      const decode=${decode.toString()},outlineBox=${outlineBox.toString()},createPdfObjects=${global.TwinTextTypesetPdfObjects.createPdfObjects.toString()},inflateSource=${global.TwinTextTypesetPdfObjects.inflateSync.toString()},interpretPage=${global.TwinTextTypesetContent.interpretPage.toString()},fontRuntime=${global.TwinTextTypesetContent.fontRuntime.toString()};
      const FONT_DATA=${JSON.stringify(data)};
      const inflate=async bytes=>inflateSource(bytes);
      const squash=name=>String(name||'').replace(/[^A-Za-z0-9]/g,'').toLowerCase();
      async function matchSpecs(state,pageIndex){
        if(state.objectsFailed)return [];
        try{
          const objects=await state.objects,list=await objects.pageFonts(pageIndex),out=[];
          for(const font of list){
            const key=font.ref??font;
            if(!state.specs.has(key)){
              const spec=await objects.fontSpec(font.dict).catch(()=>null);
              // BabelDOC clears a font's descent once it has met it: only the first page that lists the font keeps it for glyphs without a box.
              if(spec)spec.firstPage=pageIndex;
              state.specs.set(key,spec);
            }
            const spec=state.specs.get(key);if(spec)out.push(spec);
          }
          return out;
        }catch(error){state.objectsFailed=String(error?.message||error);return [];}
      }
      const pick=(specs,f)=>{
        const name=squash(f.name),same=specs.filter(s=>s.composite===Boolean(f.composite)&&(squash(s.baseFont)===name||squash(s.baseFont).endsWith(name)||name.endsWith(squash(s.baseFont))));
        if(same.length<2)return same[0]||null;
        const widths=f.widths||[],mapped=f.toUnicode?._map||[];let best=same[0],score=-1;
        for(const s of same){
          let hit=0;
          (s.widths||[]).forEach((w,i)=>{if(widths[s.firstChar+i]===w)hit++;});
          s.toUnicode?.forEach((text,code)=>{if(mapped[code]===text)hit+=2;});
          if(hit>score){score=hit;best=s;}
        }
        return best;
      };
      window.__twintextTypesetRuntime={
        async capture(pageIndex){
          const source=PDFViewerApplication.pdfDocument;let state=window.__twintextTypesetChars;
          if(state?.source!==source){await state?.task?.destroy();state=null;}
          if(!state){
            const pdfjs=await import('resource://zotero/reader/pdf/build/pdf.mjs'),bytes=await source.getData();
            const worker=new pdfjs.PDFWorker({name:'TwinText typeset characters'});
            const task=pdfjs.getDocument({worker,data:bytes.slice(),disableFontFace:true,fontExtraProperties:true,isEvalSupported:false,useSystemFonts:false,cMapUrl:'resource://zotero/reader/pdf/web/cmaps/',standardFontDataUrl:'resource://zotero/reader/pdf/web/standard_fonts/'});
            state={source,task,worker,ready:task.promise,OPS:pdfjs.OPS,specs:new Map(),objects:createPdfObjects(bytes,inflate,FONT_DATA).open()};
            state.objects.catch(error=>{state.objectsFailed=String(error?.message||error);});
            window.__twintextTypesetChars=state;
          }
          const doc=await state.ready,page=await doc.getPage(pageIndex+1),list=await page.getOperatorList();
          const names=Object.fromEntries(Object.entries(state.OPS).map(([name,id])=>[id,name])),ids=new Set();
          for(let i=0;i<list.fnArray.length;i++)if(list.fnArray[i]===state.OPS.setFont)ids.add(list.argsArray[i][0]);
          await Promise.all([...ids].map(id=>new Promise(done=>{const value=page.commonObjs.get(id,done);if(value)done(value);})));
          const get=id=>{try{return page.commonObjs.get(id);}catch(_){return null;}};
          const specs=await matchSpecs(state,pageIndex);
          // The content stream itself gives exact coordinates. PDF.js still supplies outlines, and takes over where the file cannot be read here.
          const glyphsByFont=new Map();
          {
            let current=null;
            for(let i=0;i<list.fnArray.length;i++){
              const fn=list.fnArray[i],a=list.argsArray[i];
              if(fn===state.OPS.setFont){current=a[0];if(!glyphsByFont.has(current))glyphsByFont.set(current,new Map());continue;}
              const run=fn===state.OPS.showText||fn===state.OPS.showSpacedText||fn===state.OPS.nextLineShowText?a[0]:fn===state.OPS.nextLineSetSpacingShowText?a[2]:null;
              if(run&&current)for(const g of run)if(g&&typeof g==='object')glyphsByFont.get(current).set(g.originalCharCode,g);
            }
          }
          const pdfFonts=[...glyphsByFont.keys()].map(id=>({id,font:get(id),glyphs:glyphsByFont.get(id)})).filter(e=>e.font);
          let exact=null;
          if(!state.objectsFailed){
            try{
              const objects=await state.objects,runtimes=new Map();
              const keyOf=ref=>ref?.num!==undefined?ref.num:ref;
              const fontFor=ref=>runtimes.get(keyOf(ref))||null;
              fontFor.prepare=async ref=>{
                const key=keyOf(ref);
                if(runtimes.has(key))return;
                const dict=await objects.resolve(ref);
                if(!dict||typeof dict!=='object'){runtimes.set(key,null);return;}
                if(!state.specs.has(key)){
                  const fresh=await objects.fontSpec(dict).catch(()=>null);
                  if(fresh)fresh.firstPage=pageIndex;
                  state.specs.set(key,fresh);
                }
                const spec=state.specs.get(key)||{};
                const wanted=squash(spec.baseFont),match=pdfFonts.filter(e=>{
                  if(Boolean(e.font.composite)!==Boolean(spec.composite))return false;
                  const name=squash(e.font.name);
                  return name===wanted||name.includes(wanted)||wanted.includes(name);
                });
                let chosen=match[0]||null;
                if(match.length>1){
                  let best=-1;
                  for(const e of match){
                    let hit=0;const mapped=e.font.toUnicode?._map||[];
                    spec.toUnicode?.forEach((text,code)=>{if(mapped[code]===text)hit+=2;});
                    (spec.widths||[]).forEach((w,i)=>{if((e.font.widths||[])[spec.firstChar+i]===w)hit++;});
                    if(hit>best){best=hit;chosen=e;}
                  }
                }
                const boxes=new Map();
                const runtime=await fontRuntime(objects,dict,spec,FONT_DATA,{
                  id:'f'+(typeof key==='number'?key:squash(spec.baseFont)),
                  descentOnPage:page=>spec.type3||spec.firstPage===page?spec.descent:0,
                  outline(cid){
                    if(spec.type3)return spec.type3.boxes.get(cid)||null;
                    if(spec.base14){const b=spec.base14[cid];return b?b.map(v=>v/1000):null;}
                    if(!spec.embedded||!chosen)return null;
                    const glyph=chosen.glyphs.get(cid);if(!glyph)return null;
                    if(!boxes.has(cid))boxes.set(cid,outlineBox(get(chosen.font.loadedName+'_path_'+glyph.fontChar)?.path));
                    return boxes.get(cid);
                  },
                  fallbackText(cid){
                    const glyph=chosen?.glyphs.get(cid);
                    return String(glyph?.unicode||'(cid:'+cid+')');
                  }
                });
                runtimes.set(key,runtime);
              };
              exact=await interpretPage(objects,pageIndex,fontFor);
            }catch(error){state.contentFailed=String(error?.message||error);}
          }
          if(exact){
            const mediaBox=await (await state.objects).pageMediaBox(pageIndex).catch(()=>null);
            return JSON.stringify({view:page.view,rotate:page.rotate,mediaBox,source:'content',objectsFailed:null,...exact});
          }
          const result=decode(list,id=>{
            const f=get(id);if(!f)return null;
            const spec=pick(specs,f),boxes=new Map();
            return {name:f.name,composite:f.composite,vertical:f.vertical,isType3Font:f.isType3Font,type:f.type,fontMatrix:f.fontMatrix,defaultVMetrics:f.defaultVMetrics,specified:Boolean(spec),
              emHeight:spec?.type3?.emHeight||0,descent3:spec&&(spec.type3||spec.firstPage===pageIndex)?spec.descent:0,
              outline(glyph){
                if(spec?.type3)return spec.type3.boxes.get(glyph.originalCharCode)||null;
                if(spec?.base14){const b=spec.base14[glyph.originalCharCode];return b?b.map(v=>v/1000):null;}
                if(spec&&!spec.embedded)return null;
                const key=glyph.fontChar;
                if(!boxes.has(key))boxes.set(key,outlineBox(get(f.loadedName+'_path_'+key)?.path));
                return boxes.get(key);
              },
              textOf:spec?glyph=>{
                const code=glyph.originalCharCode;
                if(spec.toUnicode?.has(code))return spec.toUnicode.get(code);
                if(spec.encoding?.has(code))return spec.encoding.get(code);
                if(spec.composite&&!spec.toUnicode)return String(glyph.unicode||'(cid:'+code+')');
                return '(cid:'+code+')';
              }:null};
          },names,page.view);
          const mediaBox=state.objectsFailed?null:await (await state.objects).pageMediaBox(pageIndex).catch(()=>null);
          return JSON.stringify({view:page.view,rotate:page.rotate,mediaBox,source:'pdfjs',contentFailed:state.contentFailed||null,objectsFailed:state.objectsFailed||null,...result});
        },
        async close(){const state=window.__twintextTypesetChars;window.__twintextTypesetChars=null;await state?.task?.destroy();}
      };
    })()`;
  }
  async function capture(win,pageIndex){
    if(!win.eval('Boolean(window.__twintextTypesetRuntime)'))win.eval(runtimeSource());
    return JSON.parse(await win.eval(`window.__twintextTypesetRuntime.capture(${Number(pageIndex)})`));
  }
  function close(win){
    return win.eval('window.__twintextTypesetRuntime?.close()');
  }
  global.TwinTextTypesetChars=Object.freeze({FIELDS,toCharacters,readingTurns,decode,outlineBox,capture,close});
})(this);
