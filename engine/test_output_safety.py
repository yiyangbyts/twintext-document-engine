import unittest
import pymupdf
from output_safety import validate
from service import failure_code


class OutputSafetyTests(unittest.TestCase):
    def fixture(self, text='Visible original scientific paragraph.', drawing=False):
        with pymupdf.open() as doc:
            page=doc.new_page()
            if text:page.insert_text((50,80),text)
            if drawing:page.draw_rect(pymupdf.Rect(50,50,150,150))
            return doc.tobytes()

    def test_blank_output_enters_existing_page_recovery(self):
        with self.assertRaisesRegex(ValueError,'lost page content') as caught:
            validate(self.fixture(),self.fixture(''),[0])
        self.assertEqual(failure_code(caught.exception,'write'),'document_page_failed')

    def test_text_and_graphics_are_not_mistaken_for_blank_pages(self):
        validate(self.fixture(),self.fixture('Translated scientific paragraph.'),[0])
        validate(self.fixture(),self.fixture('',drawing=True),[0])
        validate(self.fixture(''),self.fixture(''),[0])

    def test_isolated_output_checks_selected_source_page(self):
        with pymupdf.open() as doc:
            doc.new_page();page=doc.new_page();page.insert_text((50,80),'Only the second page contains scientific text.')
            source=doc.tobytes()
        with self.assertRaises(ValueError):validate(source,self.fixture(''),[1],True)
