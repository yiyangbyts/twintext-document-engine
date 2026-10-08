"""Exercise actual downloader destinations without downloading upstream assets."""
import hashlib,io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import download_model


class DownloadDestination(unittest.TestCase):
    def test_progress_json_remains_utf8_readable_with_windows_gbk_stdout(self):
        pipe=io.BytesIO();stdout=io.TextIOWrapper(pipe,encoding='gbk')
        message='下载并校验 BabelDOC 原生版面模型、字体与资源…'
        with patch('sys.stdout',stdout):download_model.emit('download',message,13)
        raw=pipe.getvalue();self.assertTrue(all(n<128 for n in raw))
        self.assertEqual(json.loads(raw.decode('utf-8'))['message'],message)
    def run_download(self, corrupt=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'managed';root.mkdir()
            external=Path(temp)/'external';external.mkdir();(external/'sentinel').write_bytes(b'original')
            content=b'pinned asset';digest=hashlib.sha3_256(content).hexdigest()
            (root/'model-manifest.json').write_text(json.dumps({'backend':'babeldoc','assets':[{'path':'assets/models/a.onnx','bytes':len(content),'sha3_256':digest}]}))
            const=types.ModuleType('babeldoc.const');const.CACHE_FOLDER=external
            assets=types.ModuleType('babeldoc.assets.assets')
            def warmup():
                file=const.CACHE_FOLDER/'models/a.onnx';file.parent.mkdir(parents=True,exist_ok=True)
                file.write_bytes(b'wrong content' if corrupt else content)
            assets.warmup=warmup
            assets.generate_all_assets_file_list=lambda:{'models':[{'name':'a.onnx','sha3_256':digest}]}
            assets.verify_file=lambda path,value:hashlib.sha3_256(path.read_bytes()).hexdigest()==value
            package=types.ModuleType('babeldoc');package.__path__=[];package.const=const
            folder=types.ModuleType('babeldoc.assets');folder.__path__=[]
            with patch.object(download_model,'ROOT',root),patch.dict(sys.modules,{'babeldoc':package,'babeldoc.const':const,'babeldoc.assets':folder,'babeldoc.assets.assets':assets}),patch.dict(os.environ,{'TWINTEXT_BABEL_ASSETS':str(external)}),patch.object(download_model,'emit'),patch('asset_downloads.prepare'):
                if corrupt:
                    with self.assertRaisesRegex(RuntimeError,'Pinned BabelDOC asset verification failed'):download_model.main()
                else:
                    download_model.main()
                    self.assertEqual(const.CACHE_FOLDER,(root/'assets').resolve())
                    self.assertEqual((root/'assets/models/a.onnx').read_bytes(),content)
                    self.assertTrue((root/'model/babel-assets.json').is_file())
            self.assertEqual(list(external.iterdir()),[external/'sentinel'])
            self.assertEqual((external/'sentinel').read_bytes(),b'original')

    def test_download_is_owned_and_external_assets_untouched(self):self.run_download()
    def test_pinned_asset_corruption_is_rejected(self):self.run_download(corrupt=True)


if __name__=='__main__':unittest.main()
