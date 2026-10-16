"""Incremental snapshot fidelity, resource deduplication and corruption checks."""
import copy, dataclasses, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from babeldoc.format.pdf.document_il.il_version_1 import Document,Page,PdfParagraph,Box
from native_snapshot import save,load,persist,exported_pages
from native_reflow import save_part,load_part,encode


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.pdf=self.root/'original.pdf';self.pdf.write_bytes(b'%PDF-resource')
        self.document=Document(total_pages=16,page=[Page(page_number=n,pdf_paragraph=[
            PdfParagraph(debug_id=f'p{n}',unicode='中文译文',box=Box(x=1,y=2,x2=3,y2=4))]) for n in range(16)])
        self.artifact=dict(document=self.document,sources={(n,f'p{n}'):'Original body' for n in range(16)},
            references={},preserved_ids=set(),preserved=[],pageCount=16,isolation=False,pages=None,langIn='en',langOut='zh-CN')

    def test_streamed_pages_preserve_exact_il_and_deduplicate_pdf_resources(self):
        original=copy.deepcopy(self.document)
        with patch('native_reflow.encode',side_effect=AssertionError('Must not build a full encoded tree')):
            path=save(self.artifact,self.root/'live.il.gz',dict(source=self.pdf,prepared=self.pdf,canonicalSource=self.pdf))
        self.assertEqual(len(list((self.root/'resources').iterdir())),1)
        self.document.page[0].pdf_paragraph[0].unicode='mutated after snapshot'
        loaded=load(path)
        self.assertEqual(encode(loaded['document']),encode(original))
        self.assertEqual(loaded['sources'],self.artifact['sources'])
        self.assertEqual(loaded['prepared'],b'%PDF-resource')
        self.assertEqual(len(list(exported_pages(path))),16)
        output=self.root/'persisted';output.mkdir()
        part=save_part({'snapshotFile':path},output/'0-15.il.gz',0,15)
        self.assertEqual(encode(load_part(output,part)['document']),encode(original))

    def test_corrupt_resource_and_invalid_type_fail_closed(self):
        path=save(self.artifact,self.root/'live.il.gz',dict(source=self.pdf))
        next((self.root/'resources').iterdir()).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'Corrupt snapshot resource'):load(path)
        self.artifact['unsupported']=object()
        with self.assertRaises(ValueError):save(self.artifact,self.root/'invalid.il.gz',{})
        self.assertFalse((self.root/'invalid.il.gz').exists())


if __name__=='__main__':unittest.main()
