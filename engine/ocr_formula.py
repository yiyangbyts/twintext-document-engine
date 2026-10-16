"""Native source crops preserve scan math and legacy bitmap drawing matrices.

Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
Clipped PDF Form XObjects share the original page resources. No formula, glyph
program, vector or source image is rasterized or resampled.
"""
from __future__ import annotations
import copy

KIND='twintext-source-crop'

def crop_form(box,index):
    from babeldoc.format.pdf.document_il import il_version_1 as il
    return il.PdfForm(box=copy.copy(box),graphic_state=il.GraphicState(passthrough_per_char_instruction=''),
        pdf_matrix=il.PdfMatrix(a=box.x2-box.x,b=0,c=0,d=box.y2-box.y,e=box.x,f=box.y),
        pdf_affine_transform=il.PdfAffineTransform(translation_x=box.x,translation_y=box.y,rotation=0,scale_x=1,scale_y=1,shear=0),
        pdf_form_subtype=il.PdfFormSubtype(pdf_xobj_form=il.PdfXobjForm(xref_id=index,do_args='TwinTextSourceCrop')),
        xobj_id=0,render_order=None,form_type=KIND)

def characters(comp):
    if comp.pdf_character:return [comp.pdf_character]
    for key in ('pdf_line','pdf_same_style_characters','pdf_formula'):
        item=getattr(comp,key,None)
        if item:return item.pdf_character
    return []

def preserve_paragraph(paragraph,index):
    from babeldoc.format.pdf.document_il import il_version_1 as il
    chars=[ch for comp in paragraph.pdf_paragraph_composition for ch in characters(comp)]
    if not chars:return
    for char in chars:char.pdf_character_id=None
    formula=il.PdfFormula(box=copy.copy(paragraph.box),pdf_character=chars,
        pdf_form=[crop_form(paragraph.box,index)],x_offset=0,y_offset=0,x_advance=0)
    paragraph.pdf_paragraph_composition=[il.PdfParagraphComposition(pdf_formula=formula)]

def preserve(config,page,fonts):
    for paragraph in page.pdf_paragraph:
        for comp in paragraph.pdf_paragraph_composition:
            formula=comp.pdf_formula
            if not formula or not any(ch.pdf_style.font_id in fonts for ch in formula.pdf_character):continue
            formula.pdf_form=[crop_form(formula.box,page.page_number)];formula.pdf_curve=[]
            for char in formula.pdf_character:char.pdf_character_id=None
    kept=[]
    for char in page.pdf_character:
        if char.pdf_style.font_id in fonts:page.pdf_form.append(crop_form(char.visual_bbox.box,page.page_number))
        else:kept.append(char)
    page.pdf_character=kept

def restore_visual_page(source,target,index,regions):
    import pymupdf
    page=source[index]
    for region in regions:
        if region.get('pageIndex')!=index:continue
        r=region['rect'];clip=pymupdf.Rect(r['left']*page.rect.width,r['top']*page.rect.height,(r['left']+r['width'])*page.rect.width,(r['top']+r['height'])*page.rect.height)
        clip=(clip+(-.8,-.8,.8,.8))&page.rect
        if clip.is_empty:continue
        # PDF text redaction unshares every intersecting original-page Form.
        # An opaque visual replacement keeps shared glyphs/images unchanged.
        target.draw_rect(clip,color=None,fill=(1,1,1),overlay=True)
        target.show_pdf_page(clip,source,index,clip=clip,overlay=True)

def restore_regions(canonical,translated,regions,isolated,config):
    from preserved_regions import restore
    pages=getattr(config,'twintext_ocr_pages',set())
    if not pages:return restore(canonical,translated,regions,isolated,config)
    ordinary=[r for r in regions if r.get('pageIndex') not in pages]
    recovered=[r for r in regions if r.get('pageIndex') in pages]
    output=restore(canonical,translated,ordinary,isolated,config)
    if not recovered:return output
    import pymupdf
    with pymupdf.open(getattr(config,'twintext_visual_source',config.input_file)) as source,pymupdf.open(stream=output,filetype='pdf') as target:
        for index in sorted(pages):
            if config.should_translate_page(index+1):restore_visual_page(source,target[0 if isolated else index],index,recovered)
        return target.tobytes(garbage=3,deflate=True)

