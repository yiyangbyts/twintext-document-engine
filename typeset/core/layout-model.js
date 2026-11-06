// Typeset engine, page layout. Ported from BabelDOC 0.6.4 docvision/doclayout.py and format/pdf/document_il/utils/raster_geometry.py.
// Copyright (C) 2026 TwinText; BabelDOC by its authors. SPDX-License-Identifier: AGPL-3.0-only
// Pure arithmetic: runs in the plugin, in the worker and in node. Page coordinates are points from the page's top left.
(function(global){
  'use strict';
  const NAMES=Object.freeze(['title','plain text','abandon','figure','figure_caption','table','table_caption','table_footnote','isolate_formula','formula_caption']);
  const SIDE=1024,DEFAULT_DPI=72,CONFIDENCE=.25,PAD=114;
  // Python's round(): halves go to the even neighbour.
  function round(value){
    const low=Math.floor(value),rest=value-low;
    return rest<.5?low:rest>.5?low+1:low%2===0?low:low+1;
  }
  // The page is drawn at 72 dpi unless that is over twice the model's side, then resized to fit the side and padded to its middle.
  function plan(pageWidth,pageHeight){
    if(!(pageWidth>0&&pageHeight>0))throw new Error('Invalid page size');
    const long=Math.max(pageWidth,pageHeight),dpi=long*DEFAULT_DPI/72>2*SIDE?Math.max(1,Math.floor(SIDE*72/long)):DEFAULT_DPI;
    const pixelWidth=Math.max(1,Math.ceil(pageWidth*dpi/72)),pixelHeight=Math.max(1,Math.ceil(pageHeight*dpi/72));
    const ratio=Math.min(SIDE/pixelHeight,SIDE/pixelWidth),width=round(pixelWidth*ratio),height=round(pixelHeight*ratio);
    return {pageWidth,pageHeight,dpi,pixelWidth,pixelHeight,width,height,left:Math.floor((SIDE-width)/2),top:Math.floor((SIDE-height)/2)};
  }
  // Interleaved RGB to the model's input: planar blue, green, red in 0..1, as BabelDOC feeds it.
  function tensor(rgb,layout){
    const {width,height,left,top}=layout,pixels=SIDE*SIDE,out=new Float32Array(pixels*3).fill(PAD/255);
    if(rgb.length!==width*height*3)throw new Error('Unexpected page raster length');
    for(let y=0;y<height;y++)for(let x=0;x<width;x++){
      const from=(y*width+x)*3,to=(y+top)*SIDE+x+left;
      out[to]=rgb[from+2]/255;out[pixels+to]=rgb[from+1]/255;out[pixels*2+to]=rgb[from]/255;
    }
    return out;
  }
  // Rows of [x0,y0,x1,y1,confidence,class] on the padded square, back to page points.
  function decode(rows,layout){
    const {pixelWidth,pixelHeight,pageWidth,pageHeight}=layout,gain=Math.min(SIDE/pixelHeight,SIDE/pixelWidth);
    const padX=round((SIDE-pixelWidth*gain)/2-.1),padY=round((SIDE-pixelHeight*gain)/2-.1),out=[];
    const scaleX=pixelWidth/pageWidth,scaleY=pixelHeight/pageHeight;
    for(let at=0;at+6<=rows.length;at+=6){
      const confidence=rows[at+4];
      if(!(confidence>CONFIDENCE))continue;
      out.push({name:NAMES[rows[at+5]|0],confidence,
        x0:(rows[at]-padX)/gain/scaleX,y0:(rows[at+1]-padY)/gain/scaleY,
        x1:(rows[at+2]-padX)/gain/scaleX,y1:(rows[at+3]-padY)/gain/scaleY});
    }
    return out;
  }
  // Quadrants in PDF user space (y up). Each reading frame has a positive width
  // and height and a transform back to the printed page, including its offset.
  function readingFrame(turn,width,height){
    if(turn===90)return {toLocal:[0,-1,1,0,0,width],toPage:[0,1,-1,0,width,0]};
    return {toLocal:[0,1,-1,0,height,0],toPage:[0,-1,1,0,0,height]};
  }
  function transformBox(b,[a,c,d,e,x,y]){
    const x0=a*b.x+d*b.y+x,x1=a*b.x2+d*b.y2+x;
    const y0=c*b.x+e*b.y+y,y1=c*b.x2+e*b.y2+y;
    return {x:Math.min(x0,x1),y:Math.min(y0,y1),x2:Math.max(x0,x1),y2:Math.max(y0,y1)};
  }
  global.TwinTextTypesetLayoutModel=Object.freeze({NAMES,SIDE,round,plan,tensor,decode,readingFrame,transformBox});
})(this);
