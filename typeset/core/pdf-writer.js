// Typeset engine: a translated PDF, written as an incremental update of the source file. Text-showing operators leave the page's content, graphics stay
// in their order, and every character is drawn again where the typesetter put it. Follows BabelDOC 0.6.4 document_il/backend/pdf_creater in effect.
// Copyright (C) 2026 TwinText; BabelDOC by its authors. SPDX-License-Identifier: AGPL-3.0-only
(function(global){
  'use strict';
  const WHITE=new Set([0,9,10,12,13,32]),DELIM=new Set([40,41,60,62,91,93,123,125,47,37]);
  const isWord=b=>!WHITE.has(b)&&!DELIM.has(b);
  const SHOW=new Set(['Tj','TJ',"'",'"']);
  const multiply=(l,r)=>[r[0]*l[0]+r[2]*l[1],r[1]*l[0]+r[3]*l[1],r[0]*l[2]+r[2]*l[3],r[1]*l[2]+r[3]*l[3],r[0]*l[4]+r[2]*l[5]+r[4],r[1]*l[4]+r[3]*l[5]+r[5]];
  // The stream without its text-showing operators. Text that only clips, and text the character stage does not read (turned any way but 0 or a quarter turn), stays.
  function stripText(data,movedCurves=null,startCtm=[1,0,0,1,0,0]){
    const remove=[];let p=0,group=0,numbers=[],mode=0,ctm=startCtm,tm=[1,0,0,1,0,0],pathStart=-1,pathFromMove=false,ordinal=0;const stack=[];
    const skipString=()=>{let depth=1;p++;while(p<data.length&&depth){const b=data[p++];if(b===92)p++;else if(b===40)depth++;else if(b===41)depth--;}};
    const skipValue=()=>{
      const c=data[p];
      if(c===40)return skipString();
      if(c===60&&data[p+1]===60){p+=2;let depth=1;while(p<data.length&&depth){if(data[p]===60&&data[p+1]===60){depth++;p+=2;}else if(data[p]===62&&data[p+1]===62){depth--;p+=2;}else if(data[p]===40)skipString();else p++;}return;}
      if(c===60){while(p<data.length&&data[p]!==62)p++;p++;return;}
      if(c===91){p++;while(p<data.length&&data[p]!==93){if(WHITE.has(data[p])){p++;continue;}skipValue();}p++;return;}
      if(c===47){p++;while(p<data.length&&isWord(data[p]))p++;return;}
      p++;
    };
    while(p<data.length){
      const c=data[p];
      if(WHITE.has(c)){p++;continue;}
      if(c===37){while(p<data.length&&data[p]!==10&&data[p]!==13)p++;continue;}
      if(!isWord(c)){skipValue();continue;}
      const start=p;while(p<data.length&&isWord(data[p]))p++;
      let word='';for(let i=start;i<p;i++)word+=String.fromCharCode(data[i]);
      const m=/^([-+]?\d*\.?\d*)(.*)$/su.exec(word);
      if(m[1]&&/\d/.test(m[1])&&!m[2]){numbers.push(Number(m[1]));continue;}
      if(m[1]&&/\d/.test(m[1]))numbers.push(Number(m[1]));
      const op=m[1]&&/\d/.test(m[1])?m[2]:word;
      if(op==='BI'){
        let at=p;
        for(;;){at=data.indexOf(69,at);if(at<0){p=data.length;break;}if(data[at+1]===73&&!isWord(data[at-1])&&(at+2>=data.length||!isWord(data[at+2]))){p=at+2;break;}at++;}
      }else if(op==='q')stack.push([ctm,mode,tm]);
      else if(op==='Q'){if(stack.length)[ctm,mode,tm]=stack.pop();}
      else if(op==='cm'&&numbers.length>=6)ctm=multiply(numbers.slice(-6),ctm);
      else if(op==='Tm'&&numbers.length>=6)tm=numbers.slice(-6);
      else if(op==='BT')tm=[1,0,0,1,0,0];
      else if(op==='Tr'&&numbers.length)mode=Math.trunc(numbers.at(-1));
      else if(['m','l','c','v','y','re','h'].includes(op)){
        const need={m:2,l:2,c:6,v:4,y:4,re:4,h:0}[op];
        if(numbers.length>=need&&pathStart<0){pathStart=group;pathFromMove=op==='m'||op==='re';}
      }else if(op==='n'){pathStart=-1;}
      else if(['S','s','f','F','f*','B','B*','b','b*'].includes(op)){
        if(['s','b','b*'].includes(op)&&pathStart<0){pathStart=group;pathFromMove=false;}
        if(pathStart>=0&&pathFromMove){if(movedCurves?.has(ordinal))remove.push([pathStart,p]);ordinal++;}
        pathStart=-1;
      }else if(SHOW.has(op)&&mode<4){
        const m2=multiply(tm,ctm),angle=Math.atan2(m2[1],m2[0])*180/Math.PI;
        if(Math.abs(angle)<=.1||Math.abs(Math.abs(angle)-90)<=.1)remove.push([group,p]);
      }
      numbers=[];group=p;
    }
    if(!remove.length)return data;
    const size=remove.reduce((n,[a,b])=>n-(b-a)+1,data.length),out=new Uint8Array(size);let from=0,to=0;
    for(const [a,b] of remove){out.set(data.subarray(from,a),to);to+=a-from;out[to++]=32;from=b;}
    out.set(data.subarray(from),to);
    return out;
  }
  const hex=(value,digits)=>value.toString(16).toUpperCase().padStart(digits,'0');
  const num=v=>{const s=v.toFixed(6).replace(/\.?0+$/u,'');return s==='-0'?'0':s||'0';};
  const textBytes=text=>{const out=new Uint8Array(text.length);for(let i=0;i<text.length;i++)out[i]=text.charCodeAt(i)&255;return out;};
  function createWriter({objects,bytes,deflate,book,fontInfo}){
    const {Stream,Name,Ref,resolve}=objects;
    let nextNumber=Math.max(Number(objects.trailer.Size)||0,objects.size+1);
    const allocate=()=>nextNumber++;
    const baseObjects=new Map(),formClones=new Map(),pageBases=new Map();
    function serialize(v){
      if(v==null)return 'null';
      if(v instanceof Ref)return `${v.num} 0 R`;
      if(v instanceof Name)return '/'+v.name.replace(/[^!-~]|[#%()/<>[\]{}]/gu,c=>'#'+c.charCodeAt(0).toString(16).padStart(2,'0'));
      if(typeof v==='number')return Number.isInteger(v)?String(v):num(v);
      if(typeof v==='boolean')return String(v);
      if(typeof v==='string')return v;
      if(Array.isArray(v))return '['+v.map(serialize).join(' ')+']';
      if(v?.bytes)return '<'+Array.from(v.bytes,b=>hex(b,2)).join('')+'>';
      if(v instanceof Stream)return 'null';
      return '<<'+Object.entries(v).map(([k,x])=>serialize(new Name(k))+' '+serialize(x)).join(' ')+'>>';
    }
    const packStream=async(data,dict={})=>{
      const packed=await deflate(Uint8Array.from(data));
      return {dict:{...dict,Filter:new Name('FlateDecode')},data:packed};
    };
    async function resourceCopy(resources,parent,collect,moved){
      const res=await resolve(resources);
      const out=res?{...res}:{};
      const xobjects=await resolve(out.XObject);
      for(const key of ['ColorSpace','ExtGState','Pattern','Shading']){
        const table=await resolve(out[key]);
        if(table&&collect)collect[key]={...table,...(collect[key]||{})};
      }
      if(xobjects){
        const copy={};
        for(const [name,ref] of Object.entries(xobjects)){
          const form=await resolve(ref);
          if(form instanceof Stream&&(await resolve(form.dict.Subtype))?.name==='Form'&&ref instanceof Ref)copy[name]=new Ref(await cloneForm(ref.num,form,res,collect,moved));
          else copy[name]=ref;
        }
        out.XObject=copy;
      }
      return out;
    }
    async function cloneForm(number,form,parent,collect,moved){
      const key=number+':'+[...(moved?.get(number)||[])].sort((a,b)=>a-b).join(',');
      if(formClones.has(key))return formClones.get(key);
      const fresh=allocate();formClones.set(key,fresh);
      const dict={...form.dict};
      for(const key of ['Filter','F','DecodeParms','DP','Length'])delete dict[key];
      dict.Resources=await resourceCopy(form.dict.Resources!==undefined?form.dict.Resources:parent,parent,collect,moved);
      baseObjects.set(fresh,await packStream(stripText(await objects.streamData(form),moved?.get(number)||null),dict));
      return fresh;
    }
    async function pageBase(index,moved){
      const memo=index+':'+[...moved].map(([k,v])=>k+'='+[...v].sort((a,b)=>a-b).join(',')).sort().join(';');
      if(pageBases.has(memo))return pageBases.get(memo);
      const page=await objects.pageDict(index);
      const contents=await resolve(page.Contents),streams=Array.isArray(contents)?contents:contents?[contents]:[],parts=[];
      for(const entry of streams){const s=await resolve(entry);if(s instanceof Stream){parts.push(await objects.streamData(s));parts.push(textBytes('\n'));}}
      const size=parts.reduce((n,x)=>n+x.length,0),joined=new Uint8Array(size);let at=0;for(const part of parts){joined.set(part,at);at+=part.length;}
      const collect={},resources=await resourceCopy(page.Resources,null,collect,moved);
      for(const [key,table] of Object.entries(collect))resources[key]={...table,...(await resolve(resources[key])||{})};
      const stripped=stripText(joined,moved.get(0)||null),framed=new Uint8Array(stripped.length+5);
      framed.set(textBytes('q\n'));framed.set(stripped,2);framed.set(textBytes('\nQ\n'),stripped.length+2);
      const number=allocate();
      baseObjects.set(number,await packStream(framed));
      const fonts=await objects.pageFonts(index),fontRefs={};
      for(const f of fonts)fontRefs['f'+(f.ref!=null?f.ref:String(f.dict?.BaseFont?.name||'').replace(/[^A-Za-z0-9]/gu,'').toLowerCase())]=f.ref!=null?new Ref(f.ref):f.dict;
      const base={page,number,resources,fontRefs};
      pageBases.set(memo,base);
      return base;
    }
    // Runs of one font and one graphics state go together; each glyph keeps its own place.
    function drawOperations(page,base,used,fontPrefix='TT'){
      if(page.layers){
        const lines=[],pageFonts={};
        for(const [index,layer] of page.layers.entries()){
          const draw=drawOperations(layer,base,used,'TT'+index+'_');
          Object.assign(pageFonts,draw.pageFonts);
          if(layer.toPage)lines.push('q '+layer.toPage.map(num).join(' ')+' cm',draw.text,'Q');
          else lines.push(draw.text);
        }
        return {text:lines.join('\n')+'\n',pageFonts};
      }
      const lines=[],names=new Map(),pageFonts={};
      const nameOf=id=>{if(!names.has(id)){const n=fontPrefix+names.size;names.set(id,n);const ref=base.fontRefs[id];if(ref)pageFonts[n]=ref;}return names.get(id);};
      let last=null;
      const emit=(state,font,size,matrix,code)=>{
        const key=state+'\0'+font;
        if(last!==key){
          if(last!==null)lines.push('ET Q');
          lines.push(`q ${state} BT`);
          last=key;lastSize=null;
        }
        if(lastSize!==size){lines.push(`/${font} ${num(size)} Tf`);lastSize=size;}
        lines.push(`${matrix} Tm <${code}> Tj`);
      };
      let lastSize=null;
      const source=c=>{
        if(c.cid==null)return;
        const info=fontInfo[c.style.font];
        if(!info||!base.fontRefs[c.style.font])return;
        const size=c.style.size/(info.emHeight||1);
        const matrix=c.vertical&&!page.turn?`0 1 -1 0 ${num(c.box.x2)} ${num(c.box.y)}`:`1 0 0 1 ${num(c.box.x)} ${num(c.box.y)}`;
        emit(c.style.state||'',nameOf(c.style.font),size,matrix,hex(c.cid,info.composite?4:2));
      };
      for(const c of page.chars)source(c);
      for(const p of page.paragraphs){
        for(const u of p.placed||[]){
          if(u.formula){
            for(const c of u.formula.chars)source(c);
            for(const {curve,matrix} of u.formula.moved||[]){
              if(last!==null){lines.push('ET Q');last=null;}
              const paint=(curve.fill?(curve.evenodd?'f*':'f'):'')+(curve.stroke?(curve.fill?' ':'')+'S':'');
              if(curve.fill&&curve.stroke)lines.push(`q ${matrix.map(num).join(' ')} cm ${curve.ctm.map(num).join(' ')} cm ${curve.state} ${curve.path} ${curve.evenodd?'B*':'B'} Q`);
              else lines.push(`q ${matrix.map(num).join(' ')} cm ${curve.ctm.map(num).join(' ')} cm ${curve.state} ${curve.path} ${paint} Q`);
            }
            continue;
          }
          if(u.char){source(u.char);continue;}
          if(!used.has(u.font.id))used.set(u.font.id,new Set());
          const gid=u.font.font.glyphOf(u.unicode.codePointAt(0));
          used.get(u.font.id).add(gid);
          (used.get(u.font.id).chars||=new Map()).set(gid,u.unicode);
          emit(u.style.state||'','TN'+u.font.id.replace(/[^A-Za-z0-9]/gu,''),u.fontSize,`1 0 0 1 ${num(u.x)} ${num(u.y)}`,hex(gid,4));
        }
      }
      if(last!==null)lines.push('ET Q');
      return {text:lines.join('\n')+'\n',pageFonts};
    }
    function toUnicode(chars){
      const entries=[...chars].sort((a,b)=>a[0]-b[0]),lines=['/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def /CMapName /Adobe-Identity-UCS def /CMapType 2 def 1 begincodespacerange <0000> <FFFF> endcodespacerange'];
      for(let i=0;i<entries.length;i+=100){
        const part=entries.slice(i,i+100);
        lines.push(`${part.length} beginbfchar`);
        for(const [gid,ch] of part){let h='';for(let k=0;k<ch.length;k++)h+=hex(ch.charCodeAt(k),4);lines.push(`<${hex(gid,4)}> <${h}>`);}
        lines.push('endbfchar');
      }
      lines.push('endcmap CMapName currentdict /CMap defineresource pop end end');
      return textBytes(lines.join('\n'));
    }
    async function embedFont(id,gids,objectsOut){
      const entry=book.get(id),font=entry.font,facts=entry.facts,scale=1000/font.unitsPerEm;
      const subset=global.TwinTextTypesetFonts.subsetFont(font,gids);
      const fileNumber=allocate(),descriptor=allocate(),cid=allocate(),type0=allocate(),unicode=allocate();
      objectsOut.set(fileNumber,await packStream(subset,{Length1:subset.length}));
      objectsOut.set(unicode,await packStream(toUnicode(gids.chars||new Map())));
      const name=new Name('TTSUBS+'+facts.font_name.replace(/\s+/gu,''));
      objectsOut.set(descriptor,{dict:{Type:new Name('FontDescriptor'),FontName:name,Flags:facts.serif?6:4,FontBBox:[-1000,-1000,2000,2000],ItalicAngle:facts.italic?-12:0,Ascent:facts.ascent,Descent:facts.descent,CapHeight:facts.ascent,StemV:80,FontFile2:new Ref(fileNumber)}});
      const widths=[];for(const gid of [...gids].sort((a,b)=>a-b))widths.push(gid,[Math.round(font.advanceOf(gid)*scale)]);
      objectsOut.set(cid,{dict:{Type:new Name('Font'),Subtype:new Name('CIDFontType2'),BaseFont:name,CIDSystemInfo:{Registry:{bytes:textBytes('Adobe')},Ordering:{bytes:textBytes('Identity')},Supplement:0},FontDescriptor:new Ref(descriptor),CIDToGIDMap:new Name('Identity'),DW:1000,W:widths}});
      objectsOut.set(type0,{dict:{Type:new Name('Font'),Subtype:new Name('Type0'),BaseFont:name,Encoding:new Name('Identity-H'),DescendantFonts:[new Ref(cid)],ToUnicode:new Ref(unicode)}});
      return new Ref(type0);
    }
    const packedText=new Map();
    // The file with the given pages replaced. Pages not given stay exactly as they were.
    async function build(pages){
      const out=new Map(),used=new Map(),jobs=[];
      for(const page of pages){
        const moved=new Map();
        for(const p of page.paragraphs)for(const u of p.placed||[])for(const {curve} of u.formula?.moved||[]){
          if(!moved.has(curve.scope))moved.set(curve.scope,new Set());
          moved.get(curve.scope).add(curve.ordinal);
        }
        const base=await pageBase(page.pageIndex,moved),draw=drawOperations(page,base,used);
        jobs.push({page,base,draw});
      }
      const embedded={};
      for(const [id,gids] of used)embedded['TN'+id.replace(/[^A-Za-z0-9]/gu,'')]=await embedFont(id,gids,out);
      for(const {page,base,draw} of jobs){
        let packed=packedText.get(page.pageIndex);
        if(!packed||packed.text!==draw.text){packed={text:draw.text,stream:await packStream(textBytes(draw.text))};packedText.set(page.pageIndex,packed);}
        const number=allocate();out.set(number,packed.stream);
        const original=await resolve(base.resources.Font)||{};
        const resources={...base.resources,Font:{...original,...draw.pageFonts}};
        for(const [name,ref] of Object.entries(embedded))if(draw.text.includes('/'+name+' '))resources.Font[name]=ref;
        const dict={...base.page,Contents:[new Ref(base.number),new Ref(number)],Resources:resources};
        const own=base.page.__number;delete dict.__number;
        out.set(own,{dict});
      }
      return assemble(new Map([...baseObjects,...out]));
    }
    async function assemble(all){
      const parts=[bytes,textBytes('\n')],offsets=new Map();let at=bytes.length+1;
      const push=p=>{parts.push(p);at+=p.length;};
      for(const [number,obj] of [...all].sort((a,b)=>a[0]-b[0])){
        offsets.set(number,at);
        let data=obj.data;
        if(data&&objects.seal)data=await objects.seal(data,number,0);
        if(data){
          push(textBytes(`${number} 0 obj\n${serialize({...obj.dict,Length:data.length})}\nstream\n`));push(data);push(textBytes('\nendstream\nendobj\n'));
        }else push(textBytes(`${number} 0 obj\n${serialize(obj.dict)}\nendobj\n`));
      }
      const xrefAt=at,size=Math.max(nextNumber,...offsets.keys())+1,t=objects.trailer,keep={};
      for(const key of ['Root','Info','ID','Encrypt'])if(t[key]!==undefined)keep[key]=t[key];
      const prev=objects.startXref;
      const numbers=[...offsets.keys()].sort((a,b)=>a-b);
      if(objects.usesXrefStream){
        const number=size;offsets.set(number,xrefAt);numbers.push(number);
        const table=new Uint8Array(numbers.length*7),view=new DataView(table.buffer);
        numbers.forEach((n,i)=>{table[i*7]=1;view.setUint32(i*7+1,offsets.get(n));view.setUint16(i*7+5,0);});
        const index=[];for(const n of numbers){if(index.length&&index.at(-2)+index.at(-1)===n)index[index.length-1]++;else index.push(n,1);}
        const dict={...keep,Type:new Name('XRef'),Size:number+1,W:[1,4,2],Index:index,Length:table.length};if(prev!=null)dict.Prev=prev;
        push(textBytes(`${number} 0 obj\n${serialize(dict)}\nstream\n`));push(table);push(textBytes('\nendstream\nendobj\n'));
      }else{
        const lines=['xref'];
        for(let i=0;i<numbers.length;){
          let j=i;while(j+1<numbers.length&&numbers[j+1]===numbers[j]+1)j++;
          lines.push(`${numbers[i]} ${j-i+1}`);
          for(let k=i;k<=j;k++)lines.push(String(offsets.get(numbers[k])).padStart(10,'0')+' 00000 n ');
          i=j+1;
        }
        const dict={...keep,Size:size};if(prev!=null)dict.Prev=prev;
        lines.push('trailer',serialize(dict),'');
        push(textBytes(lines.join('\n')));
      }
      push(textBytes(`startxref\n${xrefAt}\n%%EOF\n`));
      const whole=new Uint8Array(at);let pos=0;for(const part of parts){whole.set(part,pos);pos+=part.length;}
      return whole;
    }
    return {build};
  }
  global.TwinTextTypesetWriter=Object.freeze({createWriter,stripText});
})(this);
