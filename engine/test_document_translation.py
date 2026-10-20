import importlib.util
import base64
import os
from pathlib import Path
import re
import tempfile
import threading
import unicodedata
from types import SimpleNamespace as N
import unittest
from unittest.mock import patch

from document_translation import label_groups, make_translator


class RelayTests(unittest.TestCase):
    def test_plain_relay_keeps_styles_without_enabling_prompt_interface(self):
        calls = []
        class Base:
            support_llm_translate = False
            translation_config = N(disable_rich_text_translate=False, min_text_length=2)
            def get_translate_input(self, paragraph, fonts, disabled):
                calls.append((fonts, disabled))
                return N(unicode='Text <b1>bold</b1> <b3>', placeholders=['style', 'formula'])
        tracker = N(**{name: lambda value: None for name in
            ('set_pdf_unicode', 'set_input', 'set_placeholders', 'set_original_placeholders')})
        translator = make_translator(Base)()
        paragraph = N(vertical=False, unicode='Text bold formula', xobj_id=7)
        fonts={'source':N(name='Helvetica-Bold',bold=False,italic=False,serif=True,monospace=False)}
        text, prepared = translator.pre_translate_paragraph(paragraph, tracker, {}, {7: fonts})
        self.assertEqual(text, 'Text <b1>bold</b1> <b3>')
        self.assertEqual(calls, [(fonts, False)])
        self.assertTrue(fonts['source'].bold)
        self.assertFalse(fonts['source'].serif)
        self.assertFalse(translator.support_llm_translate)
        translator.translation_config = N(disable_rich_text_translate=True, min_text_length=2)
        translator.pre_translate_paragraph(paragraph, tracker, fonts, {})
        self.assertEqual(calls[-1], (fonts, True))

    def test_graphic_rows_and_distant_cells_never_join(self):
        def char(text, x, y):
            return N(char_unicode=text, box=N(x=x, y=y, x2=x+4, y2=y+10),
                     pdf_style=N(font_size=10))
        groups = list(label_groups([char('A', 10, 40), char('B', 15, 40),
            char('C', 60, 40), char('D', 10, 20)]))
        self.assertEqual([''.join(c.char_unicode for c in g) for g in groups], ['AB', 'C', 'D'])


HAS_RUNTIME = importlib.util.find_spec('babeldoc') is not None and bool(os.environ.get('TWINTEXT_BABEL_ASSETS'))


