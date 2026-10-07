import copy,json,re,unittest
from pathlib import Path
from types import SimpleNamespace as N
from structure_plan import analyze_rows,analyze,REVISION
from test_reference_layout import page,paragraph,char
FIXTURES=json.loads(Path(__file__).with_name('fixtures').joinpath('structure-rows.json').read_text())
def row(text,top,left=.1,bold=False,**extra):return dict(text=text,rect=dict(left=left,top=top,width=.75-left,height=.02),fontSize=10,fontBold=bold,**extra)
class StructureTests(unittest.TestCase):
 def test_bibliography_preserves_23_literal_labels_and_source_lines(self):
  fixture=next(f for f in FIXTURES if f['name']=='plants');before=copy.deepcopy(fixture);result=analyze_rows(fixture['pages'])
  self.assertEqual(result['revision'],REVISION);self.assertEqual([e['label'] for e in result['entries']],[f'{i}.' for i in range(1,24)])
  self.assertTrue(all(e['text'].startswith(e['label']) and e['lines'] for e in result['entries']));self.assertEqual(before,fixture)
 def test_cross_page_and_column_continuations_stop_before_appendix(self):
  fixture=next(f for f in FIXTURES if f['name']=='weather');result=analyze_rows(fixture['pages'])
  self.assertEqual([int(re.search(r'\d+',e['label'])[0]) for e in result['entries'] if e['label']],list(range(1,35)))
  self.assertTrue(any(e.get('continuation') for e in result['entries']));self.assertFalse(any(re.match(r'Appendix|Table\s',e['text'],re.I) for e in result['entries']))
  ignored=analyze_rows(fixture['pages'],dict(ignoreReferences=True,ignoreHeadersFooters=True))
  self.assertTrue(ignored['exclusions']);self.assertFalse(any(re.match(r'Appendix|Table\s',e['text'],re.I) for e in ignored['exclusions']));self.assertFalse(any(e['kind']=='reference' for e in ignored['entries']))
 def test_real_numbered_and_bulleted_instructions_keep_five_independent_items(self):
  for fixture in (f for f in FIXTURES if f['name'].startswith('list-')):
   with self.subTest(fixture=fixture['name']):
    entries=analyze_rows(fixture['pages'])['entries'];self.assertEqual(len(entries),5);self.assertTrue(all(e['kind']=='list' and e['label'] and len(e['lines'])>1 for e in entries))
 def test_alpha_items_keep_wrapped_lines_and_literal_labels(self):
  rows=[row('a) First instruction',.2),row('continuation of first instruction',.225,left=.14),row('b) Second instruction',.26)]
  entries=analyze_rows([dict(pageIndex=0,rows=rows)])['entries'];self.assertEqual([e['label'] for e in entries],['a)','b)']);self.assertEqual(len(entries[0]['lines']),2)
 def test_contents_keeps_hierarchy_styles_and_page_labels(self):
  rows=[row('Contents',.1),row('1 Introduction . . . . 3',.2,bold=True),row('1.1 Scope . . . . 4',.24,left=.14),row('2 Results . . . . 9',.28,bold=True)]
  entries=analyze_rows([dict(pageIndex=0,rows=rows)])['entries'];self.assertEqual([e['pageLabel'] for e in entries],['3','4','9']);self.assertEqual([e['label'] for e in entries],['1','1.1','2'])
  self.assertTrue(entries[0]['fontBold']);self.assertGreater(entries[1]['rect']['left'],entries[0]['rect']['left'])
 def test_prose_dates_citations_tables_and_footnotes_are_not_structured_entries(self):
  rows=[row('The 2020 results show [1] and [2]. Step 1. Use the input.',.2),row('Footnote explains the main result.',.92,kind='footnote'),row('1. table row',.4,kind='table'),row('2. table row',.5,kind='table')]
  result=analyze_rows([dict(pageIndex=0,rows=rows)],dict(ignoreReferences=True,ignoreHeadersFooters=True));self.assertEqual(result['entries'],[]);self.assertEqual(result['exclusions'],[])
 def test_repeated_margins_keep_top_table_captions(self):
  pages=[dict(pageIndex=i,rows=[row(f'Journal 2026 page {i+1}',.03),row(f'Table {i+1}. Results',.06,kind='caption'),row('Ordinary paragraph',.2)]) for i in range(2)]
  result=analyze_rows(pages,dict(ignoreHeadersFooters=True));self.assertEqual(len(result['exclusions']),2);self.assertTrue(all(e['reason']=='headersFooters' for e in result['exclusions']))
 def test_native_glyph_analysis_needs_no_frontend_and_keeps_input_untouched(self):
  doc=N(page=[page([paragraph('one',[char('a',10),char(')',12),char('First',20)]),paragraph('two',[char('b',10,50),char(')',12,50),char('Second',20,50)])])]);before=copy.deepcopy(doc)
  result=analyze(doc,N());self.assertEqual([e['label'] for e in result['entries']],['a)','b)']);self.assertEqual(doc.page[0].pdf_paragraph[0].unicode,before.page[0].pdf_paragraph[0].unicode)
 def test_cancellation_checked_inside_structure_planning(self):
  def check():raise RuntimeError('Cancelled')
  with self.assertRaisesRegex(RuntimeError,'Cancelled'):analyze_rows(FIXTURES[0]['pages'],check=check)
 def test_numbered_section_headings_remain_body_sections(self):
  rows=[row('1. Introduction',.1,kind='title'),row('Ordinary prose paragraph.',.14),row('2. Methods',.3,kind='section_header'),row('Another prose paragraph.',.34)]
  self.assertEqual(analyze_rows([dict(pageIndex=0,rows=rows)])['entries'],[])
if __name__=='__main__':unittest.main()
