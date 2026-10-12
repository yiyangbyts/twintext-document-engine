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
    def test_completed_partial_is_verified_and_promoted_without_network(self):
        body=b'completed-font';item={'bytes':len(body),'sha3_256':hashlib.sha3_256(body).hexdigest()};seen=[]
        async def run(path):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:(_ for _ in ()).throw(AssertionError('network unnecessary')))) as client:
                await transfer(client,'https://source/font',path,item,seen.append)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'font';path.with_suffix('.part').write_bytes(body);asyncio.run(run(path))
            self.assertEqual(path.read_bytes(),body);self.assertEqual(seen,[len(body)])
    def test_byte_progress_tracks_resume_and_range_restart(self):
        body=b'font-contents';item={'bytes':len(body),'sha3_256':hashlib.sha3_256(body).hexdigest()}
        for status in (200,206):
            seen=[]
            async def run(path):
                response=httpx.Response(status,content=body if status==200 else body[4:],headers={} if status==200 else {'Content-Range':f'bytes 4-{len(body)-1}/{len(body)}'})
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:response)) as client:await transfer(client,'https://source/font',path,item,seen.append)
            with tempfile.TemporaryDirectory() as root:
                path=Path(root)/'font';path.with_suffix('.part').write_bytes(body[:4]);asyncio.run(run(path))
                self.assertEqual(seen[0],0 if status==200 else 4);self.assertEqual(seen[-1],len(body))

if __name__=='__main__':unittest.main()
