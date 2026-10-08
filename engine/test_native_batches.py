"""Large-document, resume and fault-isolation regression tests.
Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
"""
import base64, tempfile, threading, unittest
from pathlib import Path
import pymupdf
from native_batches import run_document, digest,page_limit
from service import pdf_input,Jobs
from native_artifacts import extract,comparison
from unittest.mock import patch

class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.source=self.root/'source.pdf'
        with pymupdf.open() as doc:
            for n in range(305):
                page=doc.new_page(width=500,height=700);page.insert_text((30,50),'References' if n==14 else f'Original page {n}')
                if n==18:page.set_rotation(90)
            doc.set_toc([[1,'Beginning',1],[1,'Middle',155],[1,'End',305]])
            doc[0].insert_link({'kind':pymupdf.LINK_GOTO,'from':pymupdf.Rect(30,50,100,70),'page':304,'to':pymupdf.Point(0,0)})
            doc.save(self.source)
        self.memory=patch('native_batches.available_memory',return_value=16*1024**3);self.memory.start()
        self.calls=[];self.states=[];self.bridge=lambda text:'Translated';self.bridge.retained_count=0
    def tearDown(self):self.memory.stop();self.temp.cleanup()
    def single(self,data,folder,payload,bridge,progress,cancel,on_preview,on_control,collector):
        with pymupdf.open(stream=data,filetype='pdf') as doc:
            self.calls.append(doc.page_count);self.states.append(payload['_structureState']['inReferences'])
            for page in doc:
                page.insert_text((30,100),'Translated paragraph')
            if on_preview:on_preview(dict(type='native-page-preview',profile='native-document-9029-r1',pageIndex=0,revision=1,pdf=base64.b64encode(data).decode()))
            return [],doc.tobytes()
    def run_batch(self,**extra):
        collector={};events=[]
        result=run_document(self.source,self.root/'work',dict(outputFile=str(self.root/'result.pdf'),currentPage=152,**extra),self.single,self.bridge,on_preview=events.append,collector=collector)
        return result,collector,events
    def test_305_pages_bounded_parts_native_scope_bookmarks_rotation_and_checkpoint_resume(self):
        (_,output),collector,events=self.run_batch()
        self.assertEqual(max(self.calls),16);self.assertEqual(sum(self.calls),305)
        self.assertTrue(self.states[0]);self.assertEqual(events[0]['pageIndex'],144)
        with pymupdf.open(output) as doc:
            self.assertEqual(doc.page_count,305);self.assertEqual(doc[18].rotation,90)
            self.assertEqual(doc.get_toc()[1][2],155);self.assertEqual(doc[0].get_links()[0]['page'],304)
            self.assertTrue(all('Translated paragraph' in page.get_text() for page in doc))
        self.assertEqual(collector['failedPages'],[]);self.calls.clear();self.run_batch();self.assertEqual(self.calls,[])
    def test_page_failure_and_memory_pressure_split_only_affected_parts(self):
        normal=self.single
        def failing(data,*args):
            with pymupdf.open(stream=data,filetype='pdf') as doc:
                if 'Original page 70' in ''.join(p.get_text() for p in doc):raise ValueError('broken page')
                if doc.page_count>8:raise MemoryError('synthetic worker pressure')
            return normal(data,*args)
        self.single=failing
        (_,output),collector,_=self.run_batch()
        self.assertEqual(collector['failedPages'],[70]);self.assertLessEqual(max(self.calls),8)
        with pymupdf.open(output) as doc:
            self.assertNotIn('Translated paragraph',doc[70].get_text());self.assertIn('Translated paragraph',doc[304].get_text())
    def test_fatal_model_failure_is_not_repeated_per_page(self):
        count=0
        def failed(*args):
            nonlocal count
            count+=1;error=RuntimeError('401');error.twintext_translation_failure=True;raise error
        self.single=failed
        with self.assertRaisesRegex(RuntimeError,'401'):self.run_batch()
        self.assertEqual(count,1)
    def test_checkpoint_cancel_resumes_completed_parts_but_retries_retained_content(self):
        normal=self.single;cancel=threading.Event();count=0
        def part(*args):
            nonlocal count
            result=normal(*args);count+=1
            if count==2:cancel.set()
            return result
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            run_document(self.source,self.root/'work',dict(outputFile=str(self.root/'result.pdf')),part,self.bridge,cancel_event=cancel)
        self.calls.clear();self.run_batch();self.assertEqual(sum(self.calls),305-32)
        self.calls.clear()
        def retained(*args):self.bridge.retained_count+=1;return normal(*args)
        self.single=retained;self.run_batch(cacheKey='retained');self.calls.clear();self.run_batch(cacheKey='retained')
        self.assertEqual(sum(self.calls),305)
    def test_selected_scope_keeps_other_pages_and_global_preview_indexes(self):
        (_,output),collector,events=self.run_batch(pages='18-22,300-305')
        with pymupdf.open(output) as doc:
            self.assertEqual(doc.page_count,305);self.assertNotIn('Translated paragraph',doc[0].get_text())
            self.assertIn('Translated paragraph',doc[17].get_text());self.assertNotIn('Translated paragraph',doc[22].get_text())
        self.assertEqual(collector['failedPages'],[]);self.assertEqual(events[0]['pageIndex'],17)
    def test_file_payload_above_128mb_is_not_serialized_as_base64(self):
        # Extra trailing bytes are legal to ignore in a PDF. A sparse file
        # exercises the old transfer limit without allocating a giant string.
        with self.source.open('ab') as stream:stream.truncate(129*1024*1024)
        self.assertEqual(pdf_input(dict(sourceFile=str(self.source))),self.source)
        jobs=Jobs('babeldoc','.',translator_factory=lambda *_:lambda text:'Translated')
        try:
            from babel_adapter import run
            def bounded(pdf,folder,payload,bridge,progress,cancel_event,**kw):
                return run_document(pdf,folder,payload,self.single,bridge,progress,cancel_event,**kw)
            with patch('babel_adapter.run',bounded):
                key=jobs.submit(dict(sourceFile=str(self.source),outputFile=str(self.root/'result.pdf'),pages='1-3',nativeExport=True,documentExport=True))
                jobs.pool.shutdown(wait=True)
                result=jobs.result(key);self.assertNotIn('pdf',result);self.assertEqual(result['sha256'],digest(result['pdfFile']))
                self.assertLess(len(str(result)),2000);self.assertEqual(result['pageCount'],305)
        finally:jobs.pool.shutdown(wait=True)
    def test_file_backed_export_preserves_selected_vector_pages(self):
        (_,output),_,_=self.run_batch()
        for function,expected in [(extract,'native-export-9035'),(comparison,'native-comparison-9035')]:
            result=function(dict(sourceFile=str(self.source),translatedFile=str(output),outputFile=str(self.root/(expected+'.pdf')),first=290,last=304))
            self.assertNotIn('pdf',result);self.assertEqual(result['pipeline'],expected)
            with pymupdf.open(result['pdfFile']) as doc:self.assertEqual(doc.page_count,15);self.assertIn('Translated paragraph',doc[0].get_text())
    def test_small_memory_budget_reduces_native_parts_without_platform_dependencies(self):
        with patch('native_batches.available_memory',return_value=3*1024**3):self.assertEqual(page_limit(1000,{}),4)
        with patch('native_batches.available_memory',return_value=1*1024**3):self.assertEqual(page_limit(1000,{}),1)
        self.assertEqual(page_limit(1000,{'batchPages':2}),2)
        with self.assertRaises(ValueError):page_limit(1000,{'batchPages':True})
    def test_same_stage_progress_updates_are_delivered(self):
        def single(pdf,folder,payload,bridge,progress,*args,**kw):
            for n in range(3):progress(stage='translating',stage_current=n,stage_total=3,page_count=1)
            return [],b'%PDF-fixture'
        jobs=Jobs('babeldoc','.')
        try:
            with patch('babel_adapter.run',single):
                key=jobs.submit(dict(pdf=base64.b64encode(b'%PDF-fixture').decode()));jobs.pool.shutdown(wait=True)
                self.assertEqual(jobs.snapshot(key)['progress']['stage_current'],2)
        finally:jobs.pool.shutdown(wait=True)

if __name__=='__main__':unittest.main()
