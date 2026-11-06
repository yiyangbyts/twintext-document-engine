// Typeset engine: regions to paragraphs, formulas and styles. Ported from BabelDOC 0.6.4 document_il/midend/{layout_parser,paragraph_finder,
// styles_and_formulas}, document_il/utils/{extract_char,layout_helper,formular_helper}. Rules are kept as they are there, down to their order.
// Copyright (C) 2026 TwinText; BabelDOC by its authors. SPDX-License-Identifier: AGPL-3.0-only
// A character: {unicode,box,visual,style:{font,size,state},cid,vertical,xobj,advance,renderOrder}. Boxes: {x,y,x2,y2}, y up, in points.
(function(global){
  'use strict';
  const data=()=>global.TwinTextTypesetFontData;
  const box=(x,y,x2,y2)=>({x,y,x2,y2});
  const isSpaceChar=c=>/^[\s\x1c-\x1f\x85]+$/u.test(c)&&c.length>0;
  const LAYOUT_PRIORITY=['number','reference','reference_content','algorithm','formula_caption','isolate_formula','table_footnote','table_caption','figure_caption','figure_title','chart_title','table_title','table_cell_hybrid','table_text','wireless_table_cell','wired_table_cell','abandon','title','abstract','paragraph_title','content','doc_title','footnote','header','footer','seal','plain text','tiny text','author_info_hybrid','list_item_hybrid','text','paragraph_hybrid','paragraph','table_cell','figure_text','list_item','title','caption','footnote_hybrid','footnote','formula','formula_hybrid','page_header','page_footer','reference_hybrid','document_hybrid','academic_paper_hybrid','form_or_table_hybrid','presentation_slide_hybrid','webpage_screenshot_hybrid','manga_or_comic_hybrid','advertisement_hybrid','magazine_or_newspaper_hybrid','other_hybrid','table_cell_hybrid','figure_text_hybrid','title_hybrid','caption_hybrid','code_algo_hybrid','line_number_hybrid','page_header_hybrid','page_footer_hybrid','page_number_hybrid','unknown_hybrid','fallback_line','table','figure','image'];
  const TEXT_LAYOUTS=new Set(['plain text','tiny text','title','abandon','figure_caption','table_caption','table_text','table_footnote','paragraph_title','abstract','content','figure_title','table_title','doc_title','footnote','header','footer','seal','text','chart_title','paragraph','table_cell','figure_text','list_item','caption','page_header','page_footer','wired_table_cell','wireless_table_cell','paragraph_hybrid','table_cell_hybrid','caption_hybrid','unknown_hybrid','figure_text_hybrid','list_item_hybrid','title_hybrid','fallback_line','author_info_hybrid','page_header_hybrid','page_footer_hybrid','footnote_hybrid']);
  const BULLET=/^[■•⚫⬤◆◇○●◦‣⁃▪▫∗†‡¹²³⁴⁵⁶⁷⁸⁹⁰₁₂₃₄₅₆₇₈₉₀ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ¶※⁑⁂⁕⁎⁜❧☙⁋‖‽·]/u;
  const LEFT_BRACKET=new Set(['(cid:8)','(','(cid:16)','{','[','(cid:104)','(cid:2)']),RIGHT_BRACKET=new Set(['(cid:9)',')','(cid:17)','}',']','(cid:105)','(cid:3)']);
  const mean=values=>values.length?values.reduce((a,b)=>a+b,0)/values.length:NaN;
  // --- regions and the lines drawn around stray characters
  function pageLayoutFromModel(boxes,pageWidth,pageHeight){
    const w=Math.ceil(pageWidth),h=Math.ceil(pageHeight),clip=(v,hi)=>Math.min(hi,Math.max(0,Math.trunc(v)));
    return boxes.map((b,i)=>({id:i+1,name:b.name,confidence:b.confidence,box:box(clip(b.x0-1,w-1),clip(h-b.y1-1,h-1),clip(b.x1+1,w-1),clip(h-b.y0+1,h-1))}));
  }
  function components(points,linked){
    // DBSCAN with one sample a cluster is connected components, labelled by first appearance.
    const labels=new Array(points.length).fill(-1);let next=0;
    for(let i=0;i<points.length;i++){
      if(labels[i]>=0)continue;
      const stack=[i];labels[i]=next;
      while(stack.length){const a=stack.pop();for(let b=0;b<points.length;b++)if(labels[b]<0&&linked(points[a],points[b])){labels[b]=next;stack.push(b);}}
      next++;
    }
    return labels;
  }
  const groupBy=(items,labels)=>{const out=new Map();items.forEach((item,i)=>{if(!out.has(labels[i]))out.set(labels[i],[]);out.get(labels[i]).push(item);});return [...out.values()];};
  function clusterByAxis(chars,orientation){
    if(!chars.length)return [];
    const horizontal=orientation==='horizontal';
    const secondaryStart=c=>horizontal?c.y:c.x,secondaryEnd=c=>horizontal?c.y2:c.x2,mainStart=c=>horizontal?c.x:c.y,mainSize=c=>horizontal?c.x2-c.x:c.y2-c.y;
    chars.sort((a,b)=>secondaryStart(a)-secondaryStart(b));
    const bands=[];
    for(const c of chars){
      const start=secondaryStart(c),end=secondaryEnd(c),size=end-start;let best=-1,bestRatio=.5;
      for(let i=bands.length-1;i>=0;i--){
        const band=bands[i];
        if(band.end<start)break;
        const overlap=Math.max(0,Math.min(end,band.end)-Math.max(start,band.start));
        if(size>0&&overlap/size>bestRatio){bestRatio=overlap/size;best=i;}
      }
      if(best!==-1){const band=bands[best];band.chars.push(c);band.start=Math.min(band.start,start);band.end=Math.max(band.end,end);bands.push(bands.splice(best,1)[0]);}
      else bands.push({chars:[c],start,end});
    }
    const lines=[];
    for(const band of bands){
      const sizes=band.chars.map(mainSize).filter(v=>v>0),eps=(sizes.length?mean(sizes):10)*3.5;
      const centres=band.chars.map(c=>[(c.x+c.x2)/2,(c.y+c.y2)/2]);
      for(const line of groupBy(band.chars,components(centres,(a,b)=>Math.abs(a[0]-b[0])+Math.abs(a[1]-b[1])<=eps))){line.sort((a,b)=>mainStart(a)-mainStart(b));lines.push(line);}
    }
    const out=[];
    for(const line of lines){
      const low=Math.min(...line.map(secondaryStart)),high=Math.max(...line.map(secondaryEnd)),sizes=line.map(c=>secondaryEnd(c)-secondaryStart(c)).filter(v=>v>0);
      if(!sizes.length){out.push(line);continue;}
      const largest=Math.max(...sizes);
      if(high-low>largest*1.5&&line.length>1){
        const centres=line.map(c=>(secondaryStart(c)+secondaryEnd(c))/2);
        for(const sub of groupBy(line,components(centres,(a,b)=>Math.abs(a-b)<=largest*.5))){sub.sort((a,b)=>mainStart(a)-mainStart(b));out.push(sub);}
      }else out.push(line);
    }
    return out;
  }
  function mergeLines(lines){
    const merged=[],skip=new Set(),bounds=line=>[Math.min(...line.map(c=>c.x)),Math.min(...line.map(c=>c.y)),Math.max(...line.map(c=>c.x2)),Math.max(...line.map(c=>c.y2))];
    for(let i=0;i<lines.length;i++){
      if(skip.has(i))continue;
      let line1=lines[i];
      if(!line1.length){merged.push(line1);continue;}
      let b1=bounds(line1),didMerge=false;
      const heights=line1.filter(c=>c.y2>c.y).map(c=>c.y2-c.y),maxGap=(heights.length?mean(heights):0)*1.5;
      for(let j=i+1;j<lines.length;j++){
        if(skip.has(j))continue;
        const line2=lines[j];
        if(!line2.length)continue;
        const b2=bounds(line2);
        if(b1[1]-b2[3]>maxGap)break;
        const inter=Math.max(0,Math.min(b1[2],b2[2])-Math.max(b1[0],b2[0]))*Math.max(0,Math.min(b1[3],b2[3])-Math.max(b1[1],b2[1]));
        const area1=b1[2]>b1[0]&&b1[3]>b1[1]?(b1[2]-b1[0])*(b1[3]-b1[1]):0,area2=b2[2]>b2[0]&&b2[3]>b2[1]?(b2[2]-b2[0])*(b2[3]-b2[1]):0;
        const grow=()=>{b1=[Math.min(b1[0],b2[0]),Math.min(b1[1],b2[1]),Math.max(b1[2],b2[2]),Math.max(b1[3],b2[3])];skip.add(j);didMerge=true;};
        if(area2>0&&area1>=area2&&inter/area2>.6){line1.push(...line2);grow();}
        else if(area1>0&&area2>area1&&inter/area1>.6){line2.push(...line1);lines[i]=line2;lines[j]=line1;line1=lines[i];grow();}
        else if(!line1[0].vertical){
          const h1=b1[3]-b1[1],h2=b2[3]-b2[1];
          if(h1>0&&h2>0){
            const overlap=Math.max(0,Math.min(b1[3],b2[3])-Math.max(b1[1],b2[1]));
            if(overlap/h1>.7&&overlap/h2>.7){
              const gap=Math.max(b1[0],b2[0])-Math.min(b1[2],b2[2]);
              if(gap>=0){
                const widths=[...line1,...line2].filter(c=>c.x2>c.x).map(c=>c.x2-c.x),avg=widths.length?mean(widths):0;
                if(avg>0&&gap<avg*1.5){line1.push(...line2);grow();}
              }
            }
          }
        }else{
          const w1=b1[2]-b1[0],w2=b2[2]-b2[0];
          if(w1>0&&w2>0){
            const overlap=Math.max(0,Math.min(b1[2],b2[2])-Math.max(b1[0],b2[0]));
            if(overlap/w1>.7&&overlap/w2>.7){
              const gap=Math.max(b1[1],b2[1])-Math.min(b1[3],b2[3]);
              if(gap>=0){
                const hs=[...line1,...line2].filter(c=>c.y2>c.y).map(c=>c.y2-c.y),avg=hs.length?mean(hs):0;
                if(avg>0&&gap<avg*1.5){line1.push(...line2);grow();}
              }
            }
          }
        }
      }
      if(didMerge){if(!line1[0].vertical)line1.sort((a,b)=>a.x-b.x);else line1.sort((a,b)=>a.y-b.y);}
      merged.push(line1);
    }
    return merged;
  }
  function fallbackLines(chars,firstId){
    const entries=chars.map(c=>({x:c.visual.x,y:c.visual.y,x2:c.visual.x2,y2:c.visual.y2,vertical:c.vertical}));
    if(!entries.length)return [];
    const lines=[...clusterByAxis(entries.filter(c=>!c.vertical),'horizontal'),...clusterByAxis(entries.filter(c=>c.vertical),'vertical')];
    const position=line=>[-mean(line.map(c=>(c.y+c.y2)/2)),mean(line.map(c=>(c.x+c.x2)/2))];
    const keyed=lines.map(line=>({line,key:position(line)}));
    keyed.sort((a,b)=>a.key[0]-b.key[0]||a.key[1]-b.key[1]);
    return mergeLines(keyed.map(k=>k.line)).filter(line=>line.length).map((line,i)=>({id:firstId+i,name:'fallback_line',confidence:1,
      box:box(Math.min(...line.map(c=>c.x)),Math.min(...line.map(c=>c.y)),Math.max(...line.map(c=>c.x2)),Math.max(...line.map(c=>c.y2)))}));
  }
  // --- geometry
  function iouFirst(a,b){
    const left=Math.max(a.x,b.x),low=Math.max(a.y,b.y),right=Math.min(a.x2,b.x2),top=Math.min(a.y2,b.y2);
    if(right<=left||top<=low)return 0;
    const area=(a.x2-a.x)*(a.y2-a.y);
    return area<=0?0:(right-left)*(top-low)/area;
  }
  function yTrueIou(a,b){
    const low=Math.max(a.y,b.y),top=Math.min(a.y2,b.y2);
    if(top<=low)return 0;
    const h1=a.y2-a.y,h2=b.y2-b.y;
    return h1<=0?0:(top-low)/Math.min(h1,h2);
  }
  function layoutOf(char,layouts){
    const v=char.visual,area=(v.x2-v.x)*(v.y2-v.y);
    if(!(area>0))return null;
    let best=null,bestPriority=Infinity,bestIou=-1;
    for(const layout of layouts){
      const b=layout.box;
      // The index finds what touches the character; only real overlap counts.
      const inter=Math.max(0,Math.min(v.x2,b.x2)-Math.max(v.x,b.x))*Math.max(0,Math.min(v.y2,b.y2)-Math.max(v.y,b.y));
      if(!(inter>0))continue;
      const iou=inter/area;
      const at=LAYOUT_PRIORITY.indexOf(layout.name),priority=at<0?LAYOUT_PRIORITY.length:at;
      if(priority<bestPriority||priority===bestPriority&&iou>bestIou){best=layout;bestPriority=priority;bestIou=iou;}
    }
    return best;
  }
  // --- text of a run of characters
  const isChar=value=>value&&typeof value==='object';
  function isNewline(prev,curr){
    if(!prev)return false;
    const width=Math.max(curr.box.x2-curr.box.x,prev.box.x2-prev.box.x);
    const should=curr.box.y2<prev.box.y||curr.box.x2<prev.box.x-width*10;
    if(should&&(curr.cid==null||prev.cid==null))return false;
    return should;
  }
  function medianGap(chars){
    const distances=[];
    for(let i=0;i<chars.length-1;i++){
      if(!(isChar(chars[i])&&isChar(chars[i+1])))continue;
      const d=chars[i+1].box.x-chars[i].box.x2;
      if(d>1)distances.push(d);
    }
    const distinct=[...new Set(distances)].sort((a,b)=>a-b);
    return !distinct.length?1:distinct.length===1?distinct[0]:distinct[1];
  }
  const nfkc=text=>text.normalize('NFKC');
  function unicodeString(chars){
    const median=medianGap(chars),parts=[];
    for(let i=0;i<chars.length;i++){
      if(!isChar(chars[i])){parts.push(chars[i]);continue;}
      parts.push(nfkc(chars[i].unicode).replace(/[\s\x1c-\x1f\x85]+/gu,' '));
      if(chars[i].unicode===' ')continue;
      if(i<chars.length-1&&isChar(chars[i+1])){
        const d=chars[i+1].box.x-chars[i].box.x2;
        if(d>=median||isNewline(chars[i],chars[i+1]))parts.push(' ');
      }
    }
    return nfkc(parts.join('')).replace(/[\s\x1c-\x1f\x85]+/gu,' ').replace(/^[\s\x1c-\x1f\x85]+|[\s\x1c-\x1f\x85]+$/gu,'');
  }
  // --- paragraphs
  function charsOf(comp){return comp.chars||[];}
  function lineComp(chars){
    const v=chars.map(c=>c.visual);
    return {kind:'line',chars,box:box(Math.min(...v.map(b=>b.x)),Math.min(...v.map(b=>b.y)),Math.max(...v.map(b=>b.x2)),Math.max(...v.map(b=>b.y2)))};
  }
  function updateParagraph(p,withText=false){
    if(!p.comps.length)return;
    const chars=[];
    for(const comp of p.comps){
      if(comp.kind==='line'||comp.kind==='formula')chars.push(...comp.chars);
      else if(comp.kind==='char')chars.push(comp.char);
    }
    if(withText&&chars.length)p.unicode=unicodeString(chars);
    if(!chars.length)return;
    const v=chars.map(c=>c.visual);
    p.box=box(Math.min(...v.map(b=>b.x)),Math.min(...v.map(b=>b.y)),Math.max(...v.map(b=>b.x2)),Math.max(...v.map(b=>b.y2)));
    p.vertical=chars[0].vertical;p.xobj=chars[0].xobj;p.firstLineIndent=false;
    if(p.comps[0].kind==='line'&&p.comps[0].chars[0].visual.x-p.box.x>1)p.firstLineIndent=true;
  }
  function groupIntoParagraphs(page){
    const paragraphs=[],skip=[],areas=page.chars.map(c=>(c.visual.x2-c.visual.x)*(c.visual.y2-c.visual.y)).sort((a,b)=>a-b);
    let medianArea=0;
    if(areas.length){const mid=areas.length>>1;medianArea=areas.length%2===1?areas[mid]:(areas[mid-1]+areas[mid])/2;}
    let current=null,currentLayout=null;
    for(const char of page.chars){
      const layout=layoutOf(char,page.layouts);
      char.formulaLayout=null;
      if(!(layout&&TEXT_LAYOUTS.has(layout.name))||['(cid:122)','(cid:123)','(cid:124)','(cid:125)'].includes(char.unicode)){skip.push(char);continue;}
      const area=(char.visual.x2-char.visual.x)*(char.visual.y2-char.visual.y),small=area<medianArea*.05;
      let fresh=false;
      if(!current)fresh=true;
      else if(!(small&&current.comps.length&&layout.id===currentLayout.id)){
        if(layout.id!==currentLayout.id&&!/^[\s\x1c-\x1f\x85]+/u.test(char.unicode)||current.comps.length&&current.comps.at(-1).char.xobj!==char.xobj||BULLET.test(char.unicode)&&!current.comps.length)fresh=true;
      }
      if(fresh){currentLayout=layout;current={comps:[],layoutId:layout.id,label:layout.name,box:null,vertical:false,xobj:null,unicode:'',firstLineIndent:false};paragraphs.push(current);}
      current.comps.push({kind:'char',char});
    }
    page.chars=skip;
    for(const p of paragraphs)updateParagraph(p);
    return paragraphs;
  }
  function splitIntoLines(p){
    if(!p.comps.length)return;
    const all=[],other=[];
    for(const comp of p.comps){if(comp.kind==='char')all.push(comp.char);else other.push(comp);}
    if(!all.length)return;
    const bounds=all.map(char=>({char,y1:char.visual.y,y2:char.visual.y2}));
    const low=Math.min(...bounds.map(b=>b.y1)),high=Math.max(...bounds.map(b=>b.y2));
    const single=()=>{p.comps=[lineComp(all),...other];updateParagraph(p);};
    if(high-low<5)return single();
    const step=.25,f=Math.fround,m=Math.ceil((high-low)/step);
    const hist=new Int32Array(Math.max(0,m)+1);
    if(m>0)for(const b of bounds){
      // Single precision here, as BabelDOC keeps these bounds in float32.
      const start=Math.floor(f(f(f(high)-f(b.y2))/step));
      let end=Math.floor(f(f(f(high)-f(b.y1))/step))+1;end=Math.min(m,Math.max(0,end));
      hist[start>=0?start:hist.length+start]+=1;hist[end]-=1;
    }
    const gaps=[];let inGap=false,gapStart=0,count=0;
    for(let i=0;i<Math.max(0,m);i++){
      count+=hist[i];
      if(count<1&&!inGap){inGap=true;gapStart=i;}
      else if(count>=1&&inGap){inGap=false;gaps.push(gapStart);}
    }
    if(inGap)gaps.push(gapStart);
    if(!gaps.length)return single();
    const separators=gaps.map(i=>high-i*step).sort((a,b)=>b-a),lines=Array.from({length:separators.length+1},()=>[]);
    for(const b of bounds){
      const centre=(b.y1+b.y2)/2;let at=0;
      for(const sep of separators){if(centre>sep)break;at++;}
      lines[at].push(b.char);
    }
    p.comps=[...lines.filter(l=>l.length).map(lineComp),...other];
    updateParagraph(p);
  }
  function spaceChar(after,boxValue){return {style:after.style,box:boxValue,unicode:' ',cid:null,advance:boxValue.x2-boxValue.x,visual:boxValue,vertical:false,xobj:undefined,renderOrder:undefined};}
  function addSpacesToList(chars){
    if(!chars.length)return;
    const median=medianGap(chars);
    for(let i=0;i<chars.length-1;){
      const curr=chars[i],next=chars[i+1];let d=next.box.x-curr.box.x2;
      if(d>=median||isNewline(curr,next)){
        if(d<0)d=-d;
        chars.splice(i+1,0,spaceChar(curr,box(curr.box.x2,curr.box.y,curr.box.x2+Math.min(d,median),curr.box.y2)));
        i+=2;
      }else i++;
    }
  }
  function addSpaces(p){
    for(const comp of p.comps)if(comp.kind==='line'||comp.kind==='formula'||comp.kind==='same')addSpacesToList(comp.chars);
    for(let i=0;i<p.comps.length-1;i++){
      const a=p.comps[i],b=p.comps[i+1],last=a.kind==='char'?a.char:a.chars?.at(-1),first=b.kind==='char'?b.char:b.chars?.[0];
      if(!last||!first)continue;
      const d=first.box.x-last.box.x2;
      if(d>1){const s=box(last.box.x2,last.box.y,last.box.x2+d,last.box.y2);if(a.chars)a.chars.push(spaceChar(last,s));}
    }
  }
  function paragraphSpacing(p){
    if(!p.comps.length)return;
    const out=[];
    for(const comp of p.comps){
      if(comp.kind!=='line'){out.push(comp);continue;}
      if(!comp.chars.map(c=>c.unicode).join('').replace(/^[\s\x1c-\x1f\x85]+|[\s\x1c-\x1f\x85]+$/gu,''))continue;
      const kept=[];
      for(const c of comp.chars){if(!isSpaceChar(c.unicode))kept.push(c);else if(kept.length)kept.push(c);}
      while(kept.length&&isSpaceChar(kept.at(-1).unicode))kept.pop();
      if(kept.length)out.push(lineComp(kept));
    }
    p.comps=out;updateParagraph(p);
  }
  function medianLineWidth(paragraphs){
    const widths=[];
    for(const p of paragraphs)for(const comp of p.comps)if(comp.kind==='line')widths.push(comp.box.x2-comp.box.x);
    if(!widths.length)return 0;
    widths.sort((a,b)=>a-b);const mid=widths.length>>1;
    return widths.length%2===0?(widths[mid-1]+widths[mid])/2:widths[mid];
  }
  function independentParagraphs(paragraphs,median,options){
    for(let i=0;i<paragraphs.length;i++){
      const p=paragraphs[i];
      if(p.comps.length<=1)continue;
      for(let j=1;j<p.comps.length;j++){
        const prev=p.comps[j-1];
        if(prev.kind!=='line')continue;
        const width=prev.box.x2-prev.box.x,text=prev.chars.map(c=>c.unicode).join('');
        const current=p.comps[j],first=current.kind==='line'?current.chars[0]:null;
        const contents=/\.{20,}/.test(text),short=options.splitShortLines&&width<median*options.shortLineSplitFactor,bullet=first&&BULLET.test(first.unicode);
        if(contents||short||bullet){
          const q={comps:p.comps.slice(j),layoutId:p.layoutId,label:p.label,box:box(0,0,0,0),vertical:false,xobj:null,unicode:'',firstLineIndent:false};
          p.comps=p.comps.slice(0,j);updateParagraph(p);updateParagraph(q);paragraphs.splice(i+1,0,q);
          break;
        }
      }
    }
  }
  function asciiText(p){const parts=[];for(const comp of p.comps){if(comp.kind==='line')for(const c of comp.chars)parts.push(c.unicode);else if(comp.kind==='char')parts.push(comp.char.unicode);}return parts.join('');}
  function digitsOrSpaces(p){
    const text=asciiText(p);if(!text)return true;
    let digit=false;
    for(const c of text){
      if(c>='0'&&c<='9'){digit=true;continue;}
      if(isSpaceChar(c))continue;
      return false;
    }
    return digit||!text.replace(/^[\s\x1c-\x1f\x85]+|[\s\x1c-\x1f\x85]+$/gu,'');
  }
  function mergeLineNumbers(paragraphs){
    if(paragraphs.length<3)return;
    for(let i=0;i<paragraphs.length-2;){
      const a=paragraphs[i];let j=i+1,saw=false;
      while(j<paragraphs.length&&digitsOrSpaces(paragraphs[j])){saw=true;j++;}
      if(saw&&j<paragraphs.length){
        const c=paragraphs[j];
        if(a.layoutId!=null&&c.layoutId!=null&&a.layoutId===c.layoutId&&a.xobj!=null&&c.xobj!=null&&a.xobj===c.xobj){a.comps.push(...c.comps);updateParagraph(a);paragraphs.splice(j,1);continue;}
      }
      i++;
    }
  }
  function fixOverlaps(paragraphs){
    if(paragraphs.length<2)return;
    const limit=paragraphs.length*paragraphs.length,overlap=(a,b)=>a.x<b.x2&&a.x2>b.x&&a.y<b.y2&&a.y2>b.y,contained=(a,b)=>a.y>=b.y&&a.y2<=b.y2||b.y>=a.y&&b.y2<=a.y2;
    for(let pass=0;pass<limit;pass++){
      let found=false;
      for(let i=0;i<paragraphs.length;i++)for(let j=i+1;j<paragraphs.length;j++){
        const p1=paragraphs[i],p2=paragraphs[j];
        if(!p1.box||!p2.box||p1.xobj!==p2.xobj||!overlap(p1.box,p2.box)||contained(p1.box,p2.box))continue;
        const start=Math.max(p1.box.y,p2.box.y),height=Math.min(p1.box.y2,p2.box.y2)-start,width=Math.min(p1.box.x2,p2.box.x2)-Math.max(p1.box.x,p2.box.x);
        if(!(height>1e-6&&width>1e-6))continue;
        found=true;
        let lower,higher;
        if(p1.box.y2>p2.box.y&&p1.box.y<p2.box.y){lower=p1;higher=p2;}
        else if(p1.box.y2<p2.box.y2){lower=p1;higher=p2;}
        else{lower=p2;higher=p1;}
        const mid=start+height/2;
        if(mid>higher.box.y&&mid<lower.box.y2){higher.box.y=mid+1;lower.box.y2=mid-1;}
      }
      if(!found)break;
    }
  }
  function renderOrderOf(p){
    let least=Infinity;
    for(const comp of p.comps){
      const chars=comp.kind==='char'?[comp.char]:comp.kind==='line'||comp.kind==='formula'?comp.chars:[];
      for(const c of chars)if(c.renderOrder!=null&&c.renderOrder<least)least=c.renderOrder;
    }
    if(least!==Infinity)p.renderOrder=least;
  }
  function findParagraphs(page,options={}){
    const settings={splitShortLines:false,shortLineSplitFactor:.8,...options};
    const paragraphs=groupIntoParagraphs(page);
    for(const p of paragraphs)splitIntoLines(p);
    for(const p of paragraphs){addSpaces(p);paragraphSpacing(p);updateParagraph(p);}
    independentParagraphs(paragraphs,medianLineWidth(paragraphs),settings);
    mergeLineNumbers(paragraphs);
    for(const p of paragraphs)updateParagraph(p,true);
    fixOverlaps(paragraphs);
    for(const p of paragraphs)renderOrderOf(p);
    page.paragraphs=paragraphs;
    return paragraphs;
  }
  // --- formulas
  function hasChar(text){
    const points=Array.from(text);
    if(points.length!==1)return false;
    const code=points[0].codePointAt(0),ranges=data().COVERAGE;
    let low=0,high=(ranges.length>>1)-1;
    while(low<=high){const mid=(low+high)>>1;if(code<ranges[mid*2])high=mid-1;else if(code>ranges[mid*2+1])low=mid+1;else return true;}
    return false;
  }
  const FORMULA_CATEGORY=/^[\p{Mn}\p{Sk}\p{Sm}\p{Zl}\p{Zp}\p{Zs}\p{Co}]/u;
  function isStartChar(text){
    if(!text)return false;
    if(text.includes('(cid:'))return true;
    if(!hasChar(text)){
      const points=Array.from(text);
      return !(points.length>1&&points.every(hasChar));
    }
    const first=text.codePointAt(0);
    if(text!==' '&&(FORMULA_CATEGORY.test(text)||first>=0x370&&first<0x400))return true;
    return /^[0-9\[\]•]/u.test(text);
  }
  const isMiddleChar=text=>isStartChar(text)||text.startsWith(',');
  let fontPatterns=null;
  function isFormulaFont(name){
    if(!fontPatterns){const p=data().FORMULA_FONTS;fontPatterns={precise:new RegExp(p.precise,'u'),text:new RegExp(p.text,'u'),broad:new RegExp('^(?:'+p.broad+')','u')};}
    const font=String(name||'').split('+').at(-1);
    if(!font)return false;
    if(fontPatterns.precise.test(font))return true;
    if(fontPatterns.text.test(font))return false;
    return fontPatterns.broad.test(font);
  }
  function updateFormula(f){
    const v=f.chars.map(c=>c.visual),real=f.chars.filter(c=>c.cid!=null).map(c=>c.visual),h=real.length?real:v;
    f.box=box(Math.min(...v.map(b=>b.x)),Math.min(...h.map(b=>b.y)),Math.max(...v.map(b=>b.x2)),Math.max(...h.map(b=>b.y2)));
    f.xOffset=f.xOffset||0;f.yOffset=f.yOffset||0;
  }
  function formulaComp(chars,lineId,corner=false){const f={kind:'formula',chars,lineId,isCornerMark:corner,xOffset:0,yOffset:0};updateFormula(f);return f;}
  function classifyLine(comp,formulaFonts,bulletSoFar){
    const tags=[],corners=[],chars=comp.chars;let bullet=bulletSoFar,inFormula=false,inCorner=false;
    for(let i=0;i<chars.length;i++){
      const c=chars[i];
      const startOfSegment=i===0||tags.length>0&&tags.at(-1)!==inFormula;
      if(!bullet&&startOfSegment&&BULLET.test(c.unicode))bullet=true;
      const v=c.visual,b=c.box;
      let formula=c.formulaLayout||isStartChar(c.unicode)&&!inFormula||isMiddleChar(c.unicode)&&inFormula||formulaFonts.has(c.style.font)||c.vertical||b.x>v.x2||b.x2<v.x||b.y>v.y2||b.y2<v.y;
      formula=Boolean(formula);
      const previous=i>0?chars[i-1]:null,next=i<chars.length-1?chars[i+1]:null,space=isSpaceChar(c.unicode),prevSpace=previous?isSpaceChar(previous.unicode):false;
      const corner=previous&&!space&&!prevSpace&&!bullet&&c.style.size<previous.style.size*.79&&!inCorner
        ||previous&&!space&&!prevSpace&&!bullet&&c.style.size<previous.style.size*1.1&&inCorner
        ||!previous&&next&&!space&&!prevSpace&&!bullet&&c.style.size<next.style.size*.79&&!inCorner;
      formula=formula||Boolean(corner);
      if(c.unicode===' ')formula=inFormula;
      if(formula!==inFormula)inFormula=formula;
      inCorner=Boolean(corner);
      tags.push(formula);corners.push(Boolean(corner));
    }
    return {tags,corners,bullet};
  }
  function groupClassified(chars,tags,corners,lineIndex){
    const out=[];let current=[],tag=tags[0],flags=[];
    const close=()=>{out.push(tag?formulaComp(current,lineIndex,flags.some(Boolean)):lineComp(current));};
    chars.forEach((c,i)=>{
      if(tags[i]===tag){current.push(c);flags.push(corners[i]);}
      else{close();current=[c];tag=tags[i];flags=[corners[i]];}
    });
    if(current.length)close();
    return out;
  }
  function splitByComma(f){
    const out=[];let current=[],level=0;
    for(const c of f.chars){
      if(LEFT_BRACKET.has(c.unicode)){level++;current.push(c);}
      else if(RIGHT_BRACKET.has(c.unicode)){level=Math.max(0,level-1);current.push(c);}
      else if(c.unicode===','&&level===0){if(current.length){out.push([current,c]);current=[];}}
      else current.push(c);
    }
    if(current.length)out.push([current,null]);
    return out;
  }
  function commaFormulas(p){
    const out=[];
    for(const comp of p.comps){
      if(comp.kind==='formula'){
        const text=comp.chars.map(c=>c.unicode).join('');
        if(text.includes(',')&&text.replace(/[0-9\[\],\s\x1c-\x1f\x85]/gu,'')){
          for(const [chars,comma] of splitByComma(comp)){
            if(chars.length){
              out.push(formulaComp(chars,comp.lineId));
              if(comma)out.push(lineComp([comma]));
            }
          }
          continue;
        }
      }
      out.push(comp);
    }
    p.comps=out;
  }
  const xContained=(a,b)=>a.x>=b.x&&a.x2<=b.x2||b.x>=a.x&&b.x2<=a.x2;
  const yIntersects=(a,b)=>!(a.y2<b.y-1||b.y2<a.y-1);
  const xAdjacent=(a,b)=>!(a.x2<b.x||b.x2<a.x)||Math.abs(a.x2-b.x)<=2||Math.abs(b.x2-a.x)<=2;
  function yIou(a,b){
    const inter=Math.max(0,Math.min(a.y2,b.y2)-Math.max(a.y,b.y)),union=a.y2-a.y+(b.y2-b.y)-inter;
    return union<=0?0:inter/union;
  }
  function mergeFormulas(p){
    let merged=true;
    while(merged){
      merged=false;
      for(let i=0;i<p.comps.length&&!merged;i++){
        const a=p.comps[i];if(a.kind!=='formula')continue;
        for(let j=i+1;j<p.comps.length;j++){
          const b=p.comps[j];if(b.kind!=='formula')continue;
          const should=a.lineId===b.lineId&&(j===i+1&&(xContained(a.box,b.box)&&yIntersects(a.box,b.box)||xAdjacent(a.box,b.box)&&yIou(a.box,b.box)>.5)||iouFirst(a.box,b.box)>.8||iouFirst(b.box,a.box)>.8);
          if(should){p.comps[i]=formulaComp([...a.chars,...b.chars],a.lineId);p.comps.splice(j,1);merged=true;break;}
        }
      }
    }
  }
  function formulaOffsets(p){
    p.comps.forEach((comp,i)=>{
      if(comp.kind!=='formula')return;
      let left=null,right=null,leftIou=0,rightIou=0;
      if(i>0){
        const near=p.comps[i-1];
        if(near.kind==='line')for(let k=near.chars.length-1;k>=0;k--){
          const c=near.chars[k];if(!c.cid)continue;
          leftIou=yTrueIou(comp.box,c.box);
          if(leftIou>.6){left=c;break;}
        }
      }
      if(i+1<p.comps.length){
        const near=p.comps[i+1];
        if(near.kind==='line')for(const c of near.chars){
          if(!c.cid)continue;
          rightIou=yTrueIou(comp.box,c.box);
          if(rightIou>.6){right=c;break;}
        }
      }
      if(left&&right){if(leftIou<rightIou)left=null;else if(rightIou<leftIou)right=null;}
      comp.xOffset=left?comp.box.x-left.box.x2:0;
      if(Math.abs(comp.xOffset)<.1)comp.xOffset=0;
      if(comp.xOffset>10)comp.xOffset=0;
      if(comp.xOffset<-5)comp.xOffset=0;
      comp.yOffset=left?comp.box.y-left.box.y:right?comp.box.y-right.box.y:0;
      if(Math.abs(comp.yOffset)<.1)comp.yOffset=0;
    });
  }
  function translatableFormulas(p){
    p.comps=p.comps.map(comp=>{
      if(comp.kind!=='formula'||comp.isCornerMark)return comp;
      if(comp.yOffset>.1)return comp;
      return /^[0-9, .]+$/u.test(comp.chars.map(c=>c.unicode).join(''))?lineComp(comp.chars):comp;
    });
  }
  // --- what belongs to a formula besides its characters (fraction bars, roots)
  function containedInFormula(element,formula){
    return iouFirst(element,box(formula.x-2,formula.y-2,formula.x2+2,formula.y2+2))>=.95;
  }
  function collectCurves(page){
    const all=[];
    for(const p of page.paragraphs)for(const comp of p.comps)if(comp.kind==='formula'){comp.curves=[];all.push([comp,p.xobj]);}
    if(!all.length)return;
    const left=[];
    for(const curve of page.curves||[]){
      let best=null,bestPriority=3,bestScore=-Infinity;
      if(curve.box)all.forEach(([formula,xobj])=>{
        if(!formula.box||xobj!=null&&curve.xobj!==xobj)return;
        const iou=iouFirst(curve.box,formula.box);
        let priority,score;
        if(iou>=.95){priority=1;score=iou;}
        else if(containedInFormula(curve.box,formula.box)){
          const b=curve.box,f=formula.box,dx=b.x2<f.x?f.x-b.x2:b.x>f.x2?b.x-f.x2:0,dy=b.y2<f.y?f.y-b.y2:b.y>f.y2?b.y-f.y2:0,distance=Math.sqrt(dx*dx+dy*dy);
          priority=2;score=.5+.4*Math.max(0,1-distance/100);
        }else return;
        if(priority<bestPriority||priority===bestPriority&&score>bestScore){best=formula;bestPriority=priority;bestScore=score;}
      });
      if(best)best.curves.push(curve);else left.push(curve);
    }
    page.curves=left;
  }
  // --- styles
  const sameState=(a,b)=>a==null||b==null?a===b:a===b;
  const sameStyle=(a,b)=>a==null||b==null?a===b:a.font===b.font&&Math.abs(a.size-b.size)<.02&&sameState(a.state,b.state);
  function modeOf(values){const counts=new Map();for(const v of values)counts.set(v,(counts.get(v)||0)+1);let best=null,most=0;for(const [v,n] of counts)if(n>most){best=v;most=n;}return best;}
  function baseStyle(p){
    const styles=[];
    for(const comp of p.comps)if(comp.kind==='line')for(const c of comp.chars)styles.push(c.style);
    if(!styles.length)return null;
    let base=styles[0];
    for(const style of styles.slice(1)){
      if(base==null||base.size==null){base=style;continue;}
      if(style==null||style.size==null)continue;
      base={font:base.font===style.font?base.font:null,size:Math.abs(base.size-style.size)<.02?base.size:null,state:base.state===style.state?base.state:null};
    }
    base={...base};
    if(base.font==null)base.font=modeOf(styles.map(s=>s.font));
    if(base.size==null)base.size=modeOf(styles.map(s=>s.size));
    return base;
  }
  function sameStyleComp(chars,style){
    const v=chars.map(c=>c.visual);
    return {kind:'same',chars,style,box:box(Math.min(...v.map(b=>b.x)),Math.min(...v.map(b=>b.y)),Math.max(...v.map(b=>b.x2)),Math.max(...v.map(b=>b.y2)))};
  }
  function pageStyles(p){
    if(!p.comps.length)return;
    p.style=baseStyle(p);
    const out=[];let chars=[],style=null;
    for(const comp of p.comps){
      if(comp.kind==='formula'){
        if(chars.length){out.push(sameStyleComp(chars,style));chars=[];}
        out.push(comp);continue;
      }
      if(comp.kind!=='line'){out.push(comp);continue;}
      for(const c of comp.chars){
        if(style==null){style=c.style;chars.push(c);}
        else if(sameStyle(c.style,style))chars.push(c);
        else{if(chars.length)out.push(sameStyleComp(chars,style));chars=[c];style=c.style;}
      }
    }
    if(chars.length)out.push(sameStyleComp(chars,style));
    p.comps=out;
  }
  function stylesAndFormulas(page){
    const formulaFonts=new Set(Object.entries(page.fonts||{}).filter(([,name])=>isFormulaFont(name)).map(([id])=>id));
    for(const p of page.paragraphs){
      const out=[];let bullet=false;
      p.comps.forEach((comp,lineIndex)=>{
        if(comp.kind!=='line'||!comp.chars.length){out.push(comp);return;}
        const result=classifyLine(comp,formulaFonts,bullet);bullet=result.bullet;
        out.push(...groupClassified(comp.chars,result.tags,result.corners,lineIndex));
      });
      p.comps=out;
    }
    for(const p of page.paragraphs){commaFormulas(p);mergeFormulas(p);formulaOffsets(p);translatableFormulas(p);}
    for(const p of page.paragraphs)for(const comp of p.comps)if(comp.kind==='formula')updateFormula(comp);
    collectCurves(page);
    for(const p of page.paragraphs){for(const comp of p.comps)if(comp.kind==='formula')updateFormula(comp);formulaOffsets(p);for(const comp of p.comps)if(comp.kind==='formula')updateFormula(comp);pageStyles(p);}
    return page.paragraphs;
  }
  function analyzePage(page,options){
    page.layouts=[...page.layouts,...fallbackLines(page.chars,page.layouts.length+1)];
    findParagraphs(page,options);
    return stylesAndFormulas(page);
  }
  global.TwinTextTypesetStructure=Object.freeze({pageLayoutFromModel,fallbackLines,findParagraphs,stylesAndFormulas,analyzePage,unicodeString,isFormulaFont,hasChar,isStartChar});
})(this);
