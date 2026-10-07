import copy,sys,unittest
from types import SimpleNamespace as N,ModuleType
from unittest.mock import patch
from reference_layout import source_shadows,render_references,ReferencePolicy

def box(x=10,y=70,x2=90,y2=80):return N(x=x,y=y,x2=x2,y2=y2)
def comp(**kwargs):return N(**{'pdf_character':None,'pdf_line':None,'pdf_same_style_characters':None,'pdf_formula':None,**kwargs})
def char(text,x,y=70):return N(char_unicode=text,box=box(x,y,x+2,y+8),visual_bbox=None,pdf_style=N(font_size=8,font_id='base'),render_order=int(100-y)*100+int(x),sub_render_order=0)
def paragraph(key,chars):return N(debug_id=key,pdf_style=N(font_size=8,font_id='base'),xobj_id=0,pdf_paragraph_composition=[comp(pdf_same_style_characters=N(pdf_character=chars))],vertical=False,box=box(),first_line_indent=True,unicode=''.join(c.char_unicode for c in chars))
def page(paragraphs):return N(page_number=0,pdf_paragraph=paragraphs,cropbox=N(box=box(0,0,100,100)),pdf_font=[],pdf_xobject=[],pdf_curve=[],pdf_form=[])
def entry(key,label,top,height):return {'id':key,'pageIndex':0,'label':label,'text':label+' Author (2020). Title.', 'bodyLeft':.2,'rect':{'left':.1,'top':top,'width':.8,'height':height}}

