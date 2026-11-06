// Typeset engine: the PDF file's own objects, for what PDF.js does not hand over (font encodings and ToUnicode as written).
// Rules ported from BabelDOC 0.6.4 new_parser/active_direct_font_backend and runtime/{font_encoding,to_unicode_parser,font_data}_runtime.
// Copyright (C) 2026 TwinText; BabelDOC by its authors. SPDX-License-Identifier: AGPL-3.0-only
(function(global){
  'use strict';
  // Self-contained: its source runs in the reader's window as well. `inflate(bytes)` returns the raw-deflate or zlib data, inflated.
  function createPdfObjects(bytes,inflate,data){
    class Name{constructor(name){this.name=name;}}
    class Ref{constructor(num){this.num=num;}}
    class Str{constructor(bytes){this.bytes=bytes;}}
    class Stream{constructor(dict,start){this.dict=dict;this.start=start;this.num=0;this.gen=0;}}
    const WHITE=new Set([0,9,10,12,13,32]),DELIM=new Set([40,41,60,62,91,93,123,125,47,37]);
    const latin1=(b,from=0,to=b.length)=>{let s='';for(let i=from;i<to;i+=8192)s+=String.fromCharCode(...b.subarray(i,Math.min(to,i+8192)));return s;};
    function lexer(b,start=0){
      let p=start;
      const skip=()=>{for(;;){while(p<b.length&&WHITE.has(b[p]))p++;if(b[p]===37){while(p<b.length&&b[p]!==10&&b[p]!==13)p++;continue;}return;}};
      const parseValue=()=>{
        skip();const c=b[p];
        if(c===undefined)throw new Error('End of PDF data');
        if(c===47){
          p++;let s='';
          while(p<b.length&&!WHITE.has(b[p])&&!DELIM.has(b[p])){
            if(b[p]===35&&p+2<b.length){const v=parseInt(String.fromCharCode(b[p+1],b[p+2]),16);if(!Number.isNaN(v)){s+=String.fromCharCode(v);p+=3;continue;}}
            s+=String.fromCharCode(b[p++]);
          }
          return new Name(s);
        }
        if(c===91){p++;const out=[];for(;;){skip();if(b[p]===93){p++;return out;}if(p>=b.length)return out;out.push(parseValue());}}
        if(c===60&&b[p+1]===60){
          p+=2;const out={};
          for(;;){
            skip();
            if(b[p]===62&&b[p+1]===62){p+=2;return out;}
            if(p>=b.length)return out;
            const key=parseValue();if(!(key instanceof Name))continue;
            out[key.name]=parseValue();
          }
        }
        if(c===60){
          p++;const out=[];let high=-1;
          while(p<b.length&&b[p]!==62){const v=parseInt(String.fromCharCode(b[p]),16);p++;if(Number.isNaN(v))continue;if(high<0)high=v;else{out.push(high*16+v);high=-1;}}
          p++;if(high>=0)out.push(high*16);
          return new Str(Uint8Array.from(out));
        }
        if(c===40){
          p++;const out=[];let depth=1;
          while(p<b.length){
            const v=b[p++];
            if(v===92){
              const e=b[p++];
              if(e===110)out.push(10);else if(e===114)out.push(13);else if(e===116)out.push(9);else if(e===98)out.push(8);else if(e===102)out.push(12);
              else if(e>=48&&e<=55){let n=e-48;for(let k=0;k<2&&b[p]>=48&&b[p]<=55;k++)n=n*8+b[p++]-48;out.push(n&255);}
              else if(e===13){if(b[p]===10)p++;}else if(e!==10)out.push(e);
              continue;
            }
            if(v===40)depth++;
            if(v===41&&--depth===0)break;
            out.push(v);
          }
          return new Str(Uint8Array.from(out));
        }
        let end=p;while(end<b.length&&!WHITE.has(b[end])&&!DELIM.has(b[end]))end++;
        if(end===p){p++;return null;}
        const word=latin1(b,p,end);p=end;
        if(/^[-+]?\d*\.?\d+$/.test(word)||/^[-+]?\d+\.$/.test(word)){
          const value=Number(word);
          if(/^\d+$/.test(word)){
            const back=p;skip();let e=p;while(b[e]>=48&&b[e]<=57)e++;
            if(e>p){const gen=p;p=e;skip();if(b[p]===82&&(WHITE.has(b[p+1])||DELIM.has(b[p+1])||p+1>=b.length)){p++;return new Ref(value);}p=gen;}
            p=back;
          }
          return value;
        }
        if(word==='true')return true;if(word==='false')return false;if(word==='null')return null;
        return {keyword:word};
      };
      return {parseValue,skip,get pos(){return p;},set pos(v){p=v;}};
    }
    const entries=new Map();const parsed=new Map();const objectStreams=new Map();
    let trailer=null,cipher=null;
    function md5(input){
      const K=Int32Array.from({length:64},(_,i)=>Math.floor(Math.abs(Math.sin(i+1))*4294967296)),S=[7,12,17,22,5,9,14,20,4,11,16,23,6,10,15,21];
      const n=input.length,words=new Int32Array((((n+8)>>>6)+1)*16);
      for(let i=0;i<n;i++)words[i>>2]|=input[i]<<(i%4*8);
      words[n>>2]|=128<<(n%4*8);words[words.length-2]=n*8;
      let a=1732584193,b=-271733879,c=-1732584194,d=271733878;
      for(let at=0;at<words.length;at+=16){
        const A=a,B=b,C=c,D=d;
        for(let i=0;i<64;i++){
          const round=i>>4;let f,g;
          if(round===0){f=(b&c)|(~b&d);g=i;}else if(round===1){f=(d&b)|(~d&c);g=(5*i+1)%16;}else if(round===2){f=b^c^d;g=(3*i+5)%16;}else{f=c^(b|~d);g=7*i%16;}
          const t=d,sum=(a+f+K[i]+words[at+g])|0,r=S[round*4+i%4];
          d=c;c=b;b=(b+((sum<<r)|(sum>>>(32-r))))|0;a=t;
        }
        a=(a+A)|0;b=(b+B)|0;c=(c+C)|0;d=(d+D)|0;
      }
      const out=new Uint8Array(16);[a,b,c,d].forEach((v,i)=>{for(let k=0;k<4;k++)out[i*4+k]=(v>>>(k*8))&255;});
      return out;
    }
    function rc4(key,input){
      const box=Uint8Array.from({length:256},(_,i)=>i);let j=0;
      for(let i=0;i<256;i++){j=(j+box[i]+key[i%key.length])&255;[box[i],box[j]]=[box[j],box[i]];}
      const out=new Uint8Array(input.length);let x=0,y=0;
      for(let i=0;i<input.length;i++){x=(x+1)&255;y=(y+box[x])&255;[box[x],box[y]]=[box[y],box[x]];out[i]=input[i]^box[(box[x]+box[y])&255];}
      return out;
    }
    // The standard security handler with the empty user password, which is what a reader opens without asking.
    function setCipher(encrypt,fileId){
      const V=encrypt.V||0,R=encrypt.R||2,PAD=Uint8Array.from([40,191,78,94,78,117,138,65,100,0,78,86,255,250,1,8,46,46,0,182,208,104,62,128,47,12,169,254,100,83,105,122]);
      if(encrypt.Filter?.name!=='Standard'||V<1||V>4)throw new Error('Unsupported encryption');
      const stream=V===4?encrypt.CF?.[encrypt.StmF?.name]:null,method=V===4?(encrypt.StmF?.name==='Identity'?'None':stream?.CFM?.name):'V2';
      const length=V===1?5:Math.floor((V===4&&!encrypt.Length?128:encrypt.Length||40)/8)||16;
      const O=encrypt.O.bytes.subarray(0,32),P=encrypt.P|0,id=fileId||new Uint8Array(0),plainMetadata=encrypt.EncryptMetadata===false;
      const seed=[...PAD,...O,P&255,(P>>>8)&255,(P>>>16)&255,(P>>>24)&255,...id,...(R>=4&&plainMetadata?[255,255,255,255]:[])];
      let key=md5(Uint8Array.from(seed));
      if(R>=3)for(let i=0;i<50;i++)key=md5(key.subarray(0,length));
      key=key.slice(0,length);
      const objectKey=(num,gen,aes)=>{
        const salted=[...key,num&255,(num>>8)&255,(num>>16)&255,gen&255,(gen>>8)&255,...(aes?[115,65,108,84]:[])];
        return md5(Uint8Array.from(salted)).slice(0,Math.min(16,key.length+5));
      };
      cipher={plainMetadata,async seal(input,num,gen){
        if(method==='None')return input;
        if(method==='V2')return rc4(objectKey(num,gen,false),input);
        const iv=crypto.getRandomValues(new Uint8Array(16)),material=await crypto.subtle.importKey('raw',objectKey(num,gen,true),'AES-CBC',false,['encrypt']);
        const sealed=new Uint8Array(await crypto.subtle.encrypt({name:'AES-CBC',iv},material,input)),out=new Uint8Array(16+sealed.length);
        out.set(iv);out.set(sealed,16);return out;
      },async open(input,num,gen){
        if(method==='None')return input;
        if(method==='V2')return rc4(objectKey(num,gen,false),input);
        if(method==='AESV2'){
          const material=await crypto.subtle.importKey('raw',objectKey(num,gen,true),'AES-CBC',false,['decrypt']);
          return new Uint8Array(await crypto.subtle.decrypt({name:'AES-CBC',iv:input.subarray(0,16)},material,input.subarray(16)));
        }
        throw new Error('Unsupported encryption method');
      }};
    }
    const find=(text,from,to=Math.min(bytes.length,from+4096))=>{outer:for(let i=from;i<=to-text.length;i++){for(let k=0;k<text.length;k++)if(bytes[i+k]!==text.charCodeAt(k))continue outer;return i;}return -1;};
    async function streamData(stream,withPredictor=true,raw=false){
      const dict=stream.dict,lengthValue=await resolve(dict.Length);
      let start=stream.start;
      if(bytes[start]===13&&bytes[start+1]===10)start+=2;else if(bytes[start]===10||bytes[start]===13)start++;
      let end=start+(Number.isFinite(lengthValue)?lengthValue:-1);
      if(!Number.isFinite(lengthValue)||find('endstream',end,Math.min(bytes.length,end+32))<0){const at=find('endstream',start,bytes.length);if(at<0)throw new Error('Unterminated stream');end=at;}
      let out=bytes.subarray(start,end);
      if(cipher&&stream.num&&dict.Type?.name!=='XRef'&&!(dict.Type?.name==='Metadata'&&cipher.plainMetadata))out=await cipher.open(out,stream.num,stream.gen);
      if(raw)return out;
      let filters=await resolve(dict.Filter??dict.F),params=await resolve(dict.DecodeParms??dict.DP);
      filters=filters==null?[]:Array.isArray(filters)?filters:[filters];params=Array.isArray(params)?params:[params];
      for(let i=0;i<filters.length;i++){
        const filter=(await resolve(filters[i]))?.name;
        if(filter==='FlateDecode'||filter==='Fl'){
          out=await inflate(out);
          const parm=await resolve(params[i]);
          if(withPredictor&&parm&&parm.Predictor>=10){
            const columns=parm.Columns||1,row=columns+1,rows=Math.floor(out.length/row),result=new Uint8Array(rows*columns);
            for(let r=0;r<rows;r++){
              const type=out[r*row];
              for(let c=0;c<columns;c++){
                const raw=out[r*row+1+c],left=c?result[r*columns+c-1]:0,up=r?result[(r-1)*columns+c]:0,upLeft=r&&c?result[(r-1)*columns+c-1]:0;
                let v=raw;
                if(type===1)v+=left;else if(type===2)v+=up;else if(type===3)v+=(left+up)>>1;
                else if(type===4){const e=left+up-upLeft,pa=Math.abs(e-left),pb=Math.abs(e-up),pc=Math.abs(e-upLeft);v+=pa<=pb&&pa<=pc?left:pb<=pc?up:upLeft;}
                result[r*columns+c]=v&255;
              }
            }
            out=result;
          }
        }else throw new Error('Unsupported stream filter: '+filter);
      }
      return out;
    }
    const parseAt=offset=>{
      const lex=lexer(bytes,offset);
      const num=lex.parseValue(),gen=lex.parseValue(),keyword=lex.parseValue();
      if(!Number.isInteger(num)||keyword?.keyword!=='obj')throw new Error('No object at offset');
      const value=lex.parseValue();lex.skip();
      if(value&&typeof value==='object'&&!Array.isArray(value)&&find('stream',lex.pos,lex.pos+6)===lex.pos){const stream=new Stream(value,lex.pos+6);stream.num=num;stream.gen=gen;return {num,value:stream};}
      return {num,value};
    };
    async function fetchObject(num){
      if(parsed.has(num))return parsed.get(num);
      const entry=entries.get(num);let value=null;
      if(entry?.type===1){
        const at=parseAt(entry.offset);
        if(at.num!==num)throw new Error('Object number mismatch');
        value=at.value;
      }else if(entry?.type===2){
        let table=objectStreams.get(entry.stream);
        if(!table){
          const stream=await fetchObject(entry.stream),data=await streamData(stream),n=await resolve(stream.dict.N),first=await resolve(stream.dict.First);
          const head=lexer(data);table={data,first,objects:new Map()};
          for(let i=0;i<n;i++){const k=head.parseValue(),off=head.parseValue();table.objects.set(k,off);}
          objectStreams.set(entry.stream,table);
        }
        if(table.objects.has(num))value=lexer(table.data,table.first+table.objects.get(num)).parseValue();
      }
      parsed.set(num,value);return value;
    }
    async function resolve(value){let v=value,guard=0;while(v instanceof Ref&&guard++<32)v=await fetchObject(v.num);return v;}
    async function readXref(offset,seen){
      if(seen.has(offset))return;seen.add(offset);
      const lex=lexer(bytes,offset);lex.skip();
      let dict=null;
      if(find('xref',lex.pos,lex.pos+4)===lex.pos){
        lex.pos+=4;
        for(;;){
          lex.skip();
          if(find('trailer',lex.pos,lex.pos+7)===lex.pos){lex.pos+=7;break;}
          const first=lex.parseValue(),count=lex.parseValue();
          if(!Number.isInteger(first)||!Number.isInteger(count))throw new Error('Bad xref table');
          for(let i=0;i<count;i++){
            const off=lex.parseValue(),gen=lex.parseValue(),type=lex.parseValue();
            if(type?.keyword==='n'&&!entries.has(first+i))entries.set(first+i,{type:1,offset:off});
            else if(type?.keyword==='f'&&!entries.has(first+i))entries.set(first+i,{type:0});
          }
        }
        dict=lex.parseValue();
        if(Number.isInteger(dict.XRefStm))await readXref(dict.XRefStm,seen);
      }else{
        const {value}=parseAt(offset);
        if(!(value instanceof Stream))throw new Error('Bad xref stream');
        dict=value.dict;
        const data=await streamData(value),w=dict.W,index=dict.Index||[0,dict.Size],size=w[0]+w[1]+w[2];let at=0;
        const field=(from,n)=>{let v=0;for(let i=0;i<n;i++)v=v*256+data[from+i];return v;};
        for(let k=0;k+1<index.length;k+=2)for(let i=0;i<index[k+1];i++,at+=size){
          const type=w[0]?field(at,w[0]):1,second=field(at+w[0],w[1]),third=field(at+w[0]+w[1],w[2]),num=index[k]+i;
          if(entries.has(num))continue;
          if(type===1)entries.set(num,{type:1,offset:second});
          else if(type===2)entries.set(num,{type:2,stream:second,index:third});
          else entries.set(num,{type:0});
        }
      }
      trailer=trailer?{...dict,...trailer}:dict;
      if(Number.isInteger(dict.Prev))await readXref(dict.Prev,seen);
    }
    function recover(){
      entries.clear();parsed.clear();trailer=null;
      const text=latin1(bytes),re=/(\d+)\s+\d+\s+obj\b/g;let m;
      while((m=re.exec(text)))entries.set(Number(m[1]),{type:1,offset:m.index});
      const t=/trailer\s*<</g;let last=null;while((m=t.exec(text)))last=m.index+m[0].length-2;
      if(last!==null)trailer=lexer(bytes,last).parseValue();
    }
    async function open(){
      try{
        const tail=latin1(bytes,Math.max(0,bytes.length-2048)),at=tail.lastIndexOf('startxref');
        if(at<0)throw new Error('No startxref');
        const startXref=lexer(bytes,Math.max(0,bytes.length-2048)+at+9).parseValue();
        await readXref(startXref,new Set());
        api.startXref=startXref;
        {const peek=lexer(bytes,startXref);peek.skip();api.usesXrefStream=find('xref',peek.pos,peek.pos+4)!==peek.pos;}
        if(!(await resolve(trailer?.Root)))throw new Error('No catalog');
      }catch(_){
        recover();
        if(!trailer?.Root)for(const num of entries.keys()){
          const v=await fetchObject(num).catch(()=>null);
          if(v&&v.Type?.name==='Catalog'){trailer={...(trailer||{}),Root:new Ref(num)};break;}
          if(v instanceof Stream&&v.dict.Type?.name==='ObjStm')await streamData(v).catch(()=>null);
        }
      }
      if(trailer?.Encrypt){
        const raw=trailer.Encrypt instanceof Ref?await fetchObject(trailer.Encrypt.num):trailer.Encrypt,encrypt={};
        for(const [key,value] of Object.entries(raw))encrypt[key]=await resolve(value);
        const id=await resolve(trailer.ID),first=Array.isArray(id)?await resolve(id[0]):null;
        if(encrypt.CF)for(const [name,value] of Object.entries(encrypt.CF)){const filter=await resolve(value);encrypt.CF[name]=filter;}
        parsed.clear();objectStreams.clear();
        setCipher(encrypt,first?.bytes);
        api.seal=cipher.seal;
      }
      return api;
    }
    async function pageDict(index){
      const catalog=await resolve(trailer.Root);let left=index;
      const walk=async(ref,inherited,guard=0)=>{
        const node=await resolve(ref);
        if(!node||guard>64)return null;
        const resources=node.Resources!==undefined?node.Resources:inherited;
        const kids=await resolve(node.Kids);
        if(Array.isArray(kids)&&node.Type?.name!=='Page'){
          for(const kid of kids){const found=await walk(kid,resources,guard+1);if(found)return found;}
          return null;
        }
        if(left--===0)return {...node,Resources:resources,__number:ref instanceof Ref?ref.num:null};
        return null;
      };
      return walk(catalog.Pages,undefined);
    }
    async function pageFonts(index){
      const page=await pageDict(index),out=[],seenForms=new Set();
      const collect=async resources=>{
        const res=await resolve(resources);if(!res)return;
        const fonts=await resolve(res.Font);
        if(fonts)for(const [name,ref] of Object.entries(fonts))out.push({name,ref:ref instanceof Ref?ref.num:null,dict:await resolve(ref)});
        const xobjects=await resolve(res.XObject);
        if(xobjects)for(const ref of Object.values(xobjects)){
          const key=ref instanceof Ref?ref.num:null;
          if(key!==null){if(seenForms.has(key))continue;seenForms.add(key);}
          const form=await resolve(ref);
          if(form instanceof Stream&&(await resolve(form.dict.Subtype))?.name==='Form')await collect(form.dict.Resources);
        }
      };
      if(page)await collect(page.Resources);
      return out.filter(f=>f.dict&&typeof f.dict==='object');
    }
    const {GLYPHS,ENCODINGS}=data;
    const utf16=b=>{let s='';for(let i=0;i+1<b.length;i+=2)s+=String.fromCharCode(b[i]*256+b[i+1]);return s.replace(/[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/gu,'');};
    function nameToUnicode(name){
      const stem=name.split('.')[0],parts=stem.split('_');
      if(parts.length>1)return parts.map(nameToUnicode).join('');
      if(Object.hasOwn(GLYPHS,stem))return GLYPHS[stem];
      if(stem.startsWith('uni')){
        const hex=stem.slice(3);
        if(/^[0-9a-fA-F]/.test(hex)&&hex.length%4===0&&hex.length){
          let out='';
          for(let i=0;i<hex.length;i+=4){const v=parseInt(hex.slice(i,i+4),16);if(v>55295&&v<57344)throw new Error('Invalid unicode');out+=String.fromCharCode(v);}
          return out;
        }
      }
      if(stem.startsWith('u')){
        const hex=stem.slice(1);
        if(/^[0-9a-fA-F]/.test(hex)&&hex.length>=4&&hex.length<=6){const v=parseInt(hex,16);if(v>55295&&v<57344)throw new Error('Invalid unicode');return String.fromCodePoint(v);}
      }
      throw new Error('Unknown glyph name');
    }
    const baseEncoding=name=>({StandardEncoding:ENCODINGS.Standard,MacRomanEncoding:ENCODINGS.MacRoman,WinAnsiEncoding:ENCODINGS.WinAnsi,PDFDocEncoding:ENCODINGS.PDFDoc}[name]||ENCODINGS.Standard);
    function parseToUnicode(data){
      const map=new Map(),text=latin1(data),re=/<[0-9A-Fa-f\s]*>|\/[^\s<>\[\]{}()\/%]+|[-+]?\d+|[A-Za-z][A-Za-z0-9._-]*|[\[\]]/g;
      const stack=[],arrays=[];let m;
      const push=v=>{if(arrays.length)arrays.at(-1).push(v);else stack.push(v);};
      const nunpack=b=>{let v=0;for(const x of b)v=v*256+x;return v;};
      const add=(cid,code)=>{
        let value;
        if(code instanceof Name){try{value=nameToUnicode(code.name);}catch(_){return;}}
        else if(code instanceof Uint8Array)value=utf16(code);
        else if(typeof code==='number')value=String.fromCodePoint(code);
        else return;
        if(value===' '&&map.get(cid)===' ')return;
        map.set(cid,value);
      };
      const packed=(prefix,value,len)=>{const out=new Uint8Array(prefix.length+len);out.set(prefix);for(let i=len-1,v=value;i>=0;i--,v=Math.floor(v/256))out[prefix.length+i]=v&255;return out;};
      while((m=re.exec(text))){
        const t=m[0];
        if(t==='['){arrays.push([]);continue;}
        if(t===']'){if(arrays.length){const items=arrays.pop();push(items);}continue;}
        if(t[0]==='/'){push(new Name(t.slice(1)));continue;}
        if(t[0]==='<'){let hex=t.slice(1,-1).replace(/\s+/g,'');if(hex.length%2)hex+='0';const b=new Uint8Array(hex.length/2);for(let i=0;i<b.length;i++)b[i]=parseInt(hex.substr(i*2,2),16);push(b);continue;}
        if(/^[-+]?\d/.test(t)){push(parseInt(t,10));continue;}
        if(/^begin(?:cid|bf)(?:range|char)$/.test(t)){stack.length=0;continue;}
        if(t==='endbfchar'){for(let i=0;i+2<=stack.length;i+=2)if(stack[i] instanceof Uint8Array&&stack[i+1] instanceof Uint8Array)add(nunpack(stack[i]),stack[i+1]);stack.length=0;continue;}
        if(t==='endbfrange'){
          for(let i=0;i+3<=stack.length;i+=3){
            const a=stack[i],z=stack[i+1],code=stack[i+2];
            if(!(a instanceof Uint8Array&&z instanceof Uint8Array)||a.length!==z.length)continue;
            const start=nunpack(a),end=nunpack(z);
            if(Array.isArray(code)){for(let k=start,j=0;k<=end&&j<code.length;k++,j++)add(k,code[j]);continue;}
            if(!(code instanceof Uint8Array))continue;
            const tail=code.subarray(Math.max(0,code.length-4)),base=nunpack(tail),prefix=code.subarray(0,Math.max(0,code.length-4));
            for(let k=0;k<=end-start;k++)add(start+k,packed(prefix,base+k,tail.length));
          }
          stack.length=0;continue;
        }
        if(t==='endcidchar'){for(let i=0;i+2<=stack.length;i+=2)if(typeof stack[i]==='number'&&stack[i+1] instanceof Uint8Array)add(stack[i],stack[i+1]);stack.length=0;continue;}
        if(t==='endcidrange'){
          for(let i=0;i+3<=stack.length;i+=3){
            const a=stack[i],z=stack[i+1],cid=stack[i+2];
            if(!(a instanceof Uint8Array&&z instanceof Uint8Array)||typeof cid!=='number'||a.length!==z.length)continue;
            const prefix=a.subarray(0,Math.max(0,a.length-4)),start=nunpack(a.subarray(Math.max(0,a.length-4))),end=nunpack(z.subarray(Math.max(0,z.length-4)));
            for(let k=0;k<=end-start;k++)add(cid+k,packed(prefix,start+k,Math.min(4,a.length)));
          }
          stack.length=0;continue;
        }
        push(t);
      }
      return map;
    }
    function type1Encoding(header){
      const out=new Map(),re=/<[0-9A-Fa-f\s]*>|\/[^\s<>\[\]{}()\/%]+|[-+]?\d+|[A-Za-z][A-Za-z0-9._-]*|[\[\]]/g,stack=[];let m;const text=latin1(header);
      while((m=re.exec(text))){
        const t=m[0];
        if(t==='put'){
          if(stack.length<2)continue;
          const value=stack.pop(),key=stack.pop();
          if(typeof key==='number'&&value instanceof Name){try{out.set(key,nameToUnicode(value.name));}catch(_){}}
          continue;
        }
        if(t[0]==='/'){stack.push(new Name(t.slice(1)));continue;}
        if('[]<'.includes(t[0]))continue;
        if(/^[-+]?\d/.test(t)){stack.push(parseInt(t,10));continue;}
        stack.push(t);
      }
      return out;
    }
    async function fontMetrics(descriptor){
      const raw=await resolve(descriptor?.Descent),value=Number.isFinite(raw)?raw:0;
      const embedded=Boolean(descriptor&&(descriptor.FontFile!==undefined||descriptor.FontFile2!==undefined||descriptor.FontFile3!==undefined));
      return {descent:(value>0?-value:value)*.001,embedded};
    }
    // A Type3 font's em comes from its matrix and box. A glyph's box is what its procedure draws as paths, in ems of that height.
    async function type3Metrics(dict,encoding){
      const matrix=await Promise.all((await resolve(dict.FontMatrix)).map(resolve)),bbox=await Promise.all((await resolve(dict.FontBBox)).map(resolve));
      const ys=[bbox[1],bbox[3]].flatMap(y=>[bbox[0],bbox[2]].map(x=>matrix[1]*x+matrix[3]*y+matrix[5])),y0=Math.min(...ys),y1=Math.max(...ys),emHeight=y1-y0;
      if(!(emHeight>0))return null;
      const boxes=new Map(),procs=await resolve(dict.CharProcs),diff=encoding&&typeof encoding==='object'?await resolve(encoding.Differences):null;
      let code=0;
      if(procs&&Array.isArray(diff))for(const value of diff){
        const item=await resolve(value);
        if(typeof item==='number'){code=item;continue;}
        if(!(item instanceof Name))continue;
        const stream=await resolve(procs[item.name]);
        if(stream instanceof Stream){
          const box=glyphDrawing(await streamData(stream).catch(()=>new Uint8Array(0)),matrix);
          if(box)boxes.set(code,box.map(v=>v/emHeight));
        }
        code++;
      }
      return {emHeight,descent:y0/emHeight,boxes};
    }
    function glyphDrawing(data,fontMatrix){
      const words=latin1(data).split(/\s+/);let stackNumbers=[],m=fontMatrix.slice(),x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity,points=[],curX=0,curY=0;
      const saved=[];
      const see=(x,y)=>{const X=m[0]*x+m[2]*y+m[4],Y=m[1]*x+m[3]*y+m[5];points.push([X,Y]);};
      for(const word of words){
        if(/^[-+]?(\d+\.?\d*|\.\d+)$/.test(word)){stackNumbers.push(Number(word));continue;}
        const n=stackNumbers;
        if(word==='q')saved.push(m.slice());
        else if(word==='Q'){if(saved.length)m=saved.pop();}
        else if(word==='cm'&&n.length>=6){const [a,b,c,d,e,f]=n.slice(-6);m=[a*m[0]+b*m[2],a*m[1]+b*m[3],c*m[0]+d*m[2],c*m[1]+d*m[3],e*m[0]+f*m[2]+m[4],e*m[1]+f*m[3]+m[5]];}
        else if((word==='m'||word==='l')&&n.length>=2){[curX,curY]=n.slice(-2);see(curX,curY);}
        else if(word==='c'&&n.length>=6){const v=n.slice(-6);see(v[0],v[1]);see(v[2],v[3]);see(v[4],v[5]);[curX,curY]=[v[4],v[5]];}
        else if(word==='v'&&n.length>=4){const v=n.slice(-4);see(curX,curY);see(v[0],v[1]);see(v[2],v[3]);[curX,curY]=[v[2],v[3]];}
        else if(word==='y'&&n.length>=4){const v=n.slice(-4);see(v[0],v[1]);see(v[2],v[3]);[curX,curY]=[v[2],v[3]];}
        else if(word==='re'&&n.length>=4){const [x,y,w,h]=n.slice(-4);see(x,y);see(x+w,y);see(x,y+h);see(x+w,y+h);}
        else if(word==='BI')break;
        if(/^(f\*?|F|S|s|B\*?|b\*?)$/.test(word)){for(const [X,Y] of points){if(X<x0)x0=X;if(X>x1)x1=X;if(Y<y0)y0=Y;if(Y>y1)y1=Y;}points=[];}
        else if(word==='n')points=[];
        stackNumbers=[];
      }
      return x0===Infinity?null:[x0,y0,x1,y1];
    }
    // The page's frame in BabelDOC: the media box's far corner, from the origin.
    async function pageMediaBox(index){
      const catalog=await resolve(trailer.Root);let left=index,found=null;
      const walk=async(ref,inherited,guard=0)=>{
        const node=await resolve(ref);
        if(!node||found||guard>64)return;
        const box=node.MediaBox!==undefined?node.MediaBox:inherited,kids=await resolve(node.Kids);
        if(Array.isArray(kids)&&node.Type?.name!=='Page'){for(const kid of kids){await walk(kid,box,guard+1);if(found)return;}return;}
        if(left--===0)found=await Promise.all((await resolve(box)).map(resolve));
      };
      await walk(catalog.Pages,undefined);
      return found;
    }
    // What a font says about its characters: code to text, and whether BabelDOC would fall back for a code it does not know.
    async function fontSpec(dict){
      const subtype=(await resolve(dict.Subtype))?.name;
      if(subtype==='Type0'){
        const list=await resolve(dict.DescendantFonts),descendant=await resolve(Array.isArray(list)?list[0]:null);
        const toUnicode=dict.ToUnicode!==undefined?await resolve(dict.ToUnicode):undefined;
        const descriptor=await resolve(descendant?.FontDescriptor);
        return {composite:true,baseFont:(await resolve(descendant?.BaseFont))?.name||(await resolve(dict.BaseFont))?.name||'',...(await fontMetrics(descriptor)),
          toUnicode:toUnicode instanceof Stream?parseToUnicode(await streamData(toUnicode)):null,encoding:null};
      }
      const baseFont=(await resolve(dict.BaseFont))?.name||'';
      const descriptor=await resolve(dict.FontDescriptor);
      const raw=dict.Encoding!==undefined?await resolve(dict.Encoding):undefined;
      let encoding;
      if(raw instanceof Name)encoding=new Map(Object.entries(baseEncoding(raw.name)).map(([k,v])=>[Number(k),v]));
      else if(raw&&typeof raw==='object'&&!Array.isArray(raw)){
        const base=await resolve(raw.BaseEncoding);
        encoding=new Map(Object.entries(baseEncoding(base?.name||'StandardEncoding')).map(([k,v])=>[Number(k),v]));
        const diff=await resolve(raw.Differences);
        if(Array.isArray(diff)){let code=0;for(const value of diff){const item=await resolve(value);if(typeof item==='number'){code=item;continue;}if(item instanceof Name){try{encoding.set(code,nameToUnicode(item.name));}catch(_){}code++;}}}
      }else encoding=new Map(Object.entries(ENCODINGS.Standard).map(([k,v])=>[Number(k),v]));
      if(raw===undefined&&descriptor?.FontFile!==undefined){
        try{
          const file=await resolve(descriptor.FontFile),length1=await resolve(file.dict.Length1);
          let header=(await streamData(file)).subarray(0,length1);
          const at=latin1(header).indexOf('/Encoding');
          if(at>=0)header=header.subarray(at);
          encoding=type1Encoding(header);
        }catch(_){}
      }
      const toUnicode=dict.ToUnicode!==undefined?await resolve(dict.ToUnicode):undefined;
      const map=toUnicode instanceof Stream?parseToUnicode(await streamData(toUnicode)):null;
      const firstChar=await resolve(dict.FirstChar),widths=await resolve(dict.Widths);
      const type3=subtype==='Type3'?await type3Metrics(dict,raw).catch(()=>null):null;
      const metrics=await fontMetrics(descriptor);
      if(type3)metrics.descent=type3.descent;
      const base14=!metrics.embedded&&subtype!=='Type3'?data.BASE14[data.BASE14_ALIAS[baseFont]||baseFont]||null:null;
      return {composite:false,baseFont:baseFont||'',...metrics,base14,toUnicode:map,encoding,type3,firstChar:Number.isInteger(firstChar)?firstChar:0,widths:Array.isArray(widths)?await Promise.all(widths.map(resolve)):null};
    }
    async function exportObject(num){
      const entry=entries.get(num),value=await fetchObject(num);
      const gen=entry?.type===1?(()=>{const lex=lexer(bytes,entry.offset);lex.parseValue();return lex.parseValue();})():0;
      const decrypt=async value=>{
        if(value instanceof Str)return cipher&&entry?.type===1?new Str(await cipher.open(value.bytes,num,gen)):value;
        if(value instanceof Name||value instanceof Ref||value===null||typeof value!=='object')return value;
        if(Array.isArray(value))return Promise.all(value.map(decrypt));
        const result={};for(const [key,v] of Object.entries(value))result[key]=await decrypt(v);return result;
      };
      if(value instanceof Stream)return {value:await decrypt(value.dict),stream:await streamData(value,true,true)};
      return {value:await decrypt(value)};
    }
    const api={exportObject,open,seal:null,startXref:null,usesXrefStream:false,pageDict,pageFonts,pageMediaBox,fontSpec,resolve,streamData,parseToUnicode,nameToUnicode,get trailer(){return trailer;},get size(){return entries.size;},Stream,Name,Ref};
    return api;
  }
  // Plain inflate: whatever follows a stream's end, and whatever arrives before a truncation, is simply let be.
  function inflateSync(input){
    let pos=input.length>2&&(input[0]&15)===8&&((input[0]<<8)|input[1])%31===0?2:0,bit=0,count=0;
    let out=new Uint8Array(Math.max(1024,input.length*4)),size=0;
    const need=n=>{if(size+n>out.length){const next=new Uint8Array(Math.max(out.length*2,size+n));next.set(out.subarray(0,size));out=next;}};
    const bits=n=>{
      while(count<n){if(pos>=input.length)throw new RangeError('truncated');bit|=input[pos++]<<count;count+=8;}
      const v=bit&((1<<n)-1);bit>>>=n;count-=n;return v;
    };
    const table=lengths=>{
      const counts=new Uint16Array(16),symbols=new Uint16Array(lengths.length),offs=new Uint16Array(16);
      for(const l of lengths)counts[l]++;
      counts[0]=0;
      for(let i=1;i<16;i++)offs[i]=offs[i-1]+counts[i-1];
      lengths.forEach((l,i)=>{if(l)symbols[offs[l]++]=i;});
      return {counts,symbols};
    };
    const decode=h=>{
      let code=0,first=0,index=0;
      for(let len=1;len<16;len++){
        code|=bits(1);
        const c=h.counts[len];
        if(code-c<first)return h.symbols[index+(code-first)];
        index+=c;first+=c;first<<=1;code<<=1;
      }
      throw new RangeError('bad code');
    };
    const LBASE=[3,4,5,6,7,8,9,10,11,13,15,17,19,23,27,31,35,43,51,59,67,83,99,115,131,163,195,227,258],LEXT=[0,0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,0];
    const DBASE=[1,2,3,4,5,7,9,13,17,25,33,49,65,97,129,193,257,385,513,769,1025,1537,2049,3073,4097,6145,8193,12289,16385,24577],DEXT=[0,0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12,12,13,13];
    const fixedL=new Array(288),fixedD=table(new Array(30).fill(5));
    for(let i=0;i<288;i++)fixedL[i]=i<144?8:i<256?9:i<280?7:8;
    const fixedLit=table(fixedL);
    try{
      for(let last=0;!last;){
        last=bits(1);
        const type=bits(2);
        if(type===0){
          bit=0;count=0;
          if(pos+4>input.length)throw new RangeError('truncated');
          const len=input[pos]|(input[pos+1]<<8);pos+=4;
          const end=Math.min(input.length,pos+len);need(end-pos);out.set(input.subarray(pos,end),size);size+=end-pos;pos=end;
          continue;
        }
        if(type===3)throw new RangeError('bad block');
        let lit=fixedLit,dist=fixedD;
        if(type===2){
          const nlen=bits(5)+257,ndist=bits(5)+1,ncode=bits(4)+4,order=[16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1,15],lengths=new Array(19).fill(0);
          for(let i=0;i<ncode;i++)lengths[order[i]]=bits(3);
          const codes=table(lengths),all=new Array(nlen+ndist).fill(0);
          for(let i=0;i<nlen+ndist;){
            const sym=decode(codes);
            if(sym<16)all[i++]=sym;
            else{
              let prev=0,rep;
              if(sym===16){prev=all[i-1];rep=3+bits(2);}else if(sym===17)rep=3+bits(3);else rep=11+bits(7);
              while(rep--&&i<nlen+ndist)all[i++]=prev;
            }
          }
          lit=table(all.slice(0,nlen));dist=table(all.slice(nlen));
        }
        for(;;){
          const sym=decode(lit);
          if(sym<256){need(1);out[size++]=sym;continue;}
          if(sym===256)break;
          const length=LBASE[sym-257]+bits(LEXT[sym-257]),ds=decode(dist),back=DBASE[ds]+bits(DEXT[ds]);
          need(length);
          for(let i=0;i<length;i++,size++)out[size]=out[size-back];
        }
      }
    }catch(error){if(!(error instanceof RangeError)||!size)throw error;}
    return out.slice(0,size);
  }
  global.TwinTextTypesetPdfObjects=Object.freeze({createPdfObjects,inflateSync});
})(this);
