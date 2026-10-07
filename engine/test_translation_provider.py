import io,json,unittest,urllib.error
from unittest.mock import patch
from translation_provider import HTTPTranslator,TranslationProviderError
class ProviderTests(unittest.TestCase):
 def provider(self):return HTTPTranslator('http://127.0.0.1:4567/v1','local-model','secret')
 def test_generic_api_preserves_formula_tags_and_credentials_stay_in_headers(self):
  seen=[]
  def request(req,timeout):
   seen.append(req);return io.BytesIO(json.dumps({'choices':[{'message':{'content':'中文 <b0>公式</b0>'}}]}).encode())
  with patch('urllib.request.urlopen',request):self.assertEqual(self.provider()('Source <b0>formula</b0>'),'中文 <b0>公式</b0>')
  self.assertNotIn('secret',seen[0].data.decode());self.assertEqual(seen[0].get_header('Authorization'),'Bearer secret');self.assertTrue(seen[0].full_url.endswith('/v1/chat/completions'))
 def test_missing_tags_fail_instead_of_corrupting_math(self):
  with patch('urllib.request.urlopen',lambda *a,**kw:io.BytesIO(b'{"choices":[{"message":{"content":"wrong"}}]}')):
   with self.assertRaisesRegex(TranslationProviderError,'formula placeholders'):self.provider()('Source <b0>formula</b0>')
 def test_cancelled_translation_does_not_issue_http_request(self):
  provider=self.provider();provider.cancel.set()
  with patch('urllib.request.urlopen') as request:
   with self.assertRaisesRegex(RuntimeError,'cancelled'):provider('Hello')
   request.assert_not_called()
 def test_non_transient_failure_does_not_expose_body_or_key(self):
  error=urllib.error.HTTPError('url',401,'secret',{},io.BytesIO(b'secret-body'))
  with patch('urllib.request.urlopen',side_effect=error) as request:
   with self.assertRaisesRegex(TranslationProviderError,'HTTP 401') as caught:self.provider()('Hello')
  self.assertNotIn('secret',str(caught.exception));self.assertEqual(request.call_count,1)
if __name__=='__main__':unittest.main()