@unittest.skipUnless(HAS_RUNTIME, 'Requires BabelDOC runtime and verified local font assets')
class NativeTranslationTests(unittest.TestCase):
    """Exercise the real parser, bridge input and final searchable PDF styles."""
    def fixture(self, graphics_only=False):
        import pymupdf
        doc = pymupdf.open()
        page = doc.new_page(width=500, height=420)
        x = 30
        for text, font, color in [('The ', 'helv', (0,0,0)),
                ('important result', 'hebo', (0.8,0,0)), (' is ', 'helv', (0,0,0)),
                ('robust', 'heit', (0,0,0)), ('.', 'helv', (0,0,0))]:
            page.insert_text((x,45), text, fontname=font, fontsize=12, color=color)
            x += pymupdf.get_text_length(text, fontname=font, fontsize=12)
        page.insert_text((30,75), 'The experiment confirms the same conclusion.', fontsize=12)
        page.insert_text((30,110), 'x + y = z', fontname='tiit', fontsize=12)
        page.draw_rect((30,145,235,220), color=(0,0,0))
        page.insert_text((45,175), 'Control group', fontsize=11)
        page.insert_text((45,200), '95.2', fontsize=11)
        page.insert_text((30,240), 'Figure 1. Experiment overview.', fontsize=11)
        for y in (270,300,330):page.draw_line((30,y),(350,y))
        page.draw_line((190,270),(190,330))
        for x,y,text in [(40,290,'Outcome'),(210,290,'Treatment'),(40,320,'12'),(210,320,'95.2')]:
            page.insert_text((x,y),text,fontsize=11)
        if graphics_only:
            page.add_redact_annot((0,0,500,130),fill=None)
            page.apply_redactions(images=0,graphics=0)
        data=doc.tobytes();doc.close();return data

    def run_translation(self, rich, graphics, graphics_only=False, collector=None, preview=None):
        import numpy as np
        from babel_adapter import run
        class Model:
            def handle_document(self,pages,document,config,callback):
                for page in pages:
                    boxes=[]
                    for kind,box in enumerate([(20,20,470,85),(20,95,150,120),
                            (25,140,240,225),(20,228,370,250),(25,265,355,335)]):
                        boxes.append(N(xyxy=np.array(box,dtype=float),conf=np.float32(1),cls=kind))
                    yield page,N(boxes=boxes,names=['plain text','isolate_formula','figure','figure_caption','table'])
        requests=[]
        def bridge(text):
            requests.append(text)
            replacements={'important result':'重要结果','robust':'稳健性','The ':'该',
                ' is ':'具有','The experiment confirms the same conclusion.':'实验验证了相同结论。',
                'Control group':'对照组','Outcome':'结果','Treatment':'处理组',
                'Figure 1. Experiment overview.':'图 1。实验概览。'}
            for source,target in sorted(replacements.items(),key=lambda item:-len(item[0])):
                text=text.replace(source,target)
            return text
        with tempfile.TemporaryDirectory() as folder,patch('babel_runtime.layout_model',return_value=Model()):
            _,output=run(self.fixture(graphics_only),Path(folder),dict(sourceLanguage='en',targetLanguage='zh-CN',
                documentExport=True,documentOptions=dict(preserveRichText=rich,translateFigureTableText=graphics),pages='1'),
                bridge,collector=collector,on_preview=preview,cancel_event=threading.Event())
        return requests,output

    def test_graphics_only_page_counts_actual_label_translations_as_completed_text(self):
        for enabled in (False,True):
            with self.subTest(graphics=enabled):
                requests,output=self.run_translation(True,enabled,graphics_only=True)
                self.assertTrue(output.startswith(b'%PDF-'))
                self.assertEqual(any('Control group' in text for text in requests),enabled)
                self.assertTrue(any('Experiment overview' in text for text in requests))

    def test_progressive_preview_and_local_reflow_keep_rich_styles(self):
        import pymupdf
        from native_artifacts import reflow
        artifact,frames={},[]
        self.run_translation(True,True,collector=artifact,preview=frames.append)
        self.assertTrue(any(event.get('png') for event in frames),
            [event.get('type') for event in frames])
        with tempfile.TemporaryDirectory() as folder:
            result=reflow(artifact,Path(folder),dict(fontScale=110,fontFamily='sans'),threading.Event())
        with pymupdf.open(stream=base64.b64decode(result['pdf']),filetype='pdf') as doc:
            spans=[s for b in doc[0].get_text('dict')['blocks'] if 'lines' in b
                   for line in b['lines'] for s in line['spans']]
            marked=[s for s in spans if '重要结果' in s['text']]
            self.assertTrue(any(s['flags'] & 16 and s['color'] for s in marked))
            self.assertIn('对照组',doc[0].get_text())

    def test_real_rich_text_markers_and_final_color_follow_the_switch(self):
        import pymupdf
        for rich in (True,False):
            with self.subTest(rich=rich):
                requests,output=self.run_translation(rich,False)
                paired=any(re.search(r'<b\d+>.*?</b\d+>',text) for text in requests)
                self.assertEqual(paired,rich)
                self.assertFalse(any('x + y' in text for text in requests))
                with pymupdf.open(stream=output,filetype='pdf') as doc:
                    text=unicodedata.normalize('NFKC',doc[0].get_text())
                    self.assertIn('重要结果',text)
                    self.assertIn('Control group',text)
                    self.assertIn('Outcome',text)
                    spans=[s for b in doc[0].get_text('dict')['blocks'] if 'lines' in b
                           for line in b['lines'] for s in line['spans']]
                    marked=[s for s in spans if '重要结果' in s['text']]
                    self.assertTrue(marked)
                    self.assertEqual(any(s['color'] != 0 for s in marked),rich)
                    self.assertEqual(any(s['flags'] & 16 for s in marked),rich)
                    if rich:
                        regular=next(s['font'] for s in spans if s['text']=='该')
                        italic=next(s['font'] for s in spans if '稳健性' in s['text'])
                        self.assertNotEqual(italic,regular)

    def test_graphic_switch_controls_native_labels_but_keeps_numbers_and_captions(self):
        import pymupdf
        for enabled in (False,True):
            with self.subTest(graphics=enabled):
                requests,output=self.run_translation(True,enabled)
                for label in ('Control group','Outcome','Treatment'):
                    self.assertEqual(any(label in text for text in requests),enabled)
                self.assertTrue(any('Experiment overview' in text for text in requests))
                with pymupdf.open(stream=output,filetype='pdf') as doc:
                    text=unicodedata.normalize('NFKC',doc[0].get_text())
                    self.assertIn('95.2',text)
                    self.assertIn('12',text)
                    for label in (('对照组','结果','处理组') if enabled else ('Control group','Outcome','Treatment')):
                        self.assertIn(label,text)
                    with pymupdf.open(stream=self.fixture(),filetype='pdf') as original:
                        expected=[word[:5] for word in original[0].get_text('words') if word[4] in ('12','95.2')]
                    actual=[word[:5] for word in doc[0].get_text('words') if word[4] in ('12','95.2')]
                    self.assertEqual(len(actual),len(expected))
                    for a,b in zip(sorted(actual),sorted(expected)):
                        self.assertEqual(a[4],b[4])
                        for first,second in zip(a[:4],b[:4]):self.assertAlmostEqual(first,second,places=3)


if __name__ == '__main__':unittest.main()
