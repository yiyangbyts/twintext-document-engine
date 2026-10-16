"""Inspect selected text layers and recover only deficient pages, off process.

Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib,json,re,subprocess,sys,threading,time
from pathlib import Path

REVISION='page-text-2.0.30-v14'
MODEL_SHA256='7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2'

def failure(code,message):
    error=RuntimeError(message);error.code=code;error.twintext_text_failure=True
    return error

def state():return dict(revision=REVISION,checkedPages=0,scanPages=[],ocrPages=[],fontRepairPages=[],unreadablePages=[],nonTextPages=[],bodyRequests=0)

def scanned_page(page):
    import pymupdf
    if not page.get_images(full=True):return False
    if sum((pymupdf.Rect(i['bbox'])&page.rect).get_area() for i in page.get_image_info())<page.rect.get_area()*.45:return False
    spans=page.get_texttrace();total=sum(len(s['chars']) for s in spans)
    return total>0 and sum(len(s['chars']) for s in spans if s['type']==3)>total*.8

def inspect_page(page):
    import pymupdf
    fonts=[f for f in page.get_fonts() if f[2]=='Type3']
    # Native parsing supplies the actual body-request gate. A vector page
    # without bitmap fonts or images cannot need this image OCR preflight.
    if not fonts and not page.get_images(full=True):return None
    body=pymupdf.Rect(0,page.rect.height*.065,page.rect.width,page.rect.height*.935)
    text=page.get_text('text',clip=body)
    letters=sum(c.isalpha() for c in text)
    bad=sum(ord(c)<32 and not c.isspace() or c=='\ufffd' for c in text)
    # A bitmap font may expose plausible ASCII codes with no relation to the
    # drawn glyphs. A count of letters alone cannot validate such a text layer.
    unencoded=any(page.parent.xref_get_key(f[0],'ToUnicode')[0]=='null' and
        len(re.findall(r'/a\d+\b',page.parent.xref_get_key(f[0],'Encoding/Differences')[1]))>=8 for f in fonts)
    if fonts and len(text)>20 and (unencoded or bad>20 or sum(len(w)==1 and w.isascii() and w.isalpha() for w in text.split())>len(text.split())*.35):return 'bitmap-text'
    if letters>=60 and bad<=max(20,letters*.2):return None
    if not page.get_images(full=True):return None
    image_area=0
    for image in page.get_image_info():
        image_area+=(pymupdf.Rect(image['bbox']) & body).get_area()
    if image_area>body.get_area()*.45 and (letters<60 or bad>max(20,letters*.2)):return 'image-text'
    return None

def prepare(pdf,folder,payload,progress=None,cancel_event=None):
    import pymupdf
    from native_batches import selected_pages
    quality=payload.get('_textQuality')
    if quality is None:return pdf
    source=Path(folder)/'text-source.pdf';target=Path(folder)/'text-recovered.pdf'
    with pymupdf.open(stream=pdf,filetype='pdf') as doc:
        pages=selected_pages(payload.get('pages'),len(doc));tasks=[]
        for index in pages:
            if cancel_event is not None and cancel_event.is_set():raise RuntimeError('Translation cancelled')
            reason=inspect_page(doc[index]);quality['checkedPages']+=1
            if reason in ('image-text','bitmap-text') or scanned_page(doc[index]):quality['scanPages'].append(index+payload.get('_pageOffset',0))
            if reason:tasks.append(dict(index=index,reason=reason))
    if not tasks:return pdf  # Identical bytes and native path for healthy PDFs.
    language=str(payload.get('sourceLanguage','en')).lower()
    if language not in ('en','en-us','en-gb','english','auto'):
        raise failure('document_ocr_language','The selected pages require OCR; the bundled OCR model supports English only.')
    model=Path(__file__).parent/'ocr-data/eng.traineddata'
    if not model.is_file() or hashlib.sha256(model.read_bytes()).hexdigest()!=MODEL_SHA256:
        raise failure('document_ocr_unavailable','The verified English OCR model is unavailable. Reinstall the current engine bundle.')
    source.write_bytes(pdf)
    request=Path(folder)/'ocr-request.json';report=Path(folder)/'ocr-report.json'
    request.write_text(json.dumps(dict(source=str(source),target=str(target),report=str(report),tasks=tasks,
        tessdata=str(model.parent),cache=str(payload.get('_ocrCache') or Path(folder)/'ocr-cache'),
        document=payload.get('_documentDigest') or hashlib.sha256(pdf).hexdigest(),offset=payload.get('_pageOffset',0),revision=REVISION)),encoding='utf-8')
    log=(Path(folder)/'ocr-worker.log').open('wb')
    options=dict(stdout=subprocess.DEVNULL,stderr=log)
    if sys.platform=='win32':options['creationflags']=subprocess.CREATE_NO_WINDOW
    # No BabelDOC, model or font-runtime imports in this child. Its OCR buffers
    # die on exit; there is never a raster queue or a process pool of OCR pages.
    try:process=subprocess.Popen([sys.executable,'-B',str(Path(__file__).with_name('ocr_worker.py')),str(request)],**options)
    except Exception:log.close();raise
    started=time.monotonic();last=-1
    try:
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():raise RuntimeError('Translation cancelled')
            if time.monotonic()-started>max(90,len(tasks)*45):raise failure('document_ocr_timeout','Page OCR did not finish within its time budget.')
            try:done=json.loads(report.read_text())['completed']
            except (OSError,ValueError,KeyError):done=0
            if done!=last and progress:
                progress(type='progress_update',stage='recovering-page-text',stage_current=done,stage_total=len(tasks));last=done
            if cancel_event is not None:cancel_event.wait(.1)
            else:time.sleep(.1)
        if process.returncode:
            raise failure('document_ocr_failed','Page text recovery failed; no untranslated document was marked complete. OCR worker exit code: '+str(process.returncode))
    finally:
        if process.poll() is None:process.kill();process.wait()
        log.close()
    result=json.loads(report.read_text())
    if '_ocrGeometry' in payload:
        for index,path in result.get('geometryFiles',{}).items():payload['_ocrGeometry'][int(index)]=json.loads(Path(path).read_text()).get('boxes',[])
    for key in ('ocrPages','fontRepairPages','unreadablePages'):quality[key].extend(result.get(key,[]))
    quality['ocrMilliseconds']=quality.get('ocrMilliseconds',0)+round((time.monotonic()-started)*1000)
    return target.read_bytes()

def is_body(paragraph):
    label=str(getattr(paragraph,'layout_label','')).lower()
    if any(x in label for x in ('header','footer','abandon','page_number','pagenumber','formula','figure','table')):return False
    text=re.sub(r'\(cid:\d+\)|</?b\d+>','',getattr(paragraph,'unicode','') or '')
    if re.search(r'copyright|all rights reserved|publishing group|^\s*[©®]',text,re.I):return False
    return sum(c.isalpha() for c in text)>=24

def merge_ocr_lines(page):
    """Join recovered lines within one native body region and paragraph indent.

    OCR words are independent PDF text operations. Keep columns, model region
    boundaries, heading/caption labels, paragraph indents and vertical gaps.
    """
    from collections import defaultdict
    from babeldoc.format.pdf.document_il.il_version_1 import Box
    groups=defaultdict(list)
    for position,p in enumerate(page.pdf_paragraph):
        if str(p.layout_label).lower() in ('plain text','text','body','paragraph') and p.layout_id is not None:
            groups[p.layout_id].append((position,p))
    removed=set()
    columns=[]
    for entries in groups.values():
        buckets=[]
        for entry in entries:
            box=entry[1].box;bucket=next((items for items in buckets if
                min(items[0][1].box.x2,box.x2)-max(items[0][1].box.x,box.x)>
                min(items[0][1].box.x2-items[0][1].box.x,box.x2-box.x)*.3),None)
            if bucket is None:buckets.append([entry])
            else:bucket.append(entry)
        columns.extend(buckets)
    for entries in columns:
        current=None;base_x=0
        for position,p in sorted(entries,key=lambda pair:(-pair[1].box.y2,pair[1].box.x)):
            size=(p.pdf_style.font_size or 10) if p.pdf_style else 10
            gap=current.box.y-p.box.y2 if current else 1000
            same_line=current and min(current.box.y2,p.box.y2)-max(current.box.y,p.box.y)>min(current.box.y2-current.box.y,p.box.y2-p.box.y)*.5
            indented=current and not same_line and p.box.x>base_x+max(4,size*.4)
            previous_size=(current.pdf_style.font_size or size) if current and current.pdf_style else size
            separate=current is None or gap>max(5,size*.65) or indented or p.box.x>current.box.x2+size*2 or abs(previous_size-size)>max(1,size*.2)
            if separate:current=p;base_x=p.box.x;continue
            current.pdf_paragraph_composition.extend(p.pdf_paragraph_composition)
            current.unicode=((current.unicode or '')+' '+(p.unicode or '')).strip()
            a,b=current.box,p.box;current.box=Box(x=min(a.x,b.x),y=min(a.y,b.y),x2=max(a.x2,b.x2),y2=max(a.y2,b.y2))
            base_x=min(base_x,p.box.x);removed.add(position)
    page.pdf_paragraph=[p for position,p in enumerate(page.pdf_paragraph) if position not in removed]

def align_ocr_geometry(page,words):
    """Use recognition boxes rather than surrogate font ink bounds on scans."""
    from babeldoc.format.pdf.document_il.il_version_1 import Box
    crop=(page.cropbox or page.mediabox).box
    rows={}
    for x0,y0,x1,y1 in words:
        box=Box(x=crop.x+x0,y=crop.y2-y1,x2=crop.x+x1,y2=crop.y2-y0)
        for key in range(int(box.y//8)-1,int(box.y2//8)+2):rows.setdefault(key,[]).append(box)
    for char in page.pdf_character:
        if char.pdf_style.font_id!='TwinTextOCR':continue
        b=char.visual_bbox.box;cx=(b.x+b.x2)/2;cy=(b.y+b.y2)/2
        candidates=[w for w in rows.get(int(cy//8),[]) if w.x-2<=cx<=w.x2+2]
        if not candidates:continue
        w=min(candidates,key=lambda box:abs((box.y+box.y2)/2-cy))
        if abs((w.y+w.y2)/2-cy)>max(8,w.y2-w.y):continue
        x=max(w.x,min(b.x,w.x2-.1));x2=max(x+.1,min(b.x2,w.x2))
        char.visual_bbox.box=Box(x=x,y=w.y,x2=x2,y2=w.y2)
        char.box=Box(x=x,y=w.y,x2=x2,y2=w.y2)

def protect_ocr_body(document,config,plan):
    """Keep new articles and author biographies outside reference exclusions."""
    if not getattr(config,'twintext_ocr_pages',set()) or not config.twintext_document_options.get('ignoreReferences'):return plan
    from statistics import median
    from native_artifacts import paragraph_text
    import reference_layout as references
    from structure_plan import REF_MARKER
    items=[(page,p,paragraph_text(p)) for page in document.page if page.page_number in config.twintext_ocr_pages for p in page.pdf_paragraph if p.pdf_style]
    reference_sizes=[p.pdf_style.font_size for page,p,text in items if REF_MARKER.match(text) and re.search(r'\b(?:18|19|20)\d{2}\b',text)]
    threshold=median(reference_sizes)*1.15 if reference_sizes else float('inf')
    prose=[(page,p) for page,p,text in items if is_body(p) and len(text)>100 and p.pdf_style.font_size>threshold and not REF_MARKER.match(text)]
    biographies=[]
    for page,p,text in items:
        if REF_MARKER.match(text) or not is_body(p):continue
        compact=re.sub(r'\s+','',text.casefold())[:300]
        if re.search(r'(?:wasborn|graduatedfrom|received(?:his|her|an?|the)?(?:b\.?eng|b\.?sc|m\.?sc|ph\.?d|dipl|degree|d[’\']?ing))',compact):biographies.append((page,p))
    for page,p,text in items:
        if not is_body(p) or REF_MARKER.match(text):continue
        starts=[start for origin,start in biographies if origin.page_number==page.page_number]
        entire_page=len(starts)>=2 and not any(REF_MARKER.match(t) for origin,_,t in items if origin.page_number==page.page_number)
        if entire_page or any(page.page_number>origin.page_number or page.page_number==origin.page_number and
            p.box.y2<=start.box.y2+2 and min(p.box.x2,start.box.x2)-max(p.box.x,start.box.x)>min(p.box.x2-p.box.x,start.box.x2-start.box.x)*.3 for origin,start in biographies):prose.append((page,p))
    plan['exclusions']=[entry for entry in plan.get('exclusions',[]) if entry.get('reason')!='references' or not any(
        page.page_number==entry['pageIndex'] and p.box.x<=((b:=references.pdf_box(entry['rect'],page)).x+b.x2)/2<=p.box.x2
        and p.box.y<=(b.y+b.y2)/2<=p.box.y2 for page,p in prose)]
    return plan

@contextmanager
def track_body(config,quality,local):
    from babeldoc.format.pdf import high_level
    original=high_level.ILTranslator;styles=high_level.StylesAndFormulas;finder=high_level.ParagraphFinder
    import reference_layout as references
    analyze=references.analyze
    def checked_references(document,config):return protect_ocr_body(document,config,analyze(document,config))
    class ScanParagraphs(finder):
        def process_page(self,page):
            before=config.ocr_workaround
            scan=page.page_number in getattr(config,'twintext_scan_pages',set())
            if scan and not before:
                from babeldoc.format.pdf.document_il.midend.detect_scanned_file import BLACK
                for char in page.pdf_character:
                    char.render_order=None
                    if not char.debug_info:char.pdf_style.graphic_state=BLACK
                config.ocr_workaround=True
            if page.page_number in getattr(config,'twintext_ocr_geometry',{}):
                align_ocr_geometry(page,config.twintext_ocr_geometry[page.page_number])
            try:
                result=super().process_page(page)
                if page.page_number in getattr(config,'twintext_ocr_pages',set()):merge_ocr_lines(page)
                absolute=page.page_number+getattr(config,'twintext_page_offset',0)
                if absolute in quality['unreadablePages'] and not any(is_body(p) for p in page.pdf_paragraph):
                    if not any(str(layout.class_name).lower() in ('plain text','text','body') and
                        (layout.box.x2-layout.box.x)*(layout.box.y2-layout.box.y)>2000 for layout in page.page_layout):
                        quality['unreadablePages'].remove(absolute);quality['nonTextPages'].append(absolute)
                        config.twintext_nontext_pages.add(page.page_number)
                return result
            finally:config.ocr_workaround=before
    class RecoveredStyles(styles):
        def process_page(self,page):
            super().process_page(page)
            if page.page_number in getattr(config,'twintext_ocr_pages',set()):
                from ocr_formula import preserve
                preserve(config,page,{'TwinTextOCR'})
    class QualityTranslator(original):
        def translate(self,document):
            self._twintext_unchanged=set()
            result=super().translate(document)
            from ocr_formula import preserve_paragraph
            for page in document.page:
                for paragraph in page.pdf_paragraph:
                    if id(paragraph) in self._twintext_unchanged:preserve_paragraph(paragraph,page.page_number)
            return result
        def translate_paragraph(self,paragraph,page,*args,**kwargs):
            if page.page_number in getattr(config,'twintext_nontext_pages',set()):
                pbar=kwargs.get('pbar') or (args[0] if args else None)
                if pbar:pbar.advance()
                return
            previous=getattr(local,'body',False);local.body=is_body(paragraph)
            before=paragraph.unicode
            try:return super().translate_paragraph(paragraph,page,*args,**kwargs)
            finally:
                if paragraph.unicode==before and page.page_number in getattr(config,'twintext_ocr_pages',set()):
                    self._twintext_unchanged.add(id(paragraph))
                local.body=previous
    high_level.ILTranslator=QualityTranslator
    if getattr(config,'twintext_ocr_pages',set()):references.analyze=checked_references
    if getattr(config,'twintext_scan_pages',set()):high_level.ParagraphFinder=ScanParagraphs
    if getattr(config,'twintext_ocr_pages',set()):high_level.StylesAndFormulas=RecoveredStyles
    try:yield
    finally:high_level.ILTranslator=original;high_level.StylesAndFormulas=styles;high_level.ParagraphFinder=finder;references.analyze=analyze

def ensure_body(quality):
    if quality is not None:
        for key in ('scanPages','ocrPages','fontRepairPages','unreadablePages','nonTextPages'):quality[key]=sorted(set(quality[key]))
    if quality is not None and not quality['bodyRequests']:
        error=failure('document_no_body_text','No readable body text was sent for translation in the selected pages. Check the text layer, OCR language and ignored regions; the source and paragraph cache were preserved.')
        error.text_quality=quality.copy()
        raise error

def preserve_nontext(data,source,pages,isolated=False):
    if not pages:return data
    import pymupdf
    with pymupdf.open(stream=source,filetype='pdf') as original,pymupdf.open(stream=data,filetype='pdf') as output:
        toc=output.get_toc(simple=False)
        for index in sorted(pages):
            target=0 if isolated else index
            output.delete_page(target);output.insert_pdf(original,from_page=index,to_page=index,start_at=target)
        if toc:output.set_toc(toc)
        if not isolated:
            for index in range(len(output)):
                links=output[index].get_links()
                for link in original[index].get_links():
                    if link.get('kind')!=pymupdf.LINK_GOTO or (index not in pages and link.get('page') not in pages):continue
                    if not any(item.get('kind')==link['kind'] and item.get('page')==link.get('page') and item.get('from')==link.get('from') for item in links):
                        output[index].insert_link({key:value for key,value in link.items() if key not in ('xref','id')})
        return output.tobytes()
