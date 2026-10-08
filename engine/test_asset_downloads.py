import asyncio,hashlib,tempfile,unittest
from pathlib import Path
import httpx
from asset_downloads import transfer,ranked,valid

class Downloads(unittest.TestCase):
    def test_resume_and_digest_verification(self):
        body=b'valid-font-contents';item={'bytes':len(body),'sha3_256':hashlib.sha3_256(body).hexdigest()};seen=[]
        async def handler(request):
            seen.append(request.headers.get('Range'));return httpx.Response(206,content=body[5:],headers={'Content-Range':f'bytes 5-{len(body)-1}/{len(body)}'})
        async def run(path):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:await transfer(client,'https://source/font',path,item)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'font.ttf';path.with_suffix('.ttf.part').write_bytes(body[:5]);asyncio.run(run(path));self.assertTrue(valid(path,item));self.assertEqual(seen,['bytes=5-'])
    def test_ignored_range_restarts_and_corrupt_source_is_rejected(self):
        body=b'font';item={'bytes':4,'sha3_256':hashlib.sha3_256(body).hexdigest()}
        async def run(path,content):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=content))) as client:await transfer(client,'https://source/font',path,item)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'font';path.with_suffix('.part').write_bytes(b'fo');asyncio.run(run(path,body));self.assertEqual(path.read_bytes(),body)
            with self.assertRaises(ValueError):asyncio.run(run(path,b'fake'))
            self.assertFalse(path.with_suffix('.part').exists());self.assertEqual(path.read_bytes(),body)
    def test_measured_source_selection_rejects_html(self):
        async def handler(request):
            if request.url.host=='gateway':return httpx.Response(200,content=b'html',headers={'content-type':'text/html'})
            await asyncio.sleep(.001 if request.url.host=='fast' else .03);return httpx.Response(200,content=b'x'*65536)
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:return await ranked(client,['https://slow/x','https://gateway/x','https://fast/x'])
        self.assertEqual(asyncio.run(run()),['https://fast/x','https://slow/x','https://gateway/x'])

if __name__=='__main__':unittest.main()
