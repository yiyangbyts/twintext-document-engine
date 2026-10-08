"""No SDK dependency: lifecycle bounds of the optional native reflow cache."""
import unittest
from unittest.mock import patch
from native_artifacts import ArtifactStore
class ArtifactStoreTests(unittest.TestCase):
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
