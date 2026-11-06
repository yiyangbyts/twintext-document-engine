// Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
(function(global){
  const bytes=text=>new TextEncoder().encode(text);
  const join=parts=>{const out=new Uint8Array(parts.reduce((n,p)=>n+p.length,0));let at=0;for(const p of parts){out.set(p,at);at+=p.length;}return out;};
  async function decryptedPDF(input){
    const api=global.TwinTextTypesetPdfObjects;
    const objects=await api.createPdfObjects(input,async b=>api.inflateSync(b),global.TwinTextTypesetFontData).open();
    if(!objects.seal)return input;
    const hex=b=>'<'+Array.from(b,n=>n.toString(16).padStart(2,'0')).join('')+'>';
    const name=s=>'/'+Array.from(bytes(s),n=>n<=32||n>=127||[35,37,40,41,47,60,62,91,93,123,125].includes(n)?'#'+n.toString(16).padStart(2,'0'):String.fromCharCode(n)).join('');
    const encode=v=>v instanceof objects.Ref?`${v.num} 0 R`:v instanceof objects.Name?name(v.name):v?.bytes?hex(v.bytes):Array.isArray(v)?'['+v.map(encode).join(' ')+']':v&&typeof v==='object'?'<<'+Object.entries(v).filter(([k])=>!k.startsWith('__')).map(([k,x])=>name(k)+' '+encode(x)).join('\n')+'>>':v===null||v===undefined?'null':String(v);
    const size=Math.max(Number(objects.trailer.Size)||0,objects.size+1);
    const parts=[bytes('%PDF-1.7\n')],offsets=[0];let length=parts[0].length;
    const append=b=>{parts.push(b);length+=b.length;};
    for(let num=1;num<size;num++){
      // Encryption dictionaries are deliberately not referenced by the new trailer.
      if(num===objects.trailer.Encrypt?.num)continue;
      const object=await objects.exportObject(num);
      if(!object.value)continue;
      offsets[num]=length;append(bytes(`${num} 0 obj\n`));
      if(object.stream){append(bytes(encode({...object.value,Length:object.stream.length})+'\nstream\n'));append(object.stream);append(bytes('\nendstream'));}
      else append(bytes(encode(object.value)));
      append(bytes('\nendobj\n'));
    }
    const xref=length;
    append(bytes(`xref\n0 ${size}\n0000000000 65535 f \n`+Array.from({length:size-1},(_,i)=>offsets[i+1]?String(offsets[i+1]).padStart(10,'0')+' 00000 n \n':'0000000000 00000 f \n').join('')+`trailer\n<< /Size ${size} /Root ${encode(objects.trailer.Root)} >>\nstartxref\n${xref}\n%%EOF\n`));
    return join(parts);
  }
  global.TwinTextPDFNormalize=Object.freeze({decryptedPDF});
})(this);
