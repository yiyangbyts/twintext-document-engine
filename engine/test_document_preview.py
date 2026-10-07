from copy import deepcopy
from types import SimpleNamespace
import base64,io,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from document_preview import PreviewStream,read_frame,write_frame,preview_failure
from service import Jobs

class PreviewTests(unittest.TestCase):
    def test_global_failures_are_not_retried_as_broken_pages(self):
        import errno
        from service import failure_code
        for error,code in [(MemoryError(),'document_resource_failed'),(OSError(errno.ENOSPC,'disk full'),'document_resource_failed'),
                           (PermissionError('file occupied'),'document_environment_failed'),(ModuleNotFoundError('dependency absent'),'document_environment_failed'),
                           (TimeoutError('worker blocked'),'document_engine_timeout'),(RuntimeError('worker exited'),'document_engine_failed'),
                           (RecursionError('bad page'),'document_page_failed')]:
            self.assertEqual(failure_code(error,'Save PDF'),code)
        try:
            try:raise MemoryError()
            except MemoryError as cause:raise RuntimeError('wrapped failure') from cause
        except RuntimeError as error:self.assertEqual(failure_code(error,'Typesetting'),'document_resource_failed')
    def test_optional_export_failure_preserves_the_completed_pdf(self):
        def translate(*args,**kwargs):
            kwargs['collector'].update(document=object())
            args[4](type='validated',page_count=1)
            return [],b'%PDF-valid'
        jobs=Jobs('babeldoc','model');job={'id':'optional','state':'queued','created':0,'requests':{},'cancelled':False,'cancel_event':threading.Event()};jobs.jobs['optional']=job
        try:
            with patch('babel_adapter.run',side_effect=translate),patch('native_artifacts.text_pages',side_effect=ValueError('bad optional structure')):
                jobs.run(job,{'pdf':base64.b64encode(b'%PDF-source').decode(),'documentExport':True,'nativeExport':True})
            snapshot=jobs.snapshot('optional');self.assertEqual(snapshot['state'],'complete')
            self.assertEqual(base64.b64decode(snapshot['result']['pdf']),b'%PDF-valid');self.assertEqual(snapshot['result']['exportWarnings'][0]['operation'],'export-text')
        finally:jobs.pool.shutdown()
    def test_small_snapshot_and_separate_result_do_not_resend_the_final_pdf(self):
        jobs=Jobs('babeldoc','model')
        jobs.jobs['large']={'id':'large','state':'complete','created':0,'requests':{},'result':{'pdf':'x'*2_000_000},'previewCursor':1,'previews':{0:{'cursor':1,'pdf':'y'*1_000_000}}}
        try:
            snapshot=jobs.snapshot('large',metadata=True)
            self.assertTrue(snapshot['resultReady']);self.assertNotIn('result',snapshot);self.assertNotIn('previews',snapshot)
            self.assertLess(len(str(snapshot)),1000);self.assertEqual(len(jobs.result('large')['pdf']),2_000_000)
            self.assertEqual(jobs.snapshot('large')['result'],jobs.result('large'))
        finally:jobs.pool.shutdown()
    def test_engine_timing_retains_stage_and_pending_reply_age_without_text(self):
        jobs=Jobs('babeldoc','model');now=time.monotonic()
        jobs.jobs['timed']={'state':'running','created':time.time(),'startedMonotonic':now-90,'stageStartedMonotonic':now-30,'stageTimings':{'Parse PDF':20000},
                           'requests':{'pending':{'event':threading.Event(),'text':'private source','startedMonotonic':now-45}}}
        try:
            snapshot=jobs.snapshot('timed',metadata=True);timing=snapshot['timing']
            self.assertGreaterEqual(timing['elapsedMs'],90000);self.assertEqual(timing['pendingReplies'],1);self.assertGreaterEqual(timing['oldestReplyMs'],45000)
            self.assertNotIn('private',str(timing));self.assertNotIn('startedMonotonic',snapshot['requests'][0])
        finally:jobs.pool.shutdown()
    def test_windows_frame_acknowledgement_retries_sharing_violation_only(self):
        from document_preview import file_operation
        error=PermissionError('frame temporarily occupied');error.winerror=32
        with patch('document_preview.time.sleep') as sleep:
            operation=unittest.mock.Mock(side_effect=[error,error,'acknowledged'])
            self.assertEqual(file_operation(operation),'acknowledged')
            self.assertEqual(operation.call_count,3);self.assertEqual(sleep.call_count,2)
            with self.assertRaises(FileNotFoundError):file_operation(lambda:(_ for _ in ()).throw(FileNotFoundError()))
    def test_recursion_diagnostic_retains_origin_without_document_content(self):
        def recurse(depth,private_document_text):
            if depth==0:raise RecursionError('maximum recursion depth exceeded')
            return recurse(depth-1,private_document_text)
        try:recurse(70,'private source text')
        except RecursionError as error:event=preview_failure(error,'prepare-document',4)
        self.assertEqual(event['operation'],'prepare-document')
        self.assertEqual(event['errorType'],'RecursionError')
        self.assertEqual(event['pageIndex'],4)
        self.assertEqual(event['recursionLimit'],sys.getrecursionlimit())
        self.assertLessEqual(len(event['stack']),32)
        self.assertEqual(event['stack'][0]['function'],'test_recursion_diagnostic_retains_origin_without_document_content')
        self.assertEqual(event['stack'][-1]['function'],'recurse')
        self.assertNotIn('private source text',str(event))
        pipe=io.BytesIO();write_frame(pipe,event);pipe.seek(0)
        self.assertEqual(read_frame(pipe),event)
    def test_preview_failure_reaches_job_diagnostics_without_stopping_final_output(self):
        try:raise RecursionError('maximum recursion depth exceeded')
        except RecursionError as error:warning=preview_failure(error,'prepare-document',0)
        def translate(*args,**kwargs):
            kwargs['on_preview'](warning)
            args[4](type='validated',page_count=1)
            return [],b'%PDF-final-result'
        jobs=Jobs('babeldoc','model')
        job={'id':'diagnostic','state':'queued','created':0,'requests':{},'cancelled':False,'cancel_event':threading.Event()}
        jobs.jobs[job['id']]=job
        try:
            with patch('babel_adapter.run',side_effect=translate):
                jobs.run(job,{'pdf':base64.b64encode(b'%PDF-source').decode(),'documentExport':True,'nativeExport':True})
            snapshot=jobs.snapshot(job['id'])
            self.assertEqual(snapshot['state'],'complete')
            self.assertEqual(base64.b64decode(snapshot['result']['pdf']),b'%PDF-final-result')
            self.assertEqual(snapshot['previewWarnings'][0]['operation'],'prepare-document')
            self.assertEqual(snapshot['previewWarnings'][0]['stack'],warning['stack'])
        finally:jobs.pool.shutdown()
    def test_final_pdf_failure_retains_stage_and_stack_for_page_recovery(self):
        def translate(*args,**kwargs):
            args[4](stage='Save PDF',stage_current=0,stage_total=2)
            raise RecursionError('maximum recursion depth exceeded')
        jobs=Jobs('babeldoc','model')
        job={'id':'failed','state':'queued','created':0,'requests':{},'cancelled':False,'cancel_event':threading.Event()}
        jobs.jobs[job['id']]=job
        try:
            with patch('babel_adapter.run',side_effect=translate):
                jobs.run(job,{'pdf':base64.b64encode(b'%PDF-source').decode(),'documentExport':True,'nativeExport':True,'pages':'1-8'})
            snapshot=jobs.snapshot(job['id'])
            self.assertEqual(snapshot['state'],'error')
            self.assertEqual(snapshot['errorCode'],'document_page_failed')
            self.assertEqual(snapshot['errorDetails']['stage'],'Save PDF')
            self.assertEqual(snapshot['errorDetails']['pages'],'1-8')
            self.assertEqual(snapshot['errorDetails']['errorType'],'RecursionError')
            self.assertEqual(snapshot['errorDetails']['stack'][-1]['function'],'translate')
        finally:jobs.pool.shutdown()
    def test_binary_transport_handles_large_unicode_packets_and_reports_truncation(self):
        packet={'page':SimpleNamespace(unicode='中文公式 α '+('x'*4_000_000))}
        pipe=io.BytesIO();write_frame(pipe,packet);pipe.seek(0)
        self.assertEqual(read_frame(pipe)['page'].unicode,packet['page'].unicode)
        with self.assertRaises(EOFError):read_frame(io.BytesIO(pipe.getvalue()[:-1]))
        with self.assertRaises(ValueError):read_frame(io.BytesIO(b'\xff'*4))
    def worker_fixture(self,root,mode):
        script=root/'worker.py'
        script.write_text('import sys,time,os\nfrom pathlib import Path\nsys.path.insert(0,'+repr(str(Path(__file__).resolve().parent))+')\nfrom document_preview import read_frame,write_frame,read_file,write_file\n'+
            "folder=Path(sys.argv[1]) if len(sys.argv)>1 else None\ndef send(value):\n if folder:write_file(folder/'result.bin',value)\n else:write_frame(sys.stdout.buffer,value)\ndef receive():\n if not folder:return read_frame(sys.stdin.buffer)\n path=folder/'request.bin'\n while not path.exists():time.sleep(.01)\n value=read_file(path);path.unlink();return value\nopts=read_file(folder/'options.bin') if folder else receive()\nmarker=Path(opts['root'])/'failed-once'\n"+
            ("if not marker.exists():marker.touch();os._exit(7)\n" if mode=='restart' else "os._exit(8)\n" if mode=='fatal' else "if not marker.exists():\n marker.touch();send({'type':'preview-ready'});time.sleep(60)\n" if mode=='blocked' else ''))
        with script.open('a') as file:file.write("time.sleep(.05)\nsend({'type':'preview-ready'})\nwhile True:\n packet=receive()\n if packet is None:break\n send({'type':'native-page-preview','pageIndex':packet['page'].page_number,'revision':packet['revision'],'completedParagraphs':packet['completedParagraphs']})\n")
        real=subprocess.Popen
        def launch(args,**kwargs):return real([args[0],'-u',str(script),*([args[-1]] if '--files' in args else [])],**kwargs)
        config=SimpleNamespace(input_file=root/'source.pdf',lang_in='en',lang_out='zh-CN',get_working_file_path=lambda name:root/name)
        return config,patch('document_preview.subprocess.Popen',side_effect=launch)
    def wait_for(self,condition):
        deadline=time.monotonic()+8
        while not condition() and time.monotonic()<deadline:time.sleep(.02)
        self.assertTrue(condition())
    def test_isolated_worker_restarts_and_replays_completed_copies_without_translation(self):
        with tempfile.TemporaryDirectory(prefix='预览 空格 ') as temp:
            root=Path(temp);config,launch=self.worker_fixture(root,'restart');events=[]
            paragraphs=[SimpleNamespace(unicode='source') for _ in range(200)]
            doc=SimpleNamespace(page=[SimpleNamespace(page_number=0,pdf_paragraph=paragraphs)],total_pages=1)
            stream=PreviewStream(events.append)
            with launch:
                try:
                    stream.prepare(doc,config)
                    for p in paragraphs:p.unicode='translated';stream.completed_paragraph(p)
                    self.wait_for(lambda:any(e['type']=='native-page-preview' and e['completedParagraphs']==200 for e in events))
                    self.assertEqual(stream.restart_count,1)
                    self.assertTrue(all(p.unicode=='translated' for p in paragraphs))
                    self.assertTrue(any(e['type']=='preview-warning' for e in events))
                finally:stream.finish()
            self.assertIsNotNone(stream.process.returncode)
            self.assertFalse(stream.receiver.is_alive());self.assertFalse(stream.pump.is_alive())
    def test_worker_failure_is_bounded_and_available_in_live_job_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config,launch=self.worker_fixture(root,'fatal');events=[];stream=PreviewStream(events.append)
            with launch:
                try:
                    stream.start(config)
                    self.wait_for(lambda:any(e.get('state')=='unavailable' for e in events))
                    self.assertEqual(stream.restart_count,1)
                finally:stream.finish()
            self.assertLess(len([e for e in events if e['type']=='preview-warning']),4)
    def test_a_blocked_large_pipe_write_is_monitored_and_recovered(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config,launch=self.worker_fixture(root,'blocked');events=[];stream=PreviewStream(events.append)
            p=SimpleNamespace(unicode='translated'+'x'*4_000_000)
            with launch:
                try:
                    stream.prepare(SimpleNamespace(page=[SimpleNamespace(page_number=0,pdf_paragraph=[p])],total_pages=1),config)
                    stream.completed_paragraph(p)
                    self.wait_for(lambda:stream.inflight is not None)
                    stream.sent_at=time.monotonic()-121
                    self.wait_for(lambda:any(e['type']=='native-page-preview' for e in events))
                    self.assertEqual(stream.restart_count,1)
                finally:stream.finish()
            self.assertFalse(stream.writer.is_alive())
    def test_worker_preserves_first_partial_then_coalesces_fast_completions(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config,launch=self.worker_fixture(root,'normal');events=[];stream=PreviewStream(events.append)
            ps=[SimpleNamespace(unicode='source') for _ in range(200)]
            with launch:
                try:
                    stream.prepare(SimpleNamespace(page=[SimpleNamespace(page_number=0,pdf_paragraph=ps)],total_pages=1),config)
                    for p in ps:p.unicode='translated';stream.completed_paragraph(p)
                    self.wait_for(lambda:any(e.get('completedParagraphs')==200 for e in events))
                    frames=[e for e in events if e['type']=='native-page-preview']
                    self.assertEqual(frames[0]['completedParagraphs'],1)
                    self.assertLessEqual(len(frames),3)
                finally:stream.finish()
    def test_windows_hidden_host_uses_atomic_files_and_preserves_partial_updates(self):
        with tempfile.TemporaryDirectory(prefix='Windows 中文 空格 ') as temp:
            root=Path(temp);config,launch=self.worker_fixture(root,'normal');events=[];stream=PreviewStream(events.append)
            ps=[SimpleNamespace(unicode='source') for _ in range(200)]
            with launch,patch('document_preview.sys',SimpleNamespace(platform='win32',executable=sys.executable)):
                try:
                    stream.prepare(SimpleNamespace(page=[SimpleNamespace(page_number=0,pdf_paragraph=ps)],total_pages=1),config)
                    for p in ps:p.unicode='中文公式 α';stream.completed_paragraph(p)
                    self.wait_for(lambda:any(e.get('completedParagraphs')==200 for e in events))
                    frames=[e for e in events if e['type']=='native-page-preview']
                    self.assertEqual(frames[0]['completedParagraphs'],1)
                    self.assertEqual(stream.transport,'files');self.assertEqual(stream.restart_count,0)
                    self.assertIsNone(stream.process.stdin);self.assertIsNone(stream.process.stdout)
                    self.assertTrue(any(e.get('transport')=='isolated-files-9040' for e in events))
                finally:stream.finish()
            self.assertFalse(stream.receiver.is_alive());self.assertFalse(stream.writer.is_alive())
    def test_visit_publishes_completed_offscreen_paragraph_without_mutating_source(self):
        original=SimpleNamespace(unicode='source');page=SimpleNamespace(pdf_paragraph=[original],page_number=4)
        stream=PreviewStream(lambda event:None,0)
        stream.pages[4]=deepcopy(page);stream.completed[4]=set();stream.locations[id(original)]=(4,0)
        original.unicode='translated';stream.completed_paragraph(original)
        self.assertFalse(stream.pending)
        stream.set_current_page(4)
        self.assertEqual(stream.first[4]['page'].pdf_paragraph[0].unicode,'translated')
        self.assertEqual(stream.first[4]['completedParagraphs'],1)
        stream.first[4]['page'].pdf_paragraph[0].unicode='preview-layout'
        self.assertEqual(original.unicode,'translated')
        self.assertEqual(stream.pages[4].pdf_paragraph[0].unicode,'translated')
    def test_fast_completions_preserve_first_partial_snapshot(self):
        paragraphs=[SimpleNamespace(unicode='source') for _ in range(3)]
        stream=PreviewStream(lambda event:None,0)
        stream.pages[0]=SimpleNamespace(pdf_paragraph=deepcopy(paragraphs),page_number=0)
        stream.completed[0]=set();stream.locations={id(p):(0,i) for i,p in enumerate(paragraphs)}
        for p in paragraphs:p.unicode='translated';stream.completed_paragraph(p)
        self.assertEqual(stream.first[0]['completedParagraphs'],1)
        self.assertEqual(stream.first[0]['page'].pdf_paragraph[1].unicode,'source')
        self.assertEqual(stream.pending[0]['completedParagraphs'],3)
    def test_reference_baseline_does_not_publish_merged_translation_before_entry_updates(self):
        paragraph=SimpleNamespace(unicode='source references');stream=PreviewStream(lambda event:None,0)
        stream.pages[0]=SimpleNamespace(pdf_paragraph=[deepcopy(paragraph)],page_number=0)
        stream.completed[0]=set();stream.locations[id(paragraph)]=(0,0)
        paragraph.unicode='merged baseline';stream.completed_paragraph(paragraph,preserve_source=True)
        self.assertEqual(stream.first[0]['page'].pdf_paragraph[0].unicode,'source references')
        stream.reference_updated(0,[{'id':'entry-1','translated':True}])
        self.assertEqual(stream.pending[0]['references'][0]['id'],'entry-1')
        self.assertEqual(paragraph.unicode,'merged baseline')
    def test_appearance_reuses_completed_snapshot_without_mutating_glyphs(self):
        paragraph=SimpleNamespace(unicode='translated')
        stream=PreviewStream(lambda event:None,0);stream.pages[0]=SimpleNamespace(page_number=0,pdf_paragraph=[paragraph]);stream.completed[0]={0}
        stream.set_options({'fontFamily':'sans','fontScale':120})
        self.assertEqual(stream.first[0]['documentOptions'],{'fontFamily':'sans','fontScale':120})
        self.assertEqual(paragraph.unicode,'translated')
        stream.set_options({'fontFamily':'serif'})
        self.assertEqual(stream.pending[0]['documentOptions']['fontFamily'],'serif')
    def test_cursor_returns_latest_page_only_and_terminal_release_frees_result(self):
        jobs=Jobs('babeldoc','model')
        try:
            jobs.jobs['test']={'id':'test','state':'complete','created':0,'requests':{},'result':{'pdf':'large'},'previewCursor':3,
                'previews':{0:{'cursor':3,'pageIndex':0},1:{'cursor':2,'pageIndex':1}}}
            self.assertEqual(jobs.snapshot('test',2)['previews'],[{'cursor':3,'pageIndex':0}])
            jobs.jobs['test']['firstPreviews']={0:{'cursor':1,'pageIndex':0,'completedParagraphs':1}}
            self.assertEqual([p['cursor'] for p in jobs.snapshot('test',0)['previews']],[1,2,3])
            jobs.release('test');self.assertNotIn('test',jobs.jobs)
            jobs.jobs['active']={'state':'running'}
            with self.assertRaises(ValueError):jobs.release('active')
        finally:jobs.pool.shutdown(wait=False,cancel_futures=True)
    def test_visit_validation_and_control_are_not_translation_cancellation(self):
        jobs=Jobs('babeldoc','model');visited=[]
        try:
            jobs.jobs['test']={'state':'running','cancelled':False,'previewControl':SimpleNamespace(set_current_page=visited.append)}
            jobs.view('test',{'pageIndex':7});self.assertEqual(visited,[7]);self.assertFalse(jobs.jobs['test']['cancelled'])
            for value in [True,-1,'7',100000]:
                with self.assertRaises(ValueError):jobs.view('test',{'pageIndex':value})
        finally:jobs.pool.shutdown(wait=False,cancel_futures=True)
if __name__=='__main__':unittest.main()
