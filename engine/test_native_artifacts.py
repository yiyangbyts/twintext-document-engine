"""No SDK dependency: lifecycle bounds of the optional native reflow cache."""
import sys,threading,unittest
from types import SimpleNamespace,ModuleType
from unittest.mock import patch
from native_artifacts import ArtifactStore,capture
class ArtifactStoreTests(unittest.TestCase):
 def test_entry_kind_and_page_offset_survive_capture_and_restore_after_failure(self):
  local=threading.local();local.page=19;local.kind='toc';seen=[]
  class Translator:
   def translate_paragraph(self,paragraph,page):
    seen.append((local.page,local.kind))
    if getattr(paragraph,'fail',False):raise ValueError('provider failure')
    return 'sent'
  level=SimpleNamespace(ILTranslator=Translator,Typesetting=type('Typesetter',(),{}))
  module=ModuleType('babeldoc.format.pdf');module.high_level=level
  config=SimpleNamespace(translator=SimpleNamespace(twintext_context=local),twintext_page_offset=16)
  paragraph=SimpleNamespace(debug_id='p',unicode='Heading',layout_label='plain text');page=SimpleNamespace(page_number=3)
  with patch.dict(sys.modules,{'babeldoc.format.pdf':module}),patch('native_artifacts.paragraph_text',return_value='Heading'),capture(config,None,{}):
   self.assertEqual(level.ILTranslator().translate_paragraph(paragraph,page),'sent');self.assertEqual((local.page,local.kind),(19,'toc'))
   local.page=None;local.kind=None;paragraph.fail=True
   with self.assertRaisesRegex(ValueError,'provider failure'):level.ILTranslator().translate_paragraph(paragraph,page)
   self.assertEqual((local.page,local.kind),(None,None))
  self.assertEqual(seen,[(19,'toc'),(19,'plain text')]);self.assertIs(level.ILTranslator,Translator)
 def test_expired_or_unknown_handles_do_not_load_client_objects(self):
  store=ArtifactStore()
  with patch('native_artifacts.time.monotonic',return_value=1):key=store.put({'source':b'local'})
  with patch('native_artifacts.time.monotonic',return_value=3602):
   with self.assertRaisesRegex(ValueError,'native_artifact_expired'):store.get(key)
  with self.assertRaisesRegex(ValueError,'native_artifact_expired'):store.get('not-a-handle')
 def test_only_two_recent_documents_are_retained(self):
  store=ArtifactStore()
  with patch('native_artifacts.time.monotonic',return_value=1):a=store.put({'id':'a'})
  with patch('native_artifacts.time.monotonic',return_value=2):b=store.put({'id':'b'})
  with patch('native_artifacts.time.monotonic',return_value=3):c=store.put({'id':'c'})
  self.assertNotIn(a,store.values);self.assertIn(b,store.values);self.assertIn(c,store.values)
if __name__=='__main__':unittest.main()
