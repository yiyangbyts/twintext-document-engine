"""Bounded MuPDF OCR: hidden text; native opaque source for bitmap fonts.

Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
Imports only the standard library and PyMuPDF, including on Windows spawn.
"""
from __future__ import annotations
import collections,gc,hashlib,json,math,os,sys
from pathlib import Path
import pymupdf

PIXEL_BUDGET=8_000_000

def supplement_titles(page,words,dpi,tessdata):
    """Retry large bitmap headings that full-page OCR classified as artwork."""
    import statistics
    fonts={f[3] for f in page.get_fonts() if f[2]=='Type3'}
    if not fonts:return words
    glyphs=[(c[2][0],c[2][1],c[3][2]-c[3][0]) for s in page.get_texttrace() if s['font'] in fonts for c in s['chars'] if c[3][2]>c[3][0]]
    if not glyphs:return words
    typical=statistics.median(g[2] for g in glyphs);rows=[]
    for glyph in sorted((g for g in glyphs if g[1]<page.rect.height*.2 and g[2]>typical*1.35),key=lambda g:g[1]):
        row=next((r for r in rows if abs(r[0][1]-glyph[1])<8),None)
        if row is None:rows.append([glyph])
        else:row.append(glyph)
    regions=[]
    for row in rows:
        if len(row)<8:continue
        if sum(any(w[0]-2<=g[0]+g[2]*.5<=w[2]+2 and w[1]-3<=g[1]<=w[3]+4 for w in words) for g in row)>=len(row)*.7:continue
        rect=pymupdf.Rect(min(g[0] for g in row)-3,min(g[1] for g in row)-3,max(g[0]+g[2] for g in row)+3,
            max(g[1] for g in row)+statistics.median(g[2] for g in row)*1.9)
        if regions and rect.y0-regions[-1].y1<12 and min(rect.x1,regions[-1].x1)>max(rect.x0,regions[-1].x0):regions[-1]|=rect
        else:regions.append(rect)
    for number,rect in enumerate(regions[:2]):
        rect&=page.rect
        if rect.width<page.rect.width*.35:continue
        contained=[g for g in glyphs if rect.contains(pymupdf.Point(g[0],g[1]))]
        covered=sum(any(w[0]-2<=g[0]+g[2]*.5<=w[2]+2 and w[1]-3<=g[1]<=w[3]+4 for w in words) for g in contained)
        if not contained or covered>=len(contained)*.7:continue
        pix=page.get_pixmap(dpi=dpi,clip=rect,alpha=False)
        with pymupdf.open(stream=pix.pdfocr_tobytes(language='eng',tessdata=tessdata),filetype='pdf') as crop:
            recovered=crop[0].get_text('words')
        if sum(sum(c.isalpha() for c in w[4]) for w in recovered)<12:continue
        words=[w for w in words if not rect.contains(pymupdf.Point((w[0]+w[2])/2,(w[1]+w[3])/2))]
        dx,dy=pix.x*72/dpi,pix.y*72/dpi
        words.extend((w[0]+dx,w[1]+dy,w[2]+dx,w[3]+dy,w[4],1000+number*100+w[5],w[6],w[7]) for w in recovered)
    return words

def text_layer(page,path,dpi,tessdata):
    """Write stable line metrics with real fonts, keeping recognition invisible.

    Tesseract's GlyphLessFont uses per-word anisotropic matrices and paints
    rectangles when a preserved formula is made visible. Do not expose it to
    native paragraph segmentation or drawing.
    """
    import unicodedata
    tp=page.get_textpage_ocr(language='eng',dpi=dpi,full=True,tessdata=tessdata)
    import statistics
    words=supplement_titles(page,tp.extractWORDS(),dpi,tessdata);lines=collections.defaultdict(list);blocks=collections.defaultdict(list)
    for word in words:lines[(word[5],word[6])].append(word)
    for (block,_),row in lines.items():blocks[block].append(row)
    sizes={}
    for block,rows in blocks.items():
        heights=[max(w[3] for w in row)-min(w[1] for w in row) for row in rows]
        bottoms=sorted(max(w[3] for w in row) for row in rows)
        pitch=[b-a for a,b in zip(bottoms,bottoms[1:]) if 4<b-a<50]
        sizes[block]=min(statistics.median(heights),statistics.median(pitch)/1.2) if len(pitch)>=2 else statistics.median(heights)
    with pymupdf.open() as layer:
        target=layer.new_page(width=page.rect.width,height=page.rect.height)
        font=pymupdf.Font('tiro');target.insert_font(fontname='TwinTextOCR',fontbuffer=font.buffer)
        for (block,_),row in lines.items():
            size=sizes[block]
            size=max(2,min(96,size))
            baseline=max(w[3] for w in row)-size*.2
            for x0,y0,x1,y1,text,*_ in row:
                text=unicodedata.normalize('NFKC',text)
                width=font.text_length(text,fontsize=size)
                if width<=0:continue
                point=pymupdf.Point(x0,baseline)
                # Per-word horizontal scaling is interpreted as a different
                # point size by native paragraph finding. Keep a stable font
                # size per OCR block and retain each word's original origin.
                target.insert_text(point,text+' ',fontname='TwinTextOCR',fontsize=size,render_mode=3)
        temporary=path.with_suffix('.tmp');layer.save(temporary,garbage=3,deflate=True);temporary.replace(path)
    return dict(empty=sum(sum(c.isalpha() for c in word[4]) for word in words)<60,boxes=[list(word[:4]) for word in words])

