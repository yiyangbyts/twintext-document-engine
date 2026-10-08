"""Persistent reflow, visible-page priority, cancellation and data boundaries.
Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
"""
import base64,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import pymupdf
from babeldoc.format.pdf.document_il.il_version_1 import Document,Page,PdfParagraph,Box
from native_reflow import encode,decode,classes,save_part,save_manifest,load_manifest,load_part,run

class ReflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.source=self.root/'source.pdf'
        with pymupdf.open() as document:
            for n in range(34):document.new_page().insert_text((30,50),f'Source {n}')
            document.set_toc([[1,'First',1],[1,'Last',34]])
            document[1].insert_link({'kind':pymupdf.LINK_GOTO,'from':pymupdf.Rect(30,50,90,70),'page':33})
            document.save(self.source)
        self.parts=[]
        for first,last in [(0,15),(16,31),(32,33)]:
            with pymupdf.open(self.source) as source,pymupdf.open() as part:
                part.insert_pdf(source,from_page=first,to_page=last);pdf=part.tobytes()
            artifact=dict(document=Document(page=[Page(page_number=n,pdf_paragraph=[PdfParagraph(unicode='译文',box=Box(x=1,y=2,x2=3,y2=4))]) for n in range(last-first+1)]),
                references={0:[dict(label=PdfParagraph(unicode='1.'),parents=('a','b'))]},preserved_ids={'ignored'},sources={(0,'a'):'Source'},source=pdf,prepared=pdf)
            self.parts.append(save_part(artifact,self.root/f'{first}.il.gz',first,last))
        self.manifest=save_manifest(self.root,self.source,list(range(1,34)),34,self.parts)
    def test_typed_roundtrip_preserves_formula_objects_reference_keys_and_sets(self):
        artifact=load_part(self.root,self.parts[0]);restored=decode(encode(artifact),classes())
        self.assertIsInstance(restored['document'],Document);self.assertEqual(restored['sources'][(0,'a')],'Source')
        self.assertIsInstance(restored['references'][0][0]['label'],PdfParagraph);self.assertEqual(restored['preserved_ids'],{'ignored'})
        restored['document'].page[0].pdf_paragraph[0].unicode='changed'
        self.assertEqual(load_part(self.root,self.parts[0])['document'].page[0].pdf_paragraph[0].unicode,'译文')
        with self.assertRaises(ValueError):decode({'type':'os.system','fields':{}},classes())
        with self.assertRaises(ValueError):decode({'type':'Document','fields':{'__class__':'code'}},classes())
    def reflow(self,artifact,folder,options,cancel):
        if cancel.is_set():raise RuntimeError('cancelled')
        with pymupdf.open(stream=artifact['source'],filetype='pdf') as doc:
            for page in artifact['document'].page:doc[page.page_number].insert_text((30,100),f"Appearance {options['fontScale']}")
            return dict(pdf=base64.b64encode(doc.tobytes()).decode())
    def test_restart_reflows_34_pages_without_parser_or_model_and_prioritizes_visible_page(self):
        order=[];previews=[]
        def reflow(artifact,*args):order.append([p.page_number for p in artifact['document'].page]);return self.reflow(artifact,*args)
        payload=dict(artifactFile=self.manifest,currentPage=30,outputFile=str(self.root/'formatted.pdf'),documentOptions={'fontScale':120})
        with patch('native_artifacts.reflow',reflow):result=run(payload,self.root/'work',threading.Event(),previews.append)
        self.assertEqual(order[0],[14]);self.assertEqual(previews[0]['pageIndex'],30);self.assertEqual(len(order),4)
        self.assertEqual(result['artifactFile'],self.manifest);self.assertNotIn('pdf',result)
        with pymupdf.open(result['pdfFile']) as document:
            self.assertEqual(document.page_count,34);self.assertNotIn('Appearance',document[0].get_text())
            self.assertTrue(all('Appearance 120' in document[n].get_text() for n in range(1,34)))
            self.assertEqual(document.get_toc()[1][2],34);self.assertEqual(document[1].get_links()[0]['page'],33)
    def test_superseded_reflow_stops_after_preview_and_never_writes_output(self):
        cancel=threading.Event();payload=dict(artifactFile=self.manifest,currentPage=30,outputFile=str(self.root/'cancelled.pdf'),documentOptions={'fontScale':115})
        with patch('native_artifacts.reflow',self.reflow),self.assertRaisesRegex(RuntimeError,'cancelled'):
            run(payload,self.root/'work',cancel,lambda _:cancel.set())
        self.assertFalse(Path(payload['outputFile']).exists())
    def test_corrupt_checkpoint_and_traversal_are_rejected(self):
        path=self.root/self.parts[0]['path'];path.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'native_artifact_expired'):load_part(self.root,self.parts[0])
        value=json.loads(Path(self.manifest).read_text());value['parts'][0]['path']='../other.gz';Path(self.manifest).write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'checkpoint path'):load_manifest(self.manifest)
    def test_missing_part_never_produces_a_partial_reflow_that_removes_translations(self):
        self.assertIsNone(save_manifest(self.root,self.source,list(range(34)),34,self.parts[:1]))

if __name__=='__main__':unittest.main()
