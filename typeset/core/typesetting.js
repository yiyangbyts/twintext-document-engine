// Typeset engine: one typesetter for the whole document. Ported from BabelDOC 0.6.4 document_il/midend/typesetting: each paragraph's best scale,
// the document's most common scale as a ceiling, then the page. Copyright (C) 2026 TwinText; BabelDOC by its authors. SPDX-License-Identifier: AGPL-3.0-only
(function(global){
  'use strict';
  const HUNG=new Set([',','.',':',';','?','!','，','。','．','、','：','；','！','‼','？','⁇','”','’','」','』',')',']','}','）','〕','〉','】','〗','］','｝','》','～','-','–','—','·','・','‧','/','／','⁄']);
  const NO_LINE_END=new Set(['“','‘','「','『','(','[','{','（','〔','〈','《','〖','〘','〚']);
  const CJK_LISTED=new Set(['（','）','【','】','《','》','〔','〕','〈','〉','〖','〗','「','」','『','』','、','。','：','？','！','，']);
  const CJK_RANGE=/^[　-〿぀-ゟ゠-ヿ㄀-ㄯ가-힯ᄀ-ᇿ㄰-㆏ꥠ-꥿ힰ-퟿㆐-㆟㈀-㋿㌀-㏿︰-﹏一-鿿⺀-⻿㇀-㇯⼀-⿟︐-︟]+$/u;
  const CJK_NAMED=/^[㐀-䶿一-鿿﨎﨏﨑﨓﨔﨟﨡﨣﨤﨧-﨩\u{20000}-\u{2a6df}\u{2a700}-\u{2ebef}\u{30000}-\u{323af}！-｠￠-￦]$/u;
  const NO_MIX=new Set(['。','，','：','？','！']);
  let lineBreak=null;
  const box=(x,y,x2,y2)=>({x,y,x2,y2});
  function isCjk(text){
    if(!text||text.includes('(cid')||Array.from(text).length>1)return false;
    return CJK_LISTED.has(text)||CJK_RANGE.test(text)||CJK_NAMED.test(text);
  }
  function unitFrom(fields){
    const unit={...fields,x:null,y:null,scale:null,_box:null};
    return unit;
  }
  const textOf=u=>u.char?u.char.unicode:u.formula?null:u.unicode;
  function boxOf(u,book){
    if(u._box)return u._box;
    if(u.char)u._box=box(u.char.box.x,u.char.visual?u.char.visual.y:u.char.box.y,u.char.box.x2,u.char.visual?u.char.visual.y2:u.char.box.y2);
    else if(u.formula)u._box=u.formula.box;
    else{
      const w=book.width(u.font,u.unicode,u.fontSize);
      u._box=u.x==null?box(0,0,w,u.fontSize):box(u.x,u.y,u.x+w,u.y+u.fontSize);
    }
    return u._box;
  }
  const widthOf=(u,book)=>{const b=boxOf(u,book);return b.x2-b.x;};
  const heightOf=(u,book)=>{const b=boxOf(u,book);return b.y2-b.y;};
  const canBreak=u=>{
    if(u.canBreak!==undefined)return u.canBreak;
    const text=textOf(u);
    if(!lineBreak)lineBreak=new RegExp(global.TwinTextTypesetFontData.LINE_BREAK,'u');
    u.canBreak=!text||!lineBreak.test(text);
    return u.canBreak;
  };
  const cjkOf=u=>{if(u.cjk===undefined)u.cjk=u.formula?false:isCjk(textOf(u));return u.cjk;};
  const passes=u=>u.unicode==null;
  function createUnits(p,fontsById,book){
    const out=[];
    for(const comp of p.comps){
      if(comp.kind==='line'||comp.kind==='same')for(const c of comp.chars)out.push(unitFrom({char:c}));
      else if(comp.kind==='char')out.push(unitFrom({char:comp.char}));
      else if(comp.kind==='formula')out.push(unitFrom({formula:comp}));
      else if(comp.kind==='text'){
        const style=comp.style;
        if(!style||style.font==null||!comp.unicode)continue;
        const original=fontsById[style.font];
        for(const ch of comp.unicode){
          if(ch==='\n')continue;
          const font=book.map(original,ch);
          if(font)out.push(unitFrom({unicode:ch,font,fontSize:style.size,style,xobj:p.xobj}));
        }
      }
    }
    return out;
  }
  function relocate(u,x,y,scale,book){
    if(u.char){
      const w=widthOf(u,book)*scale,h=heightOf(u,book)*scale;
      const char={...u.char,box:box(x,y,x+w,y+h),style:{...u.char.style,size:u.char.style.size*scale},scale,advance:u.char.advance?u.char.advance*scale:u.char.advance};
      return {char,cjk:u.cjk,canBreak:u.canBreak,_box:box(x,char.visual?y:y,x+w,y+h)};
    }
    if(u.formula){
      const f=u.formula,minX=f.box.x,minY=f.box.y,xo=f.xOffset||0,yo=f.yOffset||0;
      const chars=f.chars.map(c=>{
        const relX=c.box.x-minX,relY=c.box.y-minY,vx=c.visual.x-minX,vy=c.visual.y-minY;
        return {...c,box:box(x+(relX+xo)*scale,y+(relY+yo)*scale,x+(relX+(c.box.x2-c.box.x)+xo)*scale,y+(relY+(c.box.y2-c.box.y)+yo)*scale),
          visual:box(x+(vx+xo)*scale,y+(vy+yo)*scale,x+(vx+(c.visual.x2-c.visual.x)+xo)*scale,y+(vy+(c.visual.y2-c.visual.y)+yo)*scale),
          style:{...c.style,size:c.style.size*scale},scale};
      });
      const v=chars.map(c=>c.visual),real=chars.filter(c=>c.cid!=null).map(c=>c.visual),h=real.length?real:v;
      const formula={kind:'formula',chars,moved:(f.curves||[]).map(curve=>({curve,matrix:[scale,0,0,scale,x+xo*scale-minX*scale,y+yo*scale-minY*scale]})),xOffset:xo*scale,yOffset:yo*scale,box:box(Math.min(...v.map(b=>b.x)),Math.min(...h.map(b=>b.y)),Math.max(...v.map(b=>b.x2)),Math.max(...h.map(b=>b.y2)))};
      return {formula,cjk:false,canBreak:u.canBreak,_box:formula.box};
    }
    const next={unicode:u.unicode,font:u.font,fontSize:u.fontSize*scale,style:u.style,xobj:u.xobj,x,y,scale,cjk:u.cjk,canBreak:u.canBreak,_box:null};
    return next;
  }
  function modeOf(values){const counts=new Map();let best=values[0],most=0;for(const v of values){const n=(counts.get(v)||0)+1;counts.set(v,n);if(n>most){most=n;best=v;}}return best;}
  function layoutUnits(units,area,scale,lineSkip,p,englishBreak,book){
    const sizes=[];
    for(const u of units){if(u.fontSize)sizes.push(u.fontSize);if(u.char?.style?.size)sizes.push(u.char.style.size);}
    sizes.sort((a,b)=>a-b);
    const fontSize=modeOf(sizes),base=book.base(),spaceWidth=book.width(base,'你',fontSize*scale)*.5;
    const heights=units.map(u=>heightOf(u,book));
    const avgHeight=!heights.length?0:heights.length===1?heights[0]*scale:modeOf(heights)*scale;
    let currentX=area.x,currentY=area.y2-avgHeight,lineHeight=0,lineHeights=[],last=null,fits=true;
    const placed=[];
    if(p.firstLineIndent)currentX+=spaceWidth*4;
    for(let i=0;i<units.length;i++){
      const u=units[i],w=widthOf(u,book)*scale,h=heightOf(u,book)*scale,text=textOf(u),space=!u.formula&&text===' ';
      if(currentX===area.x&&space)continue;
      if(last&&cjkOf(last)!==cjkOf(u)&&last._lastBox&&last._lastBox.y!=null&&currentY-.1<=last._lastBox.y2&&last._lastBox.y2<=currentY+lineHeight+.1&&!(textOf(last)&&NO_MIX.has(textOf(last)))&&!(text&&NO_MIX.has(text))&&currentX>area.x&&text!==' '&&textOf(last)!==' '&&!['。','！','？','；','：','，'].includes(textOf(last)))currentX+=spaceWidth*.5;
      let before=0;
      if(englishBreak&&!canBreak(u)){
        let total=0,found=false;
        for(let k=i;k<units.length;k++){if(canBreak(units[k])){found=true;break;}total+=widthOf(units[k],book);}
        before=total*scale;
        if(!found)before=total*scale;
      }
      const hung=!u.formula&&text!=null&&HUNG.has(text);
      if(!hung&&(currentX+w>area.x2||englishBreak&&currentX+w+before>area.x2||!u.formula&&NO_LINE_END.has(text)&&currentX+w*2>area.x2)){
        currentX=area.x;
        if(!lineHeights.length)return [[],false];
        const most=Math.max(...lineHeights),common=modeOf(lineHeights);
        currentY-=Math.max(fontSize*scale*lineSkip,common*lineSkip,most*1.05);
        lineHeight=0;lineHeights=[];
        if(currentY<area.y)fits=false;
        if(space){lineHeight=Math.max(lineHeight,h);continue;}
      }
      const moved=relocate(u,currentX,currentY,scale,book);
      placed.push(moved);
      if(!space)lineHeights.push(h);
      const b=boxOf(moved,book);
      const prevX=currentX;currentX=b.x2;
      moved._lastBox=b;
      last=moved;
    }
    return [placed,fits];
  }
  function rightSpace(current,page){
    let limit=page.width*.9;
    const blocked=b=>b.x>current.x&&!(b.y>=current.y2||b.y2<=current.y);
    for(const p of page.paragraphs)if(p.layoutBox&&p.layoutBox!==current&&!same(p.layoutBox,current)&&blocked(p.layoutBox))limit=Math.min(limit,p.layoutBox.x);
    for(const c of page.chars)if(blocked(c.box))limit=Math.min(limit,c.box.x);
    return limit;
  }
  const same=(a,b)=>a.x===b.x&&a.y===b.y&&a.x2===b.x2&&a.y2===b.y2;
  function bottomSpace(current,page){
    let limit=0;
    const blocked=b=>b.y2<current.y&&!(b.x>=current.x2||b.x2<=current.x);
    for(const p of page.paragraphs)if(p.layoutBox&&!same(p.layoutBox,current)&&blocked(p.layoutBox))limit=Math.max(limit,p.layoutBox.y2);
    for(const c of page.chars)if(blocked(c.box))limit=Math.max(limit,c.box.y2);
    return limit;
  }
  function findScale(p,page,units,initial,englishBreak,apply,book){
    let area=p.layoutBox;
    if(!area)return [initial,null];
    let scale=initial,expanded=0;
    const lineSkip=1.5,minScale=.1;
    while(scale>=minScale){
      const [placed,fits]=layoutUnits(units,area,scale,lineSkip,p,englishBreak,book);
      if(fits){if(apply){p.scale=scale;p.placed=placed;}return [scale,placed];}
      scale=scale>.6?scale-.05:scale-.1;
      if(scale<.7){
        let grew=false;
        if(expanded===0){
          const low=bottomSpace(area,page)+2;
          if(low<area.y){area=box(area.x,low,area.x2,area.y2);if(apply)p.layoutBox=area;grew=true;}
          expanded=1;
          if(grew)continue;
        }else if(expanded===1){
          const high=rightSpace(area,page)-5;
          if(high>area.x2){area=box(area.x,area.y,high,area.y2);if(apply)p.layoutBox=area;grew=true;}
          expanded=2;
          if(grew)continue;
        }
        if(expanded<2)scale=1;
      }
    }
    if(englishBreak)return findScale(p,page,units,initial,false,apply,book);
    return [minScale,null];
  }
  function adjustPositions(page){
    const list=page.paragraphs.filter(p=>p.layoutBox);
    for(const upper of list){
      const b=upper.layoutBox,height=b.y2-b.y,gap=height<36?.5:3,area=box(b.x,b.y-gap,b.x2,b.y);
      const conflicts=list.filter(o=>o!==upper&&o.layoutBox.x<=area.x2&&o.layoutBox.x2>=area.x&&o.layoutBox.y<=area.y2&&o.layoutBox.y2>=area.y&&!(o.layoutBox.x2<b.x||o.layoutBox.x>b.x2));
      if(conflicts.length){
        const y=Math.max(...conflicts.map(o=>o.layoutBox.y2))+gap;
        if(y<b.y2)upper.layoutBox={...b,y};
      }
    }
  }
  // Lays out the given pages. With document:true every paragraph is held to the document's most common scale, BabelDOC's rule for the final page.
  function typesetPages(docPages,{book,fontsById,document=true}){
    const pages=docPages.flatMap(page=>page.layers||[page]);
    const all=[],scales=[];
    for(const page of pages){
      page.width=page.media?page.media[2]:page.width;
      for(const p of page.paragraphs)p.layoutBox=p.box?{...p.box}:null;
    }
    for(const page of pages){
      for(const p of page.paragraphs){
        all.push(p);
        const units=createUnits(p,fontsById,book);p.units=units;
        let count=units.length;
        for(const u of units)if(u.formula)count+=u.formula.chars.length-1;
        if(units.every(passes))p.optimal=1;
        else p.optimal=findScale(p,page,units,1,true,false,book)[0];
        for(let i=0;i<count;i++)scales.push(p.optimal);
      }
    }
    if(document&&scales.length){
      const counts=new Map();let most=0;
      for(const s of scales){const n=(counts.get(s)||0)+1;counts.set(s,n);if(n>most)most=n;}
      let mode=Infinity;for(const [s,n] of counts)if(n===most&&s<mode)mode=s;
      for(const p of all)if(p.optimal>mode)p.optimal=mode;
      for(const page of docPages)page.documentScale=mode;
    }
    for(const page of pages){
      adjustPositions(page);
      for(const p of page.paragraphs){
        const units=p.units;p.units=null;
        if(units.every(passes)){p.scale=1;p.placed=units;continue;}
        p.placed=[];
        findScale(p,page,units,p.optimal,true,true,book);
      }
    }
    return docPages;
  }
  global.TwinTextTypesetLayout=Object.freeze({typesetPages,isCjk});
})(this);
