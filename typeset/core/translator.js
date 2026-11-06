// Typeset engine: what goes to the translator and how the reply comes back. Ported from BabelDOC 0.6.4 document_il/midend/il_translator
// with its plain (non-LLM) route, on which rich-text placeholders are off and a failed paragraph keeps its source.
// Copyright (C) 2026 TwinText; BabelDOC by its authors. SPDX-License-Identifier: AGPL-3.0-only
(function(global){
  'use strict';
  const S=()=>global.TwinTextTypesetStructure;
  const NUMERIC=/^-?\d+(\.\d+)?$/u;
  const WHITE=/^[\s\x1c-\x1f\x85]+$/u;
  const trimmed=text=>String(text||'').replace(/^[\s\x1c-\x1f\x85]+|[\s\x1c-\x1f\x85]+$/gu,'');
  const FORMULA_ANY=/\{\s*v\s*\d+\s*\}/giu,LEFT_ANY=/<\s*style\s*id\s*=\s*'\s*\d+\s*'\s*>/giu,RIGHT_ANY=/<\s*\/\s*style\s*>/giu;
  const placeholderOf=id=>({id,placeholder:`{v${id}}`,pattern:`\\{\\s*v\\s*${id}\\s*\\}`});
  function placeholderOnly(p){
    if(!p?.unicode)return false;
    for(const comp of p.comps){
      if(comp.kind==='formula')continue;
      if(comp.kind==='char'){if(!WHITE.test(comp.char.unicode))return false;}
      else if(comp.kind==='line'||comp.kind==='same'){if(!comp.chars.every(c=>WHITE.test(c.unicode)))return false;}
      else if(comp.kind==='text'){if(!WHITE.test(comp.unicode))return false;}
      else return false;
    }
    return true;
  }
  function originalTokens(text){
    const tokens=new Set();
    for(const pattern of [FORMULA_ANY,LEFT_ANY,RIGHT_ANY])for(const m of String(text||'').matchAll(pattern))tokens.add(m[0]);
    return tokens;
  }
  function translateInput(p){
    if(!p.comps.length)return null;
    if(p.unicode&&NUMERIC.test(trimmed(p.unicode)))return null;
    if(placeholderOnly(p))return null;
    const original=originalTokens(p.unicode);
    if(p.comps.length===1){
      const comp=p.comps[0];
      if(comp.kind==='line'||comp.kind==='same'||comp.kind==='char')return {unicode:p.unicode,placeholders:[],baseStyle:p.style,original};
      return null;
    }
    let id=1;const placeholders=[],chars=[];
    for(const comp of p.comps){
      if(comp.kind==='line'||comp.kind==='same')chars.push(...comp.chars);
      else if(comp.kind==='char')chars.push(comp.char);
      else if(comp.kind==='formula'){
        let ph=placeholderOf(id);
        while(new RegExp('^'+ph.pattern,'iu').test(p.unicode||''))ph=placeholderOf(++id);
        placeholders.push({...ph,formula:comp});
        id=ph.id+1;
        chars.push(...ph.placeholder);
      }else return null;
    }
    return {unicode:S().unicodeString(chars),placeholders,baseStyle:p.style,original};
  }
  function parseOutput(input,output){
    if(!input.placeholders.length)return [{kind:'text',unicode:output,style:input.baseStyle}];
    const patterns=input.placeholders.map(ph=>`(${ph.pattern})`),combined=new RegExp(patterns.join('|'),'giu'),leftover=new RegExp(patterns.join('|'),'giu');
    const allowed=new Set([...input.original,...input.placeholders.map(ph=>ph.placeholder)]);
    const strip=text=>{
      let out=text.replace(leftover,'');
      for(const pattern of [FORMULA_ANY,LEFT_ANY,RIGHT_ANY])out=out.replace(pattern,token=>allowed.has(token)?token:'');
      return out;
    };
    const result=[];let last=0;
    for(const match of output.matchAll(combined)){
      if(match.index>last)result.push({kind:'text',unicode:strip(output.slice(last,match.index)),style:input.baseStyle});
      const found=input.placeholders.find(ph=>new RegExp(`^${ph.pattern}$`,'iu').test(match[0]));
      result.push(found.formula);
      last=match.index+match[0].length;
    }
    if(last<output.length)result.push({kind:'text',unicode:strip(output.slice(last)),style:input.baseStyle});
    return result;
  }
  const textLength=text=>Array.from(text).length;
  // Paragraphs that come in while the document is still being read: a page's go in once it is built, and the translation waits for more until the feed is closed.
  function feed(){
    const queue=[],waiting=[];let closed=false;
    return {
      push(paragraphs){for(const p of paragraphs)queue.push(p);while(waiting.length&&queue.length)waiting.shift()(queue.shift());},
      close(){closed=true;for(const resolve of waiting.splice(0))resolve(null);},
      next(){return queue.length?queue.shift():closed?null:new Promise(resolve=>waiting.push(resolve));}
    };
  }
  // Translates in place; returns what happened to each paragraph. A paragraph that fails keeps its source, as in BabelDOC.
  async function translateParagraphs(paragraphs,translate,{concurrency=4,minTextLength=2,cancelled,onParagraph}={}){
    const stats={requested:0,translated:0,failed:0,skipped:0,lostPlaceholders:0};
    let queue=paragraphs;
    if(Array.isArray(paragraphs)){queue=feed();queue.push(paragraphs);queue.close();}
    const worker=async()=>{
      while(!cancelled?.()){
        const p=await queue.next();
        if(!p)return;
        const input=p.vertical?null:translateInput(p);
        if(!input||textLength(input.unicode)<minTextLength){stats.skipped++;onParagraph?.(p,'skipped');continue;}
        stats.requested++;
        try{
          const reply=await translate(input.unicode,p);
          const text=String(reply).replace(/[. 。…，]{20,}/gu,'.');
          const comps=parseOutput(input,text);
          stats.lostPlaceholders+=input.placeholders.length-comps.filter(c=>c.kind==='formula').length;
          p.source={unicode:p.unicode,comps:p.comps};
          p.unicode=text;p.comps=comps;
          stats.translated++;onParagraph?.(p,'translated');
        }catch(error){
          if(error?.name==='AbortError')throw error;
          p.failed=true;stats.failed++;onParagraph?.(p,'failed');
        }
      }
    };
    await Promise.all(Array.from({length:Math.max(1,concurrency)},worker));
    return stats;
  }
  global.TwinTextTypesetTranslator=Object.freeze({translateInput,parseOutput,feed,translateParagraphs});
})(this);
