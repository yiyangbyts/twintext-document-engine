from unittest.mock import patch
import base64,json,sys,threading,time,unittest,urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).parent))
from babel_adapter import il_regions
from service import Jobs,handler,MAX_ACTIVE_JOBS,MAX_RETAINED_JOBS
class Tests(unittest.TestCase):
    def test_explicit_completion_keeps_names_but_tracks_partial_prose_on_its_actual_page(self):
        jobs=Jobs('babeldoc','.')
        def native(pdf,folder,payload,bridge,progress,cancel_event):
            self.assertEqual(bridge('John Smith and Jane Jones',16,'author'),'John Smith and Jane Jones')
            self.assertEqual(bridge('The treatment improves health.',19,'plain text'),'治疗 improves health。')
            self.assertEqual(bridge.retained_count,1)
            return [],b'%PDF-complete'
        try:
            with patch('babel_adapter.run',native):
                key=jobs.submit({'pdf':base64.b64encode(b'%PDF-fixture').decode(),'nativeExport':True})
                deadline=time.time()+3
                for page,text,retained in [(16,'John Smith and Jane Jones',False),(19,'治疗 improves health。',True)]:
                    while not (pending:=jobs.snapshot(key)['requests']):
                        self.assertLess(time.time(),deadline);time.sleep(.005)
                    self.assertEqual(pending[0]['pageIndex'],page)
                    answer={'id':pending[0]['id'],'translation':text,'retained':retained}
                    jobs.reply(key,answer);jobs.reply(key,answer)
                    while jobs.snapshot(key)['requests'] and jobs.snapshot(key)['requests'][0]['id']==answer['id']:
                        self.assertLess(time.time(),deadline);time.sleep(.005)
                while jobs.snapshot(key)['state'] not in ('complete','error'):
                    self.assertLess(time.time(),deadline);time.sleep(.005)
                state=jobs.snapshot(key);self.assertEqual(state['state'],'complete',state)
                self.assertEqual(state['result']['incompletePages'],[19])
        finally:jobs.pool.shutdown(wait=True)
    def test_lost_submission_response_reuses_the_job_and_rejects_conflicting_input(self):
        jobs=Jobs('babeldoc','model');payload={'pdf':'fixture','nativeExport':True,'clientJobId':'a'*32}
        try:
            with patch.object(jobs.pool,'submit') as submit:
                first=jobs.submit(payload);second=jobs.submit(dict(payload))
                self.assertEqual(first,second);self.assertEqual(submit.call_count,1)
                self.assertEqual(len(jobs.jobs),1)
                with self.assertRaisesRegex(ValueError,'Conflicting submission'):jobs.submit({**payload,'pdf':'different'})
                with self.assertRaisesRegex(ValueError,'Invalid submission token'):jobs.submit({**payload,'clientJobId':'bad'})
        finally:jobs.pool.shutdown()
    def test_native_reply_retry_after_response_loss_does_not_fail_the_job(self):
        jobs=Jobs('babeldoc','.');event=threading.Event()
        try:
            jobs.jobs['task']={'state':'running','requests':{'paragraph':{'event':event}},'created':time.time()}
            answer={'id':'paragraph','translation':'完整译文'}
            jobs.reply('task',answer)
            request=jobs.jobs['task']['requests'].pop('paragraph')
            self.assertEqual(request['translation'],'完整译文')
            # The engine consumed the answer before the HTTP response reached
            # Zotero. Its retry must acknowledge the same answer, not interrupt.
            jobs.reply('task',answer)
            self.assertEqual(jobs.jobs['task']['state'],'running')
            with self.assertRaisesRegex(ValueError,'Conflicting reply'):
                jobs.reply('task',{'id':'paragraph','translation':'不同译文'})
            with self.assertRaises(KeyError):jobs.reply('task',{'id':'unknown','translation':'未知'})
        finally:jobs.pool.shutdown(wait=False,cancel_futures=True)
    def test_native_reply_receipts_are_bounded_and_released_with_the_job(self):
        jobs=Jobs('babeldoc','.')
        try:
            job={'state':'running','requests':{},'created':time.time()};jobs.jobs['task']=job
            for index in range(4200):
                key=str(index);job['requests'][key]={'event':threading.Event()}
                jobs.reply('task',{'id':key,'translation':'译文'})
                job['requests'].pop(key)
            self.assertLessEqual(len(job['replyReceipts']),4096)
            jobs.reply('task',{'id':'4199','translation':'译文'})
            job['state']='complete';jobs.release('task');self.assertNotIn('task',jobs.jobs)
        finally:jobs.pool.shutdown(wait=False,cancel_futures=True)
    def test_native_reply_http_retry_acknowledges_the_consumed_translation(self):
        jobs=Jobs('babeldoc','.');jobs.jobs['task']={'state':'running','cancelled':False,'requests':{'paragraph':{'event':threading.Event()}},'created':time.time()}
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(jobs,{'id':'fixture','port':0}))
        server.RequestHandlerClass=handler(jobs,{'id':'fixture','port':server.server_port})
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            root='http://127.0.0.1:'+str(server.server_port)
            def reply(text):
                request=urllib.request.Request(root+'/v1/jobs/task/reply',data=json.dumps({'id':'paragraph','translation':text}).encode(),headers={'Content-Type':'application/json'})
                return json.load(urllib.request.urlopen(request))
            self.assertEqual(reply('完整译文'),{'ok':True})
            jobs.jobs['task']['requests'].pop('paragraph')
            self.assertEqual(reply('完整译文'),{'ok':True})
            with self.assertRaises(urllib.error.HTTPError) as failure:reply('不同译文')
            self.assertEqual(failure.exception.code,400)
            self.assertTrue(json.load(urllib.request.urlopen(root+'/health'))['ready'])
        finally:server.shutdown();server.server_close();jobs.pool.shutdown(wait=True)
    def test_completed_pages_never_exhaust_the_active_queue(self):
        jobs=Jobs('babeldoc','.');jobs.pool.shutdown(wait=True)
        class Immediate:
            def submit(self,run,job,payload):
                job['state']='complete';job['result']={'regions':[]}
        jobs.pool=Immediate()
        for page in range(128):
            key=jobs.submit({'pageIndex':page})
            self.assertEqual(jobs.snapshot(key)['state'],'complete')
            self.assertLessEqual(len(jobs.jobs),MAX_RETAINED_JOBS)
        self.assertEqual(len(jobs.jobs),MAX_RETAINED_JOBS)
    def test_active_queue_remains_bounded_and_cancellation_releases_a_slot(self):
        jobs=Jobs('babeldoc','.');jobs.pool.shutdown(wait=True)
        class Waiting:
            def submit(self,*args):pass
        jobs.pool=Waiting()
        keys=[jobs.submit({}) for _ in range(MAX_ACTIVE_JOBS)]
        with self.assertRaisesRegex(ValueError,'Too many outstanding jobs'):jobs.submit({})
        jobs.cancel(keys[0]);self.assertIsInstance(jobs.submit({}),str)
    def test_completed_errors_and_old_response_history_do_not_block_new_pages(self):
        jobs=Jobs('babeldoc','.');jobs.pool.shutdown(wait=True)
        class Immediate:
            def submit(self,run,job,payload):job['state']='error';job['error']='fixture parse failure'
        jobs.pool=Immediate()
        for page in range(80):
            key=jobs.submit({});self.assertEqual(jobs.snapshot(key)['state'],'error')
        self.assertLessEqual(len(jobs.jobs),MAX_RETAINED_JOBS)
    def test_http_jobs_accept_more_than_sixteen_completed_pages(self):
        class Completed(Jobs):
            def run(self,job,payload):job['result']={'regions':[]};job['state']='complete'
        jobs=Completed('babeldoc','.')
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(jobs,{'id':'fixture','port':0}))
        server.RequestHandlerClass=handler(jobs,{'id':'fixture','port':server.server_port})
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            root='http://127.0.0.1:'+str(server.server_port)
            for page in range(32):
                req=urllib.request.Request(root+'/v1/jobs',data=json.dumps({'pageIndex':page}).encode(),headers={'Content-Type':'application/json'})
                key=json.load(urllib.request.urlopen(req))['id'];deadline=time.time()+3
                while True:
                    state=json.load(urllib.request.urlopen(root+'/v1/jobs/'+key))
                    if state['state']=='complete':break
                    self.assertLess(time.time(),deadline);time.sleep(.01)
            self.assertTrue(json.load(urllib.request.urlopen(root+'/health'))['ready'])
        finally:server.shutdown();server.server_close();jobs.pool.shutdown(wait=True)
    def test_native_bridge_cancels_while_waiting_for_model(self):
        jobs=Jobs('babeldoc','.')
        def waiting(pdf,folder,payload,bridge,progress,cancel_event):
            progress(type='progress_update',stage='Translate Paragraphs',overall_progress=25)
            bridge('We consider <b0> in this limit.')
            raise AssertionError('Cancelled bridge must not complete')
        with patch('babel_adapter.run',waiting):
            key=jobs.submit({'pdf':base64.b64encode(b'%PDF-fixture').decode(),'nativeExport':True})
            deadline=time.time()+3
            while not jobs.snapshot(key)['requests']:
                self.assertLess(time.time(),deadline);time.sleep(.01)
            self.assertEqual(jobs.snapshot(key)['progress']['stage'],'Translate Paragraphs')
            self.assertEqual(jobs.snapshot(key)['requests'][0]['text'],'We consider <b0> in this limit.')
            jobs.cancel(key)
            while jobs.snapshot(key)['state']!='error':
                self.assertLess(time.time(),deadline);time.sleep(.01)
            self.assertIn('cancelled',jobs.snapshot(key)['error'])
        jobs.pool.shutdown(wait=True)
    def test_bridge_rejects_structure_callbacks_instead_of_requiring_a_client_parser(self):
        jobs=Jobs('babeldoc','.')
        def native(pdf,folder,payload,bridge,progress,cancel_event):
            bridge({'operation':'reference-analysis'})
        try:
            with patch('babel_adapter.run',native):
                key=jobs.submit({'pdf':base64.b64encode(b'%PDF-fixture').decode(),'nativeExport':True})
                deadline=time.time()+3
                while jobs.snapshot(key)['state'] not in ('complete','error'):
                    self.assertLess(time.time(),deadline);time.sleep(.01)
                result=jobs.snapshot(key)
                self.assertEqual(result['state'],'error');self.assertIn('text only',result['error'])
                self.assertEqual(result['requests'],[])
        finally:jobs.pool.shutdown(wait=True)
    def test_generic_server_translates_without_any_client_replies(self):
        jobs=Jobs('babeldoc','.',translator_factory=lambda payload,cancel:lambda text:'译文')
        def native(pdf,folder,payload,bridge,progress,cancel_event):
            self.assertEqual(bridge('Introduction'),'译文')
            return [],b'%PDF-complete'
        try:
            with patch('babel_adapter.run',native):
                key=jobs.submit({'pdf':base64.b64encode(b'%PDF-fixture').decode(),'nativeExport':True})
                deadline=time.time()+3
                while jobs.snapshot(key)['state'] not in ('complete','error'):
                    self.assertLess(time.time(),deadline);time.sleep(.01)
                self.assertEqual(jobs.snapshot(key)['state'],'complete')
                self.assertEqual(jobs.snapshot(key)['requests'],[])
        finally:jobs.pool.shutdown(wait=True)
    def test_babel_il(self):
        document={'page':[{'mediabox':{'box':{'x':0,'y':0,'x2':100,'y2':200}},'pdfParagraph':[{'box':{'x':10,'y':100,'x2':90,'y2':150},'unicode':'source','pdfParagraphComposition':[{'pdfFormula':{'box':{'x':20,'y':120,'x2':40,'y2':130},'pdfCharacter':[{'charUnicode':'x'},{'charUnicode':'='}]}}]}]}]}
        regions=il_regions(document);self.assertEqual(regions[1]['latex'],'x=');self.assertEqual(regions[0]['rect'],[.1,.25,.8,.25])
if __name__=='__main__':unittest.main()
