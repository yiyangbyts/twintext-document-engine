"""Quality gates and a real, bounded, on-demand OCR round trip."""
import hashlib,json,subprocess,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pymupdf
from pdf_text_quality import state,inspect_page,prepare,ensure_body,is_body,MODEL_SHA256

class TextQualityTests(unittest.TestCase):
    def test_ocr_reference_filter_stops_at_biography_without_disabling_citations(self):
        from pdf_text_quality import protect_ocr_body
        from babeldoc.format.pdf.document_il.il_version_1 import Box,Cropbox,Page,PdfParagraph,PdfStyle,PdfParagraphComposition,PdfSameStyleUnicodeCharacters
        def p(text,x,y,size=8):return PdfParagraph(unicode=text,box=Box(x=x,y=y,x2=x+220,y2=y+20),pdf_style=PdfStyle(font_size=size),layout_label='plain text',pdf_paragraph_composition=[PdfParagraphComposition(pdf_same_style_unicode_characters=PdfSameStyleUnicodeCharacters(unicode=text))])
        ref=p('[1] A. Smith, A paper, 1998.',20,500)
        other=p('[2] B. Smith, A second paper, 1997.',20,200)
        bio=p('Yann LeCun received a Diplome from Ecole Polytechnique and later joined the university.',300,300)
        continuation=p('His research includes machine learning and handwriting recognition, and document analysis.',300,260)
        nextpage=p('His interests also include video-based user interfaces and scientific image processing.',20,700)
        crop=Cropbox(box=Box(x=0,y=0,x2=600,y2=800))
        pages=[Page(page_number=4,cropbox=crop,pdf_paragraph=[ref,other,bio,continuation]),Page(page_number=5,cropbox=crop,pdf_paragraph=[nextpage])]
        def entry(page,paragraph,reason='references'):
            b=paragraph.box
            return dict(pageIndex=page,reason=reason,rect=dict(left=b.x/600,top=(800-b.y2)/800,width=(b.x2-b.x)/600,height=(b.y2-b.y)/800))
        exclusions=[entry(4,ref),entry(4,other),entry(4,bio),entry(4,continuation),entry(5,nextpage),entry(5,nextpage,'headersFooters')]
        config=SimpleNamespace(twintext_ocr_pages={4,5},twintext_document_options={'ignoreReferences':True})
        result=protect_ocr_body(SimpleNamespace(page=pages),config,{'exclusions':exclusions})
        self.assertEqual(result['exclusions'],[exclusions[0],exclusions[1],exclusions[-1]])
        config.twintext_ocr_pages=set()
        self.assertEqual(protect_ocr_body(SimpleNamespace(page=pages),config,{'exclusions':exclusions})['exclusions'],exclusions)
    def test_graphic_only_page_keeps_source_pixels_bookmarks_and_destinations(self):
        from pdf_text_quality import preserve_nontext
        with pymupdf.open() as doc:
            for i in range(3):doc.new_page().insert_text((30,100),f'Source page {i}')
            doc.set_toc([[1,'Figure',2],[1,'Body',3]])
            doc[0].insert_link(dict(kind=pymupdf.LINK_GOTO,from_=None,**{'from':pymupdf.Rect(20,20,100,40),'page':1,'to':pymupdf.Point(0,0)}))
            source=doc.tobytes();toc=doc.get_toc();pixels=doc[1].get_pixmap().samples
            for page in doc:page.insert_text((30,150),'Translated body')
            data=doc.tobytes()
        recovered=preserve_nontext(data,source,[1])
        with pymupdf.open(stream=recovered,filetype='pdf') as output:
            self.assertEqual(len(output),3);self.assertEqual(output.get_toc(),toc)
            self.assertEqual(output[1].get_pixmap().samples,pixels)
            self.assertIn('Translated body',output[0].get_text());self.assertEqual(output[0].get_links()[0]['page'],1)
    def test_ocr_uses_recognition_height_and_leaves_native_font_geometry_unchanged(self):
        from pdf_text_quality import align_ocr_geometry
        from babeldoc.format.pdf.document_il.il_version_1 import Page,Cropbox,Box,PdfCharacter,PdfStyle,VisualBbox
        def char(font):return PdfCharacter(pdf_style=PdfStyle(font_id=font,font_size=10),box=Box(x=10,y=606,x2=20,y2=612),visual_bbox=VisualBbox(box=Box(x=10,y=606,x2=20,y2=612)),pdf_character_id=8)
        ocr,native=char('TwinTextOCR'),char('native')
        page=Page(cropbox=Cropbox(box=Box(x=0,y=0,x2=600,y2=800)),pdf_character=[ocr,native])
        align_ocr_geometry(page,[[10,180,100,200]])
        self.assertEqual((ocr.box.y,ocr.box.y2),(600,620));self.assertEqual((native.box.y,native.box.y2),(606,612))
    def test_native_source_form_preserves_vectors_while_preview_uses_bounded_pixels(self):
        from ocr_formula import install,crop_form
        from babeldoc.format.pdf.document_il.backend.pdf_creater import PDFCreater,FormRenderUnit
        from babeldoc.format.pdf.document_il.il_version_1 import Page,Cropbox,Box
        from bitstring import BitStream
        install()
        class StopBeforeNativeDrawing(Exception):pass
        with tempfile.TemporaryDirectory() as folder,pymupdf.open() as source:
            page=source.new_page(width=180,height=200);page.draw_rect((20,20,160,180),color=(0,0,1),fill=(.8,.9,1));page.insert_text((30,100),'x + y = 2')
            path=Path(folder)/'source.pdf';source.save(path);pixels=page.get_pixmap().samples
            for preview in (False,True):
                with pymupdf.open() as target:
                    target.new_page(width=180,height=200);form=crop_form(Box(x=0,y=0,x2=180,y2=200),0)
                    il=Page(page_number=0,cropbox=Cropbox(box=Box(x=0,y=0,x2=180,y2=200)),pdf_form=[form])
                    config=SimpleNamespace(input_file=path,ocr_workaround=False,twintext_preview_source_crops=preview,raise_if_cancelled=lambda:None)
                    creator=object.__new__(PDFCreater)
                    with patch.object(PDFCreater,'get_available_font_list',side_effect=StopBeforeNativeDrawing):
                        with self.assertRaises(StopBeforeNativeDrawing):creator.update_page_content_stream(False,il,target,config)
                    ops=BitStream();FormRenderUnit(form,None).render(ops,None)
                    ref=target.get_new_xref();target.update_object(ref,'<<>>');target.update_stream(ref,ops.tobytes());target[0].set_contents(ref)
                    if not preview:
                        self.assertEqual(target[0].get_pixmap().samples,pixels);self.assertTrue(target[0].get_fonts(full=True));self.assertFalse(target[0].get_images())
                    else:
                        self.assertFalse(target[0].get_fonts(full=True));info=target[0].get_image_info()[0]
                        self.assertLessEqual(info['width']*info['height'],8_000_000)
    def test_ocr_line_merge_keeps_columns_indents_headings_and_region_boundaries(self):
        from babeldoc.format.pdf.document_il.il_version_1 import PdfParagraph,Box,PdfStyle,Page
        from pdf_text_quality import merge_ocr_lines
        def p(text,x,y,region=1,label='plain text'):
            return PdfParagraph(unicode=text,layout_id=region,layout_label=label,box=Box(x=x,y=y,x2=x+100,y2=y+8),pdf_style=PdfStyle(font_size=10),pdf_paragraph_composition=[])
        page=Page(pdf_paragraph=[p('First',30,100),p('continues',30,90),p('New indent',40,80),p('continues again',30,70),p('Other column',300,100),p('Heading',30,60,label='title'),p('Other region',30,50,2)])
        merge_ocr_lines(page)
        self.assertEqual([p.unicode for p in page.pdf_paragraph],['First continues','New indent continues again','Other column','Heading','Other region'])
    def test_only_generated_opaque_source_forms_skip_glyph_interpretation(self):
        from ocr_formula import install
        install()
        from babeldoc.format.pdf.new_parser.prepared_page import PreparedXObject
        from babeldoc.format.pdf.new_parser.xobject_content_execution import interpret_operations_with_xobjects,tokenize_content_stream
        from babeldoc.format.pdf.new_parser.interpreter import ImageXObjectEvent,BeginXObjectEvent
        form=PreparedXObject(subtype_name='Form',xref_id=8,font_specs=(),xobject_map={},bbox=(0,0,600,800),matrix=(1,0,0,1,0,0),data=b'% TwinText opaque original page\nq Q')
        resources=SimpleNamespace(get_font=lambda *args:None)
        events,_=interpret_operations_with_xobjects(tokenize_content_stream(b'/TwinTextOpaque Do'),{'TwinTextOpaque':form},resource_bundle=resources)
        self.assertEqual(len(events),1);self.assertIsInstance(events[0],ImageXObjectEvent)
        from dataclasses import replace
        events,_=interpret_operations_with_xobjects(tokenize_content_stream(b'/TwinTextOpaque Do'),{'TwinTextOpaque':replace(form,data=b'q Q')},resource_bundle=resources)
        self.assertIsInstance(events[0],BeginXObjectEvent)
    def test_healthy_text_is_byte_identical_and_never_launches_ocr(self):
        with tempfile.TemporaryDirectory() as folder,pymupdf.open() as doc:
            page=doc.new_page();page.insert_text((72,150),'Readable body text for translation. '*4)
            data=doc.tobytes();quality=state()
            with patch('pdf_text_quality.subprocess.Popen',side_effect=AssertionError('healthy text must bypass OCR')):
                self.assertEqual(prepare(data,Path(folder),{'_textQuality':quality}),data)
            self.assertEqual(quality['checkedPages'],1);self.assertEqual(quality['ocrPages'],[])
    def test_copyright_is_not_body_and_zero_body_is_actionable(self):
        for text in ['© Nature Publishing Group 1986','All rights reserved','(cid:123)'*30]:
            self.assertFalse(is_body(SimpleNamespace(unicode=text,layout_label='text')))
        self.assertTrue(is_body(SimpleNamespace(unicode='This ordinary body paragraph should be sent for translation.',layout_label='text')))
        quality=state()
        with self.assertRaises(RuntimeError) as caught:ensure_body(quality)
        self.assertEqual(caught.exception.code,'document_no_body_text')
        quality['bodyRequests']=1;ensure_body(quality)
    def test_image_only_recovers_hidden_text_without_changing_source_pixels_and_reuses_disk(self):
        with tempfile.TemporaryDirectory(prefix='OCR 中文 空格 ') as folder:
            root=Path(folder)
            with pymupdf.open() as printed:
                page=printed.new_page();page.insert_text((60,180),'This scanned document contains readable scientific body text.',fontsize=18)
                page.insert_text((60,230),'Page OCR must preserve original images and vector graphics.',fontsize=18)
                image=page.get_pixmap(dpi=180).tobytes('png')
            with pymupdf.open() as scan:
                page=scan.new_page();page.insert_image(page.rect,stream=image);page.draw_rect((30,30,80,80),color=(1,0,0));source=scan.tobytes()
                self.assertEqual(inspect_page(page),'image-text');pixels=page.get_pixmap().samples
            quality=state();payload={'_textQuality':quality,'sourceLanguage':'en','_ocrCache':str(root/'cache')}
            recovered=prepare(source,root,payload,cancel_event=threading.Event())
            with pymupdf.open(stream=recovered,filetype='pdf') as pdf:
                self.assertIn('scanned document',' '.join(pdf[0].get_text().split()));self.assertEqual(pdf[0].get_pixmap().samples,pixels)
                self.assertEqual(len(pdf[0].get_drawings()),1)
            self.assertEqual(quality['ocrPages'],[0])
            again=prepare(source,root,payload)
            self.assertEqual(json.loads((root/'ocr-report.json').read_text())['cachedPages'],1)
            with pymupdf.open(stream=again,filetype='pdf') as pdf:self.assertIn('scanned document',' '.join(pdf[0].get_text().split()))
    def test_ocr_model_is_pinned_and_worker_has_no_model_or_font_imports(self):
        root=Path(__file__).parent
        self.assertEqual(hashlib.sha256((root/'ocr-data/eng.traineddata').read_bytes()).hexdigest(),MODEL_SHA256)
        command='import runpy,sys;runpy.run_path('+repr(str(root/'ocr_worker.py'))+');assert not any(n.startswith(("babeldoc","onnxruntime","numpy")) for n in sys.modules)'
        subprocess.run([sys.executable,'-c',command],check=True,timeout=20)
    def test_type3_native_background_keeps_pixels_and_exposes_ocr_letters(self):
        with tempfile.TemporaryDirectory() as folder,pymupdf.open() as doc:
            page=doc.new_page();base=page.insert_font(fontname='helv');font=doc.get_new_xref()
            chars='ABCDEFGHIJKLMNOPQRSTUVWXYZ';programs=[]
            for code,char in enumerate(chars,1):
                ref=doc.get_new_xref();doc.update_object(ref,'<<>>')
                doc.update_stream(ref,f'650 0 0 -200 650 900 d1 BT /F0 900 Tf 0 0 Td ({char}) Tj ET'.encode())
                programs.append(f'/a{code} {ref} 0 R')
            doc.update_object(font,f'<< /Type /Font /Subtype /Type3 /Name /Fixture /FontBBox [0 -200 650 900] /FontMatrix [.001 0 0 .001 0 0] /FirstChar 0 /LastChar 26 /Widths [0 {"650 "*26}] /Encoding << /Type /Encoding /Differences [1 {" ".join("/a"+str(i) for i in range(1,27))}] >> /Resources << /Font << /F0 {base} 0 R >> >> /CharProcs << {" ".join(programs)} >> >>')
            doc.xref_set_key(page.xref,'Resources',f'<< /Font << /A {font} 0 R >> >>')
            sentence='READABLE BODY TEXT RECOVERS ORIGINAL BITMAP LETTERS'
            stream=doc.get_new_xref();doc.update_object(stream,'<<>>')
            code=''.join(f'{chars.index(c)+1:02x}' if c!=' ' else '00' for c in sentence)
            # Space has width but no visible glyph; preserve explicit word gaps.
            doc.xref_set_key(font,'Widths','[650 '+('650 '*26)+']')
            doc.update_stream(stream,('BT /A 16 Tf 1 0 0 1 40 600 Tm <'+code+'> Tj 0 -32 Td <'+code+'> Tj 0 -32 Td <'+code+'> Tj ET').encode());page.set_contents(stream)
            data=doc.tobytes();pixels=page.get_pixmap().samples;quality=state()
            recovered=prepare(data,Path(folder),{'_textQuality':quality,'sourceLanguage':'en'})
            with pymupdf.open(stream=recovered,filetype='pdf') as after:
                self.assertEqual(after[0].get_pixmap().samples,pixels)
                self.assertIn('READABLE',''.join(after[0].get_text().split()))
                self.assertEqual(after[0].get_images(),[])
            self.assertEqual(quality['fontRepairPages'],[0])
    def test_unsupported_language_does_not_silently_use_english(self):
        with tempfile.TemporaryDirectory() as folder,pymupdf.open() as doc:
            page=doc.new_page();page.insert_text((60,180),'Placeholder image body')
            image=page.get_pixmap().tobytes('png');page=doc.new_page();page.insert_image(page.rect,stream=image)
            with self.assertRaises(RuntimeError) as caught:prepare(doc.tobytes(),Path(folder),{'_textQuality':state(),'pages':'2','sourceLanguage':'de'})
            self.assertEqual(caught.exception.code,'document_ocr_language')

if __name__=='__main__':unittest.main()