def write_json(path,value):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value),encoding='utf-8');temporary.replace(path)

def run(request):
    cache=Path(request['cache']);cache.mkdir(parents=True,exist_ok=True)
    report=Path(request['report']);result=dict(completed=0,ocrPages=[],fontRepairPages=[],unreadablePages=[],geometryFiles={},cachedPages=0,pixelBudget=PIXEL_BUDGET)
    # Tesseract fast model uses one CPU worker and bounded page raster buffers.
    os.environ['OMP_THREAD_LIMIT']='1'
    with pymupdf.open(request['source']) as pdf,pymupdf.open(request['source']) as original:
        for task in request['tasks']:
            index=task['index'];page=pdf[index];absolute=index+request['offset']
            revision=request['revision']
            key=hashlib.sha256(f"{request['document']}:{absolute}:{revision}:eng-fast-4.1.0:220".encode()).hexdigest()
            metadata=cache/(key+'.json');layer_file=cache/(key+'.pdf');data=None
            try:
                data=json.loads(metadata.read_text())
                if data['reason']!=task['reason']:data=None
                if data and not data.get('empty') and task['reason'] in ('image-text','bitmap-text') and hashlib.file_digest(layer_file.open('rb'),'sha256').hexdigest()!=data['sha256']:data=None
            except (OSError,ValueError,KeyError):data=None
            if data:result['cachedPages']+=1
            else:
                dpi=min(220,max(1,int(72*math.sqrt(PIXEL_BUDGET/max(1,page.rect.get_area())))))
                geometry=text_layer(page,layer_file,dpi,request['tessdata'])
                data=dict(reason=task['reason'],**geometry,sha256=hashlib.file_digest(layer_file.open('rb'),'sha256').hexdigest())
                write_json(metadata,data)
            if task['reason']=='bitmap-text':
                    # Keep the original page as one native, opaque Form. The
                    # parser reads the new OCR layer, never thousands of bad
                    # bitmap glyph metrics or unencoded character IDs.
                    before={x[0] for x in page.get_xobjects()}
                    page.show_pdf_page(page.rect,original,index)
                    wrapper=next(x for x in page.get_xobjects() if x[0] not in before and x[2]==0)
                    pdf.update_stream(wrapper[0],b'% TwinText opaque original page\n'+pdf.xref_stream(wrapper[0]))
                    pdf.xref_set_key(page.xref,'Resources',f'<< /XObject << /TwinTextOpaque {wrapper[0]} 0 R >> >>')
                    stream=pdf.get_new_xref();pdf.update_object(stream,'<<>>');pdf.update_stream(stream,b'q /TwinTextOpaque Do Q');page.set_contents(stream)
                    result['fontRepairPages'].append(absolute)
            if data.get('empty'):result['unreadablePages'].append(absolute)
            else:
                with pymupdf.open(layer_file) as layer:page.show_pdf_page(page.rect,layer,0)
                result['ocrPages'].append(absolute)
                result['geometryFiles'][str(index)]=str(metadata)
            result['completed']+=1;write_json(report,result);gc.collect()
        pdf.save(request['target'],garbage=3,deflate=True)
    write_json(report,result)

if __name__=='__main__':run(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
