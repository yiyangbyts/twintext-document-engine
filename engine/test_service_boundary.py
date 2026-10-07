import json,tempfile,threading,unittest,urllib.request,urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import service
from service import Jobs,handler
class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.jobs=Jobs('babeldoc','.')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.jobs,{'id':'test','port':0}))
        self.server.RequestHandlerClass=handler(self.jobs,{'id':'test','port':self.server.server_port})
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.root='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.jobs.pool.shutdown(wait=True,cancel_futures=True)
    def request(self,path,data=None,origin=None):
        headers={'Content-Type':'application/json'}
        if origin is not None:headers['Origin']=origin
        request=urllib.request.Request(self.root+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(request,timeout=2) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as error:return error.code,json.load(error)
    def test_invalid_query_returns_json_and_service_stays_healthy(self):
        self.assertEqual(self.request('/v1/jobs/abc?after=invalid')[0],400)
        self.assertEqual(self.request('/health')[0],200)
        self.assertEqual(self.request('/v1/jobs/a/unknown')[0],404)
    def test_non_object_and_retired_operations_fail_before_queue(self):
        for payload in [[],['a'],{'liveParse':True},{'officialParse':True},{'png':'data'}]:
            self.assertEqual(self.request('/v1/jobs',payload)[0],400)
        self.assertFalse(self.jobs.jobs)
        self.assertEqual(self.request('/v1/documents',{})[0],404)
        with self.assertRaises(ValueError):Jobs('mineru-vlm','.')
    def test_origin_prefix_spoof_is_rejected_and_zotero_origin_is_accepted(self):
        for origin in ['chrome://zotero.evil','chrome://zotero@evil','chrome://zotero/evil','https://evil']:
            self.assertEqual(self.request('/health',origin=origin)[0],403)
        for origin in ['chrome://zotero','chrome://zotero/','']:
            self.assertEqual(self.request('/health',origin=origin)[0],200)
    def test_source_endpoint_preserves_local_archives_and_redirects_to_exact_public_version(self):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        opener=urllib.request.build_opener(NoRedirect)
        with tempfile.TemporaryDirectory() as temp,patch.object(service,'__file__',str(Path(temp)/'service.py')):
            archive=Path(temp)/'engine-source.zip';archive.write_bytes(b'PK-legacy-source')
            with opener.open(self.root+'/v1/source',timeout=2) as response:
                self.assertEqual(response.status,200);self.assertEqual(response.read(),b'PK-legacy-source')
            archive.unlink()
            self.assertEqual(self.request('/v1/source')[0],404)
            repository='https://github.com/yiyangbyts/twintext-document-engine'
            url=repository+'/releases/download/v2.0.7/twintext-engine-source-2.0.7.zip'
            manifest=Path(temp)/'source-distribution.json'
            manifest.write_text(json.dumps(dict(schema=1,version='2.0.7',repository=repository,archive=url)))
            with self.assertRaises(urllib.error.HTTPError) as redirected:
                opener.open(self.root+'/v1/source',timeout=2)
            self.assertEqual(redirected.exception.code,302);self.assertEqual(redirected.exception.headers['Location'],url);redirected.exception.close()
            manifest.write_text(json.dumps(dict(schema=1,version='2.0.7',repository=repository,archive='https://other.example/source.zip')))
            self.assertEqual(self.request('/v1/source')[0],503)
            self.assertEqual(self.request('/health')[0],200)