class ReferenceTests(unittest.TestCase):
    def setUp(self):
        fake=ModuleType('babeldoc.format.pdf.document_il.il_version_1');fake.Box=box
        fake.PdfParagraphComposition=lambda **kw:N(pdf_character=kw.get('pdf_character'),pdf_line=None,pdf_same_style_characters=None,pdf_formula=None)
        fake.PdfSameStyleCharacters=lambda **kw:N(**kw)
        fake.PdfParagraphComposition=lambda **kw:N(**{'pdf_character':None,'pdf_line':None,'pdf_same_style_characters':None,'pdf_formula':None,**kw})
        self.modules=patch.dict(sys.modules,{'babeldoc.format.pdf.document_il.il_version_1':fake});self.modules.start();self.addCleanup(self.modules.stop)
    def test_merged_parent_splits_and_keeps_labels_out_of_translation(self):
        chars=[char('1',10),char('.',12),char('A',20),char('2',10,50),char('.',12,50),char('B',20,50)]
        p=paragraph('merged',chars);before=copy.deepcopy(p);out=source_shadows(page([p]),[entry('a','1.',.2,.1),entry('b','2.',.4,.1)])
        self.assertEqual(len(out),2);self.assertEqual([e['label'].unicode for e in out],['1.','2.'])
        self.assertTrue(all(not e['paragraph'].unicode.startswith(e['label'].unicode) for e in out))
        self.assertEqual([e['paragraph'].box.x for e in out],[20,20]);self.assertEqual(p.unicode,before.unicode)
        self.assertEqual(len(p.pdf_paragraph_composition[0].pdf_same_style_characters.pdf_character),6)
    def test_mixed_body_and_reference_parent_is_left_entirely_unchanged(self):
        p=paragraph('mixed',[char('1',10),char('.',12),char('A',20),char('正文',10,90)])
        self.assertEqual(source_shadows(page([p]),[entry('a','1.',.2,.1)]),[])
    def test_last_reference_never_extends_into_appendix(self):
        ref=paragraph('ref',[char('1',10),char('.',12),char('A',20)]);appendix=paragraph('appendix',[char('Appendix',10,50)])
        out=source_shadows(page([ref,appendix]),[entry('a','1.',.2,.1)])
        self.assertEqual(len(out),1);self.assertEqual(out[0]['parents'],['ref']);self.assertEqual(out[0]['box'].y,70)
    def test_duplicate_source_membership_and_missing_numbers_are_conservative(self):
        p=paragraph('ref',[char('1',10),char('.',12),char('A',20)])
        self.assertEqual(source_shadows(page([p]),[entry('a','1.',.2,.1),entry('b','2.',.2,.1)]),[])
        self.assertEqual(source_shadows(page([p]),[entry('a','9.',.2,.1)]),[])
    def test_formula_crossing_entries_rolls_back_whole_parent(self):
        p=paragraph('ref',[]);p.pdf_paragraph_composition=[comp(pdf_formula=N(pdf_character=[char('1',10),char('.',12),char('∑',20),char('2',10,50),char('.',12,50),char('B',20,50)]))]
        self.assertEqual(source_shadows(page([p]),[entry('a','1.',.2,.1),entry('b','2.',.4,.1)]),[])
    def test_failed_reference_fit_retains_upstream_paragraph_and_body_identity(self):
        ref=paragraph('ref',[char('1',10),char('.',12),char('A',20)]);body=paragraph('body',[char('正文',10,90)])
        doc=page([body,ref]);plan=source_shadows(doc,[entry('a','1.',.2,.1)]);plan[0]['translated']=True
        typesetter=N(font_mapper=N(fontid2font={}),create_typesetting_units=lambda p,f:[object()],_layout_typesetting_units=lambda *a:([],False))
        render_references(doc,plan,typesetter);self.assertIs(doc.pdf_paragraph[0],body);self.assertIs(doc.pdf_paragraph[1],ref)
    def test_structural_analysis_is_local_and_needs_no_client_callback(self):
        policy=ReferencePolicy(N())
        policy.prepare(N(page=[page([paragraph('body',[char('Body',10)])])]))
        self.assertEqual(policy.snapshot(0),[])
    def test_alphabetic_list_marker_is_literal_and_item_body_starts_at_source_indent(self):
        p=paragraph('list',[char('a',10),char(')',12),char('Title',25)])
        e=entry('a','a)',.2,.1);e['kind']='list'
        result=source_shadows(page([p]),[e]);self.assertEqual(len(result),1)
        self.assertEqual(result[0]['paragraph'].box.x,25);self.assertEqual(result[0]['label'].unicode,'a)')
    def test_contents_keeps_page_glyphs_at_original_right_position_outside_provider_text(self):
        p=paragraph('toc',[char('1',10),char('Title',25),char('.',50),char('.',60),char('3',85)])
        e=entry('a','1',.2,.1);e.update(kind='toc',text='1 Introduction',pageLabel='3')
        result=source_shadows(page([p]),[e]);self.assertEqual(len(result),1)
        out=result[0];self.assertEqual(out['paragraph'].unicode,'Introduction');self.assertEqual(out['paragraph'].box.x,25)
        self.assertLess(out['paragraph'].box.x2,85);self.assertEqual(out['tail'].pdf_paragraph_composition[-1].pdf_character.box.x,85)
    def test_translated_units_are_rendered_to_real_glyphs_and_keep_body_object_identity(self):
        ref=paragraph('ref',[char('1',10),char('.',12),char('A',20)]);body=paragraph('body',[char('Body',10,90)]);doc=page([body,ref])
        plan=source_shadows(doc,[entry('a','1.',.2,.1)]);plan[0]['translated']=True
        unit=N(box=box(20,70,28,78),render=lambda:([char('中',20)],[],[]))
        setter=N(font_mapper=N(fontid2font={}),create_typesetting_units=lambda p,f:[unit],_layout_typesetting_units=lambda *a:([unit],True),_update_paragraph_render_order=lambda p:None)
        render_references(doc,plan,setter);self.assertIs(doc.pdf_paragraph[0],body)
        self.assertEqual(doc.pdf_paragraph[1].pdf_paragraph_composition[0].pdf_character.char_unicode,'中')
    def test_split_rows_keep_distinct_contiguous_pdf_reading_orders(self):
        p=paragraph('merged',[char('1',10),char('.',12),char('A',20),char('2',10,50),char('.',12,50),char('B',20,50)])
        for c in p.pdf_paragraph_composition[0].pdf_same_style_characters.pdf_character:c.render_order=0
        doc=page([p]);plan=source_shadows(doc,[entry('a','1.',.2,.1),entry('b','2.',.4,.1)])
        for e in plan:e['translated']=True
        def units(p,fonts):
            y=p.box.y
            return [N(box=box(20,y,28,y+8),render=lambda:([char('译',20,y),char('文',24,y)],[],[]))]
        setter=N(font_mapper=N(fontid2font={}),create_typesetting_units=units,_layout_typesetting_units=lambda u,*a:(u,True))
        render_references(doc,plan,setter)
        from reference_layout import characters
        chars=[c for p in doc.pdf_paragraph for comp in p.pdf_paragraph_composition for c in characters(comp)]
        ordered=sorted(chars,key=lambda c:(c.render_order,c.sub_render_order))
        self.assertEqual(''.join(c.char_unicode for c in ordered),'1.译文2.译文')
        self.assertEqual(len({(c.render_order,c.sub_render_order) for c in ordered}),len(ordered))
    def test_null_ocr_orders_place_labels_above_upstream_white_masks(self):
        p=paragraph('ref',[char('1',10),char('.',12),char('A',20)])
        p.render_order=None
        for c in p.pdf_paragraph_composition[0].pdf_same_style_characters.pdf_character:c.render_order=None
        doc=page([p]);plan=source_shadows(doc,[entry('a','1.',.2,.1)]);plan[0]['translated']=True
        unit=N(box=box(20,70,28,78),render=lambda:([char('中',20)],[],[]))
        setter=N(font_mapper=N(fontid2font={}),create_typesetting_units=lambda p,f:[unit],_layout_typesetting_units=lambda *a:([unit],True))
        render_references(doc,plan,setter)
        from reference_layout import characters
        glyphs=[c for p in doc.pdf_paragraph for comp in p.pdf_paragraph_composition for c in characters(comp)]
        self.assertTrue(all(c.sub_render_order>9999999999999999 for c in glyphs))
if __name__=='__main__':unittest.main()
