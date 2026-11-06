// Typeset engine: the target fonts. What BabelDOC asks of PyMuPDF (does a font hold a character, how wide is it), read from the files themselves.
// Mapping rules ported from BabelDOC 0.6.4 document_il/utils/fontmap. Copyright (C) 2026 TwinText; BabelDOC by its authors. SPDX-License-Identifier: AGPL-3.0-only
(function(global){
  'use strict';
  function parseFont(bytes){
    const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength),tables={},count=view.getUint16(4);
    for(let i=0;i<count;i++){
      const at=12+i*16,tag=String.fromCharCode(bytes[at],bytes[at+1],bytes[at+2],bytes[at+3]);
      tables[tag]={offset:view.getUint32(at+8),length:view.getUint32(at+12)};
    }
    const unitsPerEm=view.getUint16(tables.head.offset+18),longLoca=view.getInt16(tables.head.offset+50)===1;
    const numHMetrics=view.getUint16(tables.hhea.offset+34),numGlyphs=view.getUint16(tables.maxp.offset+4);
    const cmap=tables.cmap.offset,subtables=[];
    for(let i=0,n=view.getUint16(cmap+2);i<n;i++)subtables.push({platform:view.getUint16(cmap+4+i*8),encoding:view.getUint16(cmap+6+i*8),offset:cmap+view.getUint32(cmap+8+i*8)});
    const pick=subtables.find(s=>s.platform===3&&s.encoding===10)||subtables.find(s=>s.platform===0&&s.encoding>=4)||subtables.find(s=>s.platform===3&&s.encoding===1)||subtables.find(s=>s.platform===0);
    const format=view.getUint16(pick.offset);
    let glyphOf;
    if(format===12){
      const groups=view.getUint32(pick.offset+12),base=pick.offset+16;
      glyphOf=code=>{let low=0,high=groups-1;while(low<=high){const mid=(low+high)>>1,at=base+mid*12,start=view.getUint32(at),end=view.getUint32(at+4);if(code<start)high=mid-1;else if(code>end)low=mid+1;else return view.getUint32(at+8)+code-start;}return 0;};
    }else if(format===4){
      const seg=view.getUint16(pick.offset+6)/2,ends=pick.offset+14,starts=ends+seg*2+2,deltas=starts+seg*2,ranges=deltas+seg*2;
      glyphOf=code=>{
        if(code>0xffff)return 0;
        let low=0,high=seg-1;
        while(low<high){const mid=(low+high)>>1;if(view.getUint16(ends+mid*2)<code)low=mid+1;else high=mid;}
        const start=view.getUint16(starts+low*2);
        if(code<start||code>view.getUint16(ends+low*2))return 0;
        const delta=view.getInt16(deltas+low*2),range=view.getUint16(ranges+low*2);
        if(!range)return (code+delta)&0xffff;
        const g=view.getUint16(ranges+low*2+range+(code-start)*2);
        return g?(g+delta)&0xffff:0;
      };
    }else throw new Error('Unsupported cmap format');
    const hmtx=tables.hmtx.offset;
    const advanceOf=gid=>view.getUint16(hmtx+Math.min(gid,numHMetrics-1)*4);
    return {bytes,view,tables,unitsPerEm,longLoca,numGlyphs,glyphOf,advanceOf};
  }
  // Keeps every glyph number and drops the outlines of glyphs not used, with the glyphs a used composite needs.
  function subsetFont(font,used){
    const {bytes,view,tables,longLoca,numGlyphs}=font,glyf=tables.glyf.offset,loca=tables.loca.offset;
    const offsetOf=g=>longLoca?view.getUint32(loca+g*4):view.getUint16(loca+g*2)*2;
    const keep=new Set([0]),stack=[...used];
    while(stack.length){
      const g=stack.pop();
      if(g>=numGlyphs||keep.has(g)&&g!==0&&false)continue;
      keep.add(g);
      const start=offsetOf(g),end=offsetOf(g+1);
      if(end<=start||view.getInt16(glyf+start)>=0)continue;
      let at=glyf+start+10;
      for(;;){
        const flags=view.getUint16(at),part=view.getUint16(at+2);
        if(!keep.has(part)){keep.add(part);stack.push(part);}
        at+=4+(flags&1?4:2);
        if(flags&8)at+=2;else if(flags&0x40)at+=4;else if(flags&0x80)at+=8;
        if(!(flags&0x20))break;
      }
    }
    let total=0;for(const g of keep)total+=(offsetOf(g+1)-offsetOf(g)+3)&~3;
    const newGlyf=new Uint8Array(total),newLoca=new Uint8Array((numGlyphs+1)*4),locaView=new DataView(newLoca.buffer);let pos=0;
    for(let g=0;g<numGlyphs;g++){
      locaView.setUint32(g*4,pos);
      if(keep.has(g)){const s=offsetOf(g),e=offsetOf(g+1);newGlyf.set(bytes.subarray(glyf+s,glyf+e),pos);pos+=(e-s+3)&~3;}
    }
    locaView.setUint32(numGlyphs*4,pos);
    const parts={head:null,hhea:null,hmtx:null,maxp:null,cvt:null,fpgm:null,prep:null};
    const wanted=['cvt ','fpgm','glyf','head','hhea','hmtx','loca','maxp','prep'].filter(t=>tables[t]);
    const content=wanted.map(tag=>{
      if(tag==='glyf')return newGlyf;
      if(tag==='loca')return newLoca;
      const copy=bytes.slice(tables[tag].offset,tables[tag].offset+tables[tag].length);
      if(tag==='head')new DataView(copy.buffer).setInt16(50,1);
      return copy;
    });
    let offset=12+wanted.length*16;
    const size=content.reduce((sum,c)=>sum+((c.length+3)&~3),offset),out=new Uint8Array(size),outView=new DataView(out.buffer);
    outView.setUint32(0,0x00010000);outView.setUint16(4,wanted.length);
    wanted.forEach((tag,i)=>{
      const at=12+i*16;for(let k=0;k<4;k++)out[at+k]=tag.charCodeAt(k);
      outView.setUint32(at+8,offset);outView.setUint32(at+12,content[i].length);
      out.set(content[i],offset);offset+=(content[i].length+3)&~3;
    });
    return out;
  }
  // loader(fileName) gives the font file's bytes. Serif or sans follows the reader's setting, as BabelDOC's primary font family does.
  function createBook(loader,{primary='serif'}={}){
    const D=global.TwinTextTypesetFontData,loaded=new Map(),family=D.FONT_FAMILY;
    const open=async name=>{if(!loaded.has(name))loaded.set(name,{id:name,name,facts:D.FONT_FACTS[name],font:parseFont(await loader(name))});return loaded.get(name);};
    const ready=(async()=>{for(const name of new Set(Object.values(family).flat()))await open(name);})();
    const get=name=>loaded.get(name);
    const types={script:()=>family.script.map(get),normal:()=>family.normal.map(get),fallback:()=>family.fallback.map(get)};
    const has=(entry,code)=>entry.font.glyphOf(code)!==0;
    const inType=(bold,italic,serif,code,type)=>{
      if(type==='script'&&!italic)return null;
      for(const entry of types[type]()){
        if(!has(entry,code))continue;
        if(Boolean(bold)!==Boolean(entry.facts.bold))continue;
        const named=entry.id.toLowerCase().includes('serif');
        if(serif&&!named||!serif&&named)continue;
        return entry;
      }
      return null;
    };
    const memo=new Map();
    function map(original,char){
      const code=char.codePointAt(0),italic=Boolean(original?.italic),bold=Boolean(original?.bold),serif=primary==='sans'?false:primary==='serif'?true:Boolean(original?.serif);
      const key=(bold?1:0)+(italic?2:0)+(serif?4:0)+code*8;
      if(memo.has(key))return memo.get(key);
      let found=inType(bold,italic,serif,code,'script');
      if(!found&&italic)found=types.script().find(e=>has(e,code))||null;
      found=found||inType(bold,italic,serif,code,'normal')||inType(bold,italic,serif,code,'fallback')||types.fallback().find(e=>has(e,code))||null;
      memo.set(key,found);
      return found;
    }
    const width=(entry,char,size)=>entry.font.advanceOf(entry.font.glyphOf(char.codePointAt(0)))/entry.font.unitsPerEm*size;
    return {ready,map,width,get,base:()=>get(family.base[0])};
  }
  global.TwinTextTypesetFonts=Object.freeze({parseFont,subsetFont,createBook});
})(this);