def install():
    from dataclasses import replace
    from babeldoc.format.pdf.new_parser import xobject_content_execution as execution,page_content_execution
    from babeldoc.format.pdf.document_il.frontend.il_creater_active import ActiveILCreater
    if not getattr(execution,'_twintext_opaque_source',False):
        interpret=execution.interpret_operations_with_xobjects
        def opaque(operations,xobject_map,*args,**kwargs):
            if 'TwinTextOpaque' in xobject_map:
                xobject_map={key:replace(value,subtype_name='Image') if key=='TwinTextOpaque' and value.data.startswith(b'% TwinText opaque original page\n') else value for key,value in xobject_map.items()}
            return interpret(operations,xobject_map,*args,**kwargs)
        execution.interpret_operations_with_xobjects=opaque;page_content_execution.interpret_operations_with_xobjects=opaque
        image=ActiveILCreater.emit_native_image_xobject
        def emit(self,event,**kwargs):
            if event.name=='TwinTextOpaque':
                box=self.current_page.mediabox.box
                event=replace(event,bbox=(box.x,box.y,box.x2,box.y2))
            return image(self,event,**kwargs)
        ActiveILCreater.emit_native_image_xobject=emit;execution._twintext_opaque_source=True
    from babeldoc.format.pdf.document_il.backend.pdf_creater import PDFCreater
    if getattr(PDFCreater,'_twintext_source_crops',False):return
    original=PDFCreater.update_page_content_stream
    original_write=PDFCreater.write
    def write(self,config,*args,**kwargs):
        if not getattr(config,'twintext_ocr_pages',set()):return original_write(self,config,*args,**kwargs)
        import pymupdf
        # One source document / graft map per batch keeps original font
        # programs shared across every cropped page, not copied per page.
        with pymupdf.open(getattr(config,'twintext_visual_source',config.input_file)) as source:
            config.twintext_source_crop_document=source
            try:return original_write(self,config,*args,**kwargs)
            finally:del config.twintext_source_crop_document
    def update(self,check_font_exists,page,pdf,config,*args,**kwargs):
        import pymupdf
        forms=list(page.pdf_form)+[form for p in page.pdf_paragraph for comp in p.pdf_paragraph_composition
            if comp.pdf_formula for form in comp.pdf_formula.pdf_form]
        crops=[f for f in forms if f.form_type==KIND]
        if crops:
            from contextlib import nullcontext
            shared=getattr(config,'twintext_source_crop_document',None)
            with nullcontext(shared) if shared is not None else pymupdf.open(getattr(config,'twintext_visual_source',config.input_file)) as source:
                for form in crops:
                    index=form.pdf_form_subtype.pdf_xobj_form.xref_id;matrix=form.pdf_matrix
                    source_page=source[index];crop=source_page.cropbox
                    region=pymupdf.Rect(matrix.e-crop.x0,source_page.mediabox.height-(matrix.f+matrix.d)-crop.y0,
                        matrix.e+matrix.a-crop.x0,source_page.mediabox.height-matrix.f-crop.y0)&source_page.rect
                    if region.is_empty:continue
                    if getattr(config,'twintext_preview_source_crops',False):
                        # The provisional frame is raster already. A fixed
                        # source resolution avoids caching a full-page image
                        # at a different scale for every relocated formula.
                        import base64,json,math,zlib
                        from babeldoc.format.pdf.document_il.il_version_1 import PdfMatrix,PdfFormSubtype,PdfInlineForm
                        scale=min(4,math.sqrt(8_000_000/max(1,source_page.rect.get_area())))
                        pix=source_page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),clip=region,alpha=False)
                        left=pix.x/scale+crop.x0;bottom=source_page.mediabox.height-(pix.y+pix.height)/scale-crop.y0
                        form.pdf_matrix=PdfMatrix(a=pix.width/scale,b=0,c=0,d=pix.height/scale,e=left,f=bottom)
                        form.pdf_form_subtype=PdfFormSubtype(pdf_inline_form=PdfInlineForm(
                            form_data=base64.b64encode(zlib.compress(pix.samples,1)).decode('ascii'),
                            image_parameters=json.dumps(dict(W=pix.width,H=pix.height,BPC=8,CS='/DeviceRGB',F='/FlateDecode'))))
                        form.form_type='image'
                        continue
                    target=pdf[page.page_number];before={x[0] for x in target.get_xobjects()}
                    target.show_pdf_page(region,source,index,clip=region)
                    wrapper=next(x for x in target.get_xobjects() if x[0] not in before and x[2]==0)
                    form.pdf_form_subtype.pdf_xobj_form.xref_id=wrapper[0];form.pdf_form_subtype.pdf_xobj_form.do_args=wrapper[1]
                    from babeldoc.format.pdf.document_il.il_version_1 import PdfMatrix
                    form.pdf_matrix=PdfMatrix(a=1,b=0,c=0,d=1,e=0,f=0)
        before=config.ocr_workaround
        if page.page_number in getattr(config,'twintext_scan_pages',set()):config.ocr_workaround=True
        try:return original(self,check_font_exists,page,pdf,config,*args,**kwargs)
        finally:config.ocr_workaround=before
    PDFCreater.update_page_content_stream=update;PDFCreater._twintext_source_crops=True
    PDFCreater.write=write
