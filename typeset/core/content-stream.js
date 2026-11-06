// Typeset engine: a page's content stream read as BabelDOC reads it, so that every coordinate keeps the file's own precision.
// Ported from BabelDOC 0.6.4 new_parser/{tokenizer,interpreter,state,text_positioning,native_text} and awlt_char.
// Copyright (C) 2026 TwinText; BabelDOC by its authors. SPDX-License-Identifier: AGPL-3.0-only
(function(global){
  'use strict';
  // Self-contained: its source runs in the reader's window as well.
  async function interpretPage(objects,pageIndex,fontFor){
    const WHITE=new Set([0,9,10,12,13,32]),DELIM=new Set([40,41,60,62,91,93,123,125,47,37]);
    const KEYWORDS=new Set(['q','Q','cm','g','G','rg','RG','k','K','cs','CS','ri','gs','sc','SC','scn','SCN','w','i','J','j','M','d','m','l','c','v','y','h','re','S','s','f','F','f*','B','B*','b','b*','n','W','W*','sh','MP','DP','BMC','BDC','EMC','BX','EX','Do','BT','ET','Tf','Tc','Tw','Tz','TL','Ts','Tr','Tm','Td','TD','T*','Tj','TJ',"'",'"','BI','ID','EI','d0','d1']);
    const SPLIT=[...KEYWORDS].sort((a,b)=>b.length-a.length);
    class Name{constructor(v){this.value=v;}}
    class Key{constructor(v){this.value=v;}}
    class Str{constructor(b){this.bytes=b;}}
    const isWord=b=>!WHITE.has(b)&&!DELIM.has(b);
    function* tokens(data){
      let p=0;const pending=[];
      const latin=(a,b)=>{let s='';for(let i=a;i<b;i++)s+=String.fromCharCode(data[i]);return s;};
      const skip=()=>{for(;;){while(p<data.length&&WHITE.has(data[p]))p++;if(data[p]===37){while(p<data.length&&data[p]!==10&&data[p]!==13)p++;continue;}return;}};
      const number=()=>{
        const start=p;let q=p;
        if(data[q]===43||data[q]===45)q++;
        while(data[q]>=48&&data[q]<=57)q++;
        if(data[q]===46){q++;while(data[q]>=48&&data[q]<=57)q++;}
        if(q===start)return undefined;
        const raw=latin(start,q);p=q;
        if(['+','-','.','+.','-.'].includes(raw))return null;
        return Number(raw);
      };
      const split=raw=>{
        if(KEYWORDS.has(raw)||!/[0-9]/.test(raw))return null;
        const out=[];let at=0;
        while(at<raw.length){
          const m=/^[-+]?\d*\.?\d*/.exec(raw.slice(at))[0];
          if(m&&/\d/.test(m)){out.push(Number(m));at+=m.length;continue;}
          const key=SPLIT.find(k=>raw.startsWith(k,at));
          if(!key)return null;
          out.push(new Key(key));at+=key.length;
        }
        return out.length>1?out:null;
      };
      const keyword=()=>{
        const start=p;while(p<data.length&&isWord(data[p]))p++;
        if(p===start){p++;return next();}
        const raw=latin(start,p);
        if(raw==='true')return true;if(raw==='false')return false;if(raw==='null')return null;
        const parts=split(raw);
        if(parts){pending.push(...parts.slice(1));return parts[0];}
        return new Key(raw);
      };
      const next=()=>{
        if(pending.length)return pending.shift();
        for(;;){
          skip();
          if(p>=data.length)return undefined;
          const c=data[p];
          if(c===47){p++;let s='';while(p<data.length&&isWord(data[p])){if(data[p]===35&&p+2<data.length&&/^[0-9a-fA-F]{2}$/.test(String.fromCharCode(data[p+1],data[p+2]))){s+=String.fromCharCode(parseInt(String.fromCharCode(data[p+1],data[p+2]),16));p+=3;continue;}s+=String.fromCharCode(data[p++]);}return new Name(s);}
          if(c===40){
            p++;let depth=1;const out=[];
            while(p<data.length){
              const b=data[p++];
              if(b===92){
                if(p>=data.length)break;
                const e=data[p++],map={110:10,114:13,116:9,98:8,102:12,40:40,41:41,92:92};
                if(e in map){out.push(map[e]);continue;}
                if(e===13||e===10){if(e===13&&data[p]===10)p++;continue;}
                if(e>=48&&e<=55){let v=e-48;for(let k=0;k<2&&data[p]>=48&&data[p]<=55;k++)v=v*8+data[p++]-48;out.push(v&255);continue;}
                out.push(e);continue;
              }
              if(b===40){depth++;out.push(b);continue;}
              if(b===41){if(--depth===0)return new Str(Uint8Array.from(out));out.push(b);continue;}
              out.push(b);
            }
            throw new Error('Unterminated literal string');
          }
          if(c===60){
            if(data[p+1]===60){
              p+=2;const dict={};
              for(;;){skip();if(data[p]===62&&data[p+1]===62){p+=2;return dict;}if(p>=data.length)return dict;const k=next();const v=next();if(k instanceof Name)dict[k.value]=v;}
            }
            p++;const hex=[];
            while(p<data.length&&data[p]!==62){if(!WHITE.has(data[p]))hex.push(String.fromCharCode(data[p]));p++;}
            p++;let raw=hex.join('');if(raw.length%2)raw+='0';
            const out=new Uint8Array(raw.length/2);for(let i=0;i<out.length;i++)out[i]=parseInt(raw.substr(i*2,2),16);
            return new Str(out);
          }
          if(c===91){
            p++;const out=[];
            for(;;){skip();if(data[p]===93){p++;return out;}if(p>=data.length)return out;const v=next();if(v===undefined)return out;if(!(v instanceof Key))out.push(v);}
          }
          if(c===43||c===45||c===46||c>=48&&c<=57){
            const v=number();
            if(v===null)return next();
            if(v!==undefined)return v;
            return keyword();
          }
          if(c===93||c===62||c===125||c===123||c===41){p++;continue;}
          return keyword();
        }
      };
      const EI_TAIL=new Set(['Q','q','cm','Do','BT','ET','W','W*','S','s','f','F','f*','B','B*','b','b*','n','BI','ID','EMC','BDC','Tj','TJ','Td','TD','Tm','Tf','TL','Tc','Tw','Tz','Ts','Tr','gs']);
      for(;;){
        const t=next();
        if(t===undefined)return;
        if(t instanceof Key&&t.value==='BI'){
          for(;;){const k=next();if(k===undefined)return;if(k instanceof Key&&k.value==='ID')break;}
          let at=p;
          for(;;){
            at=data.indexOf(69,at);
            if(at<0){p=data.length;break;}
            if(data[at+1]===73&&(at===0||!isWord(data[at-1]))&&(at+2>=data.length||!isWord(data[at+2]))){
              let q=at+2;while(q<data.length&&WHITE.has(data[q]))q++;
              let e=q;while(e<data.length&&isWord(data[e]))e++;
              const tail=latin(q,e);
              if(q>=data.length||data[q]===47||EI_TAIL.has(tail)){p=at+2;break;}
            }
            at++;
          }
          yield new Key('INLINE_IMAGE');
          continue;
        }
        yield t;
      }
    }
    const multiply=(l,r)=>[r[0]*l[0]+r[2]*l[1],r[1]*l[0]+r[3]*l[1],r[0]*l[2]+r[2]*l[3],r[1]*l[2]+r[3]*l[3],r[0]*l[4]+r[2]*l[5]+r[4],r[1]*l[4]+r[3]*l[5]+r[5]];
    const moved=(m,x,y)=>[m[0],m[1],m[2],m[3],x*m[0]+y*m[2]+m[4],x*m[1]+y*m[3]+m[5]];
    const apply=(m,x,y)=>[m[0]*x+m[2]*y+m[4],m[1]*x+m[3]*y+m[5]];
    const SPACES=/^[    -​  ⁠　\t]+$/u;
    const REPLACED=new Set(['sc','SC','scn','SCN','g','G','rg','RG','k','K','cs','CS','ri','w','J','j','M','i','d']);
    const MAX_BUFFER=2048,MAX_DEPTH=64;
    const chars=[],fonts={},curves=[];let renderOrder=0,xobjectSerial=0;
    const page=await objects.pageDict(pageIndex);
    if(!page)throw new Error('No such page');
    const contents=await objects.resolve(page.Contents),streams=Array.isArray(contents)?contents:contents?[contents]:[];
    const parts=[];
    for(const entry of streams){const s=await objects.resolve(entry);if(s instanceof objects.Stream)parts.push(await objects.streamData(s));}
    const size=parts.reduce((n,x)=>n+x.length+1,0),joined=new Uint8Array(size);let at=0;
    for(const part of parts){joined.set(part,at);at+=part.length;joined[at++]=10;}
    // Where painting can show at all: a form's BBox and rectangular clips, as a box on the page. BabelDOC does not read it, so the stages above only use it if asked.
    const boundsOf=points=>({x:Math.min(...points.map(p=>p[0])),y:Math.min(...points.map(p=>p[1])),x2:Math.max(...points.map(p=>p[0])),y2:Math.max(...points.map(p=>p[1]))});
    const within=(a,b)=>!a?b:!b?a:{x:Math.max(a.x,b.x),y:Math.max(a.y,b.y),x2:Math.min(a.x2,b.x2),y2:Math.min(a.y2,b.y2)};
    const outside=(clip,x0,y0,x1,y1)=>Boolean(clip&&(x1<clip.x-.5||x0>clip.x2+.5||y1<clip.y-.5||y0>clip.y2+.5));
    const scopeRun=async(data,resources,ctm,xobj,depth,seen,formNumber=0,clip=null)=>{
      const items=[];
      const flush=()=>{for(const item of items)if(item)chars.push(item);items.length=0;};
      const buffer=item=>{items.push(item);if(items.length>=MAX_BUFFER)flush();};
      const res=await objects.resolve(resources);
      const fontDicts=res?await objects.resolve(res.Font):null,xobjects=res?await objects.resolve(res.XObject):null;
      let g={ctm,clip},t={font:null,size:0,charSpacing:0,wordSpacing:0,hscale:100,leading:0,rise:0,mode:0},o={inText:false,matrix:[1,0,0,1,0,0],lineX:0,lineY:0};
      const stack=[];
      let state=[],stateStack=[],path=false,pathFromMove=false,args=[],pathPoints=[],pathText=[],pathOrdinal=0;
      const stateKey=()=>state.map(e=>e[1]+' '+e[0]).join(' ');
      const setState=(op,value)=>{
        // A replaced operator moves to the end, as in BabelDOC: black after a blue link is not the black before it.
        state=REPLACED.has(op)?state.filter(e=>e[0]!==op):[...state];
        state.push([op,value]);
      };
      const argText=list=>list.map(v=>v instanceof Name?'/'+v.value:Array.isArray(v)?'['+v.join(' ')+']':String(v)).join(' ');
      const need=(operands,n)=>{
        if(operands.length<n)return false;
        if(operands.length>n){if(n===0){args.push(...operands);operands.length=0;}else{args.push(...operands.slice(0,-n));operands.splice(0,operands.length-n);}}
        return true;
      };
      const show=segments=>{
        const font=t.font?fontFor(t.font):null;
        const scaling=t.hscale*.01,charspace=t.charSpacing*scaling,wordspace=font&&font.multibyte?0:t.wordSpacing*scaling,dxscale=.001*t.size*scaling;
        let x=o.lineX,y=o.lineY,need=false;
        if(!font)return;
        const vertical=font.vertical,matrix=multiply(o.matrix,g.ctm);
        for(const seg of segments){
          if(typeof seg==='number'){if(vertical)y-=seg*dxscale;else x-=seg*dxscale;need=true;continue;}
          for(const cid of font.decode(seg)){
            if(need){if(vertical)y+=charspace;else x+=charspace;}
            const width=font.charWidth(cid),advance=width*t.size*scaling,m=moved(matrix,x,y);
            if(t.mode!==7){
              let ll,ur;
              if(vertical){
                const disp=font.charDisp(cid),vx=disp[0]==null?t.size*.5:disp[0]*t.size*.001,vy=(1000-disp[1])*t.size*.001;
                ll=[-vx,vy+t.rise+advance];ur=[-vx+t.size,vy+t.rise];
              }else{ll=[0,t.rise];ur=[advance,t.rise+t.size];}
              let [x0,y0]=apply(m,ll[0],ll[1]),[x1,y1]=apply(m,ur[0],ur[1]);
              if(x1<x0)[x0,x1]=[x1,x0];
              if(y1<y0)[y0,y1]=[y1,y0];
              const angle=Math.atan2(m[1],m[0])*180/Math.PI;
              const turn=Math.abs(Math.abs(angle)-90)<=.1?Math.sign(angle)*90:0;
              const measured=vertical||turn?x1-x0:y1-y0,fontSize=measured*(font.emHeight||1);
              renderOrder++;
              if(fontSize!==0&&(Math.abs(angle)<=.1||turn)){
                let text=font.textOf(cid);
                if(SPACES.test(text))text=' ';
                const descent=(font.descentOnPage(pageIndex)||0)*fontSize;
                let visual=turn?[x0-Math.sign(turn)*descent,y0,x1-Math.sign(turn)*descent,y1]:[x0,y0+descent,x1,y1+descent];
                const box=text!==' '?font.outline(cid):null;
                if(box){
                  const [left,bottom,right,top]=box.map(value=>value*fontSize);
                  let v;
                  if(turn===90)v=[x1-top,y0+left,x1-bottom,y0+right];
                  else if(turn===-90)v=[x0+bottom,y1-right,x0+top,y1-left];
                  else v=[x0+left,y0+bottom,x0+right,y0+top];
                  if((v[2]-v[0])*(v[3]-v[1])>1)visual=v;
                }
                fonts[font.id]=font.info;
                buffer([text,x0,y0,x1,y1,visual[0],visual[1],visual[2],visual[3],fontSize,font.id,cid,Boolean(vertical&&turn),advance,xobj,renderOrder,stateKey(),outside(g.clip,x0,y0,x1,y1),turn]);
              }
            }
            if(vertical){y+=advance;if(cid===32&&wordspace)y+=wordspace;}
            else{x+=advance;if(cid===32&&wordspace)x+=wordspace;}
            need=true;
          }
        }
        o.lineX=x;o.lineY=y;
      };
      const asBytes=v=>v instanceof Str?v.bytes:null;
      // A path that does not begin with a move makes no curve, and takes no place in the buffer.
      const paint=(stroke,fill,evenodd)=>{
        if(path&&pathFromMove){
          buffer(null);
          const ordinal=pathOrdinal++,pts=pathPoints.map(([x,y])=>apply(g.ctm,x,y));
          if(pts.length)curves.push({scope:formNumber,xobj,ordinal,ctm:g.ctm,state:stateKey(),stroke,fill,evenodd,path:pathText.length<=64?pathText.join(' '):null,
            box:boundsOf(pts),hidden:(b=>outside(g.clip,b.x,b.y,b.x2,b.y2))(boundsOf(pts))});
        }
        path=false;pathPoints=[];pathText=[];
      };
      for(const token of tokens(data)){
        if(!(token instanceof Key)){args.push(token);continue;}
        const op=token.value,a=args;args=[];
        switch(op){
          case 'q':need(a,0);stack.push([{...g},{...t},{...o}]);stateStack.push(state);break;
          case 'Q':need(a,0);if(stack.length)[g,t,o]=stack.pop();state=stateStack.length?stateStack.pop():[];break;
          case 'cm':if(need(a,6))g={...g,ctm:multiply(a,g.ctm)};break;
          case 'g':case 'G':case 'rg':case 'RG':case 'k':case 'K':case 'sc':case 'SC':case 'scn':case 'SCN':setState(op,argText(a));break;
          case 'cs':case 'CS':case 'ri':case 'gs':case 'w':case 'i':case 'J':case 'j':case 'M':if(need(a,1))setState(op,argText(a));break;
          case 'd':if(need(a,2))setState(op,argText(a));break;
          case 'm':case 'l':case 'c':case 'v':case 'y':case 're':{
            const nums=a.filter(v=>typeof v==='number'),n={m:2,l:2,c:6,v:4,y:4,re:4}[op];
            if(nums.length>=n){
              if(!path){pathFromMove=op==='m'||op==='re';pathPoints=[];pathText=[];}
              path=true;
              const v=nums.slice(-n);
              if(op==='re'){pathPoints.push([v[0],v[1]],[v[0]+v[2],v[1]],[v[0]+v[2],v[1]+v[3]],[v[0],v[1]+v[3]],[v[0],v[1]]);}
              else pathPoints.push(v.slice(-2));
              pathText.push(v.join(' ')+' '+op);
            }
            break;
          }
          case 'h':need(a,0);if(!path){pathFromMove=false;pathPoints=[];pathText=[];}path=true;if(pathPoints.length)pathPoints.push(pathPoints[0]);pathText.push('h');break;
          case 'S':need(a,0);paint(true,false,false);break;
          case 'f':case 'F':need(a,0);paint(false,true,false);break;
          case 'f*':need(a,0);paint(false,true,true);break;
          case 'B':need(a,0);paint(true,true,false);break;
          case 'B*':need(a,0);paint(true,true,true);break;
          case 's':need(a,0);if(!path){pathFromMove=false;pathPoints=[];pathText=[];}path=true;pathText.push('h');paint(true,false,false);break;
          case 'b':case 'b*':need(a,0);if(!path){pathFromMove=false;pathPoints=[];pathText=[];}path=true;pathText.push('h');paint(true,true,op==='b*');break;
          case 'n':need(a,0);path=false;pathPoints=[];pathText=[];break;
          case 'W':case 'W*':need(a,0);if(pathPoints.length)g={...g,clip:within(g.clip,boundsOf(pathPoints.map(([x,y])=>apply(g.ctm,x,y))))};break;
          case 'sh':if(need(a,1))buffer(null);break;
          case 'BT':need(a,0);o={inText:true,matrix:[1,0,0,1,0,0],lineX:0,lineY:0};break;
          case 'ET':need(a,0);o={inText:false,matrix:[1,0,0,1,0,0],lineX:0,lineY:0};break;
          case 'Tf':if(need(a,2)&&a[0] instanceof Name){t.font=fontDicts?fontDicts[a[0].value]:null;t.size=a[1];}break;
          case 'Tc':if(need(a,1))t.charSpacing=a[0];break;
          case 'Tw':if(need(a,1))t.wordSpacing=a[0];break;
          case 'Tz':if(need(a,1))t.hscale=a[0];break;
          case 'TL':if(need(a,1))t.leading=-a[0];break;
          case 'Ts':if(need(a,1))t.rise=a[0];break;
          case 'Tr':if(need(a,1))t.mode=Math.trunc(a[0]);break;
          case 'Tm':if(need(a,6)){o.matrix=a.slice();o.lineX=0;o.lineY=0;}break;
          case 'Td':if(need(a,2)){o.matrix=moved(o.matrix,a[0],a[1]);o.lineX=0;o.lineY=0;}break;
          case 'TD':if(need(a,2)){t.leading=a[1];o.matrix=moved(o.matrix,a[0],a[1]);o.lineX=0;o.lineY=0;}break;
          case 'T*':need(a,0);o.matrix=[o.matrix[0],o.matrix[1],o.matrix[2],o.matrix[3],t.leading*o.matrix[2]+o.matrix[4],t.leading*o.matrix[3]+o.matrix[5]];o.lineX=0;o.lineY=0;break;
          case 'Tj':if(need(a,1)&&asBytes(a[0]))await prepared(t.font).then(()=>show([a[0].bytes]));break;
          case 'TJ':if(need(a,1)&&Array.isArray(a[0]))await prepared(t.font).then(()=>show(a[0].map(v=>v instanceof Str?v.bytes:v).filter(v=>typeof v==='number'||v instanceof Uint8Array)));break;
          case "'":if(need(a,1)&&asBytes(a[0])){o.matrix=[o.matrix[0],o.matrix[1],o.matrix[2],o.matrix[3],t.leading*o.matrix[2]+o.matrix[4],t.leading*o.matrix[3]+o.matrix[5]];o.lineX=0;o.lineY=0;await prepared(t.font);show([a[0].bytes]);}break;
          case '"':if(need(a,3)&&asBytes(a[2])){t.wordSpacing=a[0];t.charSpacing=a[1];o.matrix=[o.matrix[0],o.matrix[1],o.matrix[2],o.matrix[3],t.leading*o.matrix[2]+o.matrix[4],t.leading*o.matrix[3]+o.matrix[5]];o.lineX=0;o.lineY=0;await prepared(t.font);show([a[2].bytes]);}break;
          case 'Do':{
            if(!need(a,1)||!(a[0] instanceof Name)||!xobjects)break;
            const ref=xobjects[a[0].value],form=await objects.resolve(ref);
            if(!(form instanceof objects.Stream))break;
            if((await objects.resolve(form.dict.Subtype))?.name!=='Form')break;
            const id=form.num;
            if(seen.includes(id)||depth>=MAX_DEPTH)break;
            const raw=await objects.resolve(form.dict.Matrix),matrix=raw?await Promise.all(raw.map(objects.resolve)):[1,0,0,1,0,0];
            const place=multiply(matrix,g.ctm),rawBox=await objects.resolve(form.dict.BBox),bbox=Array.isArray(rawBox)&&rawBox.length===4?await Promise.all(rawBox.map(objects.resolve)):null;
            const shown=bbox&&bbox.every(v=>typeof v==='number')?within(g.clip,boundsOf([[bbox[0],bbox[1]],[bbox[2],bbox[1]],[bbox[2],bbox[3]],[bbox[0],bbox[3]]].map(([x,y])=>apply(place,x,y)))):g.clip;
            await scopeRun(await objects.streamData(form),form.dict.Resources!==undefined?form.dict.Resources:resources,place,++xobjectSerial,depth+1,[...seen,id],id,shown);
            break;
          }
          default:break;
        }
      }
      flush();
    };
    const prepared=ref=>ref?fontFor.prepare(ref):Promise.resolve();
    await scopeRun(joined,page.Resources,[1,0,0,1,0,0],0,0,[]);
    return {chars,fonts,curves};
  }
  // A font as the interpreter uses it, from BabelDOC's rules for simple, Type3 and CID fonts.
  async function fontRuntime(objects,dict,spec,data,helpers){
    const {resolve}=objects;
    const subtype=(await resolve(dict.Subtype))?.name;
    let target=dict,composite=false;
    if(subtype==='Type0'){const list=await resolve(dict.DescendantFonts);target=await resolve(Array.isArray(list)?list[0]:null)||dict;composite=true;}
    const descriptor=await resolve(target.FontDescriptor);
    const nameOf=v=>v?.name||(v?.bytes?String.fromCharCode(...v.bytes):typeof v==='string'?v:'');
    const fontName=nameOf(await resolve(descriptor?.FontName))||nameOf(await resolve(target.BaseFont))||'unknown';
    const num=async(v,d=0)=>{const n=await resolve(v);return Number.isFinite(n)?n:d;};
    const flags=await num(descriptor?.Flags,0),weight=await num(descriptor?.FontWeight,0),angle=await num(descriptor?.ItalicAngle,0),stem=fontName.split('+').at(-1);
    const bold=Boolean(flags&262144)||weight>=700||/bold|black|heavy|-medi$|^cmbx|^cmmib|^cmbsy/iu.test(stem),italic=Boolean(flags&64)||angle!==0||/italic|oblique/iu.test(stem);
    const runtime={...helpers,id:helpers.id,info:{id:helpers.id,name:fontName,bold,italic,serif:Boolean(flags&2),composite,emHeight:spec.type3?.emHeight||0},multibyte:composite,vertical:false,emHeight:spec.type3?.emHeight||0};
    if(composite){
      const encoding=await resolve(dict.Encoding);
      let decode;const name=encoding?.name;
      if(name==='Identity-H'||name==='Identity-V'||name==='DLIdent-H'||name==='DLIdent-V'){
        decode=b=>{const out=[];for(let i=0;i+1<b.length;i+=2)out.push(b[i]*256+b[i+1]);return out;};
      }else if(name==='OneByteIdentityH'||name==='OneByteIdentityV')decode=b=>Array.from(b);
      else throw new Error('Predefined CMap: '+(name||'stream'));
      runtime.decode=decode;runtime.vertical=/-V$|V$/.test(name||'')&&name!=='OneByteIdentityH';
      const widths=new Map(),w=await resolve(target.W);
      if(Array.isArray(w)){
        const items=await Promise.all(w.map(resolve));let range=[];
        for(const value of items){
          if(Array.isArray(value)){
            if(range.length){const first=range.at(-1);const list=await Promise.all(value.map(resolve));list.forEach((v,i)=>widths.set(first+i,v));range=[];}
          }else if(typeof value==='number'){
            range.push(value);
            if(range.length===3){const [a,b,v]=range;if(Number.isInteger(a)&&Number.isInteger(b))for(let i=a;i<=b;i++)widths.set(i,v);range=[];}
          }
        }
      }
      const dw=await num(target.DW,1000);
      if(runtime.vertical){
        const disps=new Map(),w2=new Map(),source=await resolve(target.W2);
        if(Array.isArray(source)){
          const items=await Promise.all(source.map(resolve));let range=[];
          for(const value of items){
            if(Array.isArray(value)){
              if(range.length){const first=range.at(-1);const list=await Promise.all(value.map(resolve));for(let i=0;i+3<=list.length;i+=3){w2.set(first+i/3,list[i]);disps.set(first+i/3,[list[i+1],list[i+2]]);}range=[];}
            }else if(typeof value==='number'){
              range.push(value);
              if(range.length===5){const [a,b,v,x,y]=range;for(let i=a;i<=b;i++){w2.set(i,v);disps.set(i,[x,y]);}range=[];}
            }
          }
        }
        const d2=await resolve(target.DW2),vy=Array.isArray(d2)?await resolve(d2[0]):880,wd=Array.isArray(d2)?await resolve(d2[1]):-1000;
        runtime.charWidth=cid=>(w2.has(cid)?w2.get(cid):wd)*.001;
        runtime.charDisp=cid=>disps.get(cid)||[null,vy];
      }else{
        runtime.charWidth=cid=>(widths.has(cid)?widths.get(cid):dw)*.001;
        runtime.charDisp=()=>[null,0];
      }
      runtime.textOf=cid=>{
        if(spec.toUnicode)return spec.toUnicode.has(cid)?spec.toUnicode.get(cid):`(cid:${cid})`;
        return helpers.fallbackText(cid);
      };
      return runtime;
    }
    runtime.decode=b=>Array.from(b);runtime.charDisp=()=>[null,0];
    runtime.textOf=cid=>spec.toUnicode?.has(cid)?spec.toUnicode.get(cid):spec.encoding?.has(cid)?spec.encoding.get(cid):`(cid:${cid})`;
    const first=await num(dict.FirstChar,0),list=await resolve(dict.Widths),widths=new Map();
    if(Array.isArray(list)){const v=await Promise.all(list.map(resolve));v.forEach((w,i)=>{if(w!=null)widths.set(first+i,w);});}
    else for(let i=0;i<256;i++)widths.set(first+i,0);
    let missing=await num(descriptor?.MissingWidth,0);
    if(subtype==='Type3'){
      const matrix=await Promise.all((await resolve(dict.FontMatrix)).map(resolve)),hscale=matrix[0]+matrix[2];
      runtime.charWidth=cid=>{
        if(widths.has(cid))return widths.get(cid)*hscale;
        const text=runtime.textOf(cid);
        return missing*hscale;
      };
      return runtime;
    }
    const metrics=data.METRICS[fontName];
    if(metrics&&(subtype==='Type1'||subtype==='MMType1'||subtype==='TrueType')){
      missing=metrics.missing||0;
      runtime.info.name=metrics.name||fontName;
      runtime.charWidth=cid=>{const w=metrics.widths[runtime.textOf(cid)];return (w!==undefined?w:missing)*.001;};
      return runtime;
    }
    runtime.charWidth=cid=>(widths.has(cid)?widths.get(cid):missing)*.001;
    return runtime;
  }
  global.TwinTextTypesetContent=Object.freeze({interpretPage,fontRuntime});
})(this);
