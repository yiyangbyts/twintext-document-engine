import copy,unittest
from types import SimpleNamespace as N
import test_reference_layout as fixtures
from test_reference_layout import paragraph,char,page,entry,comp
from ignored_regions import split
from document_options import options,make_typesetter

class IgnoreTests(unittest.TestCase):
    setUp=fixtures.ReferenceTests.setUp
    def test_mixed_header_body_split_preserves_exact_glyphs(self):
        original=paragraph('mixed',[char('Header',10,90),char('Body',10,70)])
        p=page([original]);excluded={'pageIndex':0,'rect':{'left':.09,'top':.01,'width':.85,'height':.10}}
        preserved=split(p,[excluded]);self.assertEqual(len(p.pdf_paragraph),2)
        self.assertEqual(p.pdf_paragraph[0].unicode,'Body');self.assertEqual(p.pdf_paragraph[1].unicode,'Header')
        self.assertIn(p.pdf_paragraph[1].debug_id,preserved)
        self.assertEqual(p.pdf_paragraph[1].pdf_paragraph_composition[0].pdf_same_style_characters.pdf_character[0].box.y,90)
        self.assertEqual(original.unicode,'HeaderBody')
    def test_unselected_page_and_formula_crossing_boundary_are_unchanged(self):
        original=paragraph('formula',[char('x',10,90),char('y',10,70)]);original.pdf_paragraph_composition=[comp(pdf_formula=N(pdf_character=[char('x',10,90),char('y',10,70)]))]
        p=page([original]);self.assertEqual(split(p,[{'pageIndex':1,'rect':{'left':0,'top':0,'width':1,'height':.15}}]),set())
        self.assertEqual(split(p,[{'pageIndex':0,'rect':{'left':0,'top':0,'width':1,'height':.15}}]),set());self.assertIs(p.pdf_paragraph[0],original)
    def test_fully_ignored_paragraph_is_original_object(self):
        original=paragraph('ref',[char('Reference',10,70)]);p=page([original]);self.assertEqual(split(p,[entry('a','1.',.2,.1)]),{'ref'});self.assertIs(p.pdf_paragraph[0],original)

class FormatTests(unittest.TestCase):
    def test_only_translated_unicode_scales_and_line_height_is_passed(self):
        units=[N(unicode='中',font_size=10),N(unicode=None,font_size=10,char=N()),N(unicode=None,font_size=None,formula=N())];calls=[]
        class Base:
            def create_typesetting_units(self,*_):return units
            def _layout_typesetting_units(self,*args):calls.append(args);return args[0],True
        setter=make_typesetter(Base,{'fontScale':140,'lineHeightScale':150})()
        setter.create_typesetting_units(None,None);self.assertEqual([u.font_size for u in units],[14,10,None])
        setter._layout_typesetting_units(units,None,1,1.2,None);self.assertAlmostEqual(calls[0][3],1.8)
    def test_invalid_preferences_are_bounded(self):
        self.assertEqual(options({'fontScale':True,'lineHeightScale':999,'fontFamily':'arbitrary'})['fontScale'],1)
        self.assertEqual(options({'lineHeightScale':999})['lineHeightScale'],1.8)
        self.assertEqual(options({'fontFamily':'sans'})['fontFamily'],'sans-serif')

if __name__=='__main__':unittest.main()
