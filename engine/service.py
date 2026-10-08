"""Loopback job service; slow inference never blocks health or cancellation."""
from __future__ import annotations
import argparse,base64,concurrent.futures,errno,hashlib,json,os,re,secrets,tempfile,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
MAX_BYTES=192*1024*1024
MAX_ACTIVE_JOBS=16
MAX_RETAINED_JOBS=64

def pdf_input(payload,field='pdf'):
    file_key='sourceFile' if field=='pdf' else 'translatedFile'
    if file_key in payload:
        value=payload[file_key]
        if not isinstance(value,str) or not value or '\x00' in value:raise ValueError('Invalid PDF file path')
        path=Path(value)
        if not path.is_file():raise FileNotFoundError('PDF file unavailable')
        with path.open('rb') as stream:
            if b'%PDF' not in stream.read(1024):raise ValueError('Expected a PDF file')
        return path
    data=base64.b64decode(payload[field],validate=True)
    if not data.startswith(b'%PDF'):raise ValueError('Expected a PDF')
    return data

def failure_code(error,stage):
    # Page isolation cannot repair missing dependencies, exhausted memory/disk
    # or worker timeouts. Repeating the full pipeline per page makes those worse.
    chain=[];seen=set();current=error
    while current is not None and id(current) not in seen:
        seen.add(id(current));chain.append(current);current=current.__cause__ or current.__context__
    if any(isinstance(e,MemoryError) or isinstance(e,OSError) and e.errno in (errno.ENOMEM,errno.ENOSPC,errno.EDQUOT) for e in chain):return 'document_resource_failed'
    if any(isinstance(e,(ImportError,FileNotFoundError,PermissionError)) or isinstance(e,OSError) and (e.errno in (errno.EACCES,errno.EPERM,errno.EROFS) or getattr(e,'winerror',None) in (5,32,33)) for e in chain):return 'document_environment_failed'
    if any(isinstance(e,TimeoutError) for e in chain):return 'document_engine_timeout'
    # Known document-content exceptions can be narrowed to individual pages.
    if any(isinstance(e,(RecursionError,ValueError,IndexError,KeyError,AssertionError)) or type(e).__name__ in ('FzErrorFormat','FzErrorSyntax') for e in chain):return 'document_page_failed'
    return 'document_engine_failed'

class Jobs:
    def __init__(self,key,model,translator_factory=None):
        if key!='babeldoc':raise ValueError('Unsupported document engine')
        self.key=key;self.model=model;self.jobs={};self.lock=threading.RLock();self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=1);self.adapter=None;self.artifacts=None;self.translator_factory=translator_factory
    def assemble(self,payload):
        import pymupdf
        pdf=pdf_input(payload)
        parts=payload.get('parts')
        if not isinstance(parts,list) or not parts or len(parts)>10000:raise ValueError('Invalid page recovery parts')
        with (pymupdf.open(pdf) if isinstance(pdf,Path) else pymupdf.open(stream=pdf,filetype='pdf')) as document:
            count=document.page_count;seen=set();toc=document.get_toc(simple=False)
            for part in parts:
                index=part.get('pageIndex')
                if not isinstance(index,int) or isinstance(index,bool) or not 0<=index<count or index in seen:raise ValueError('Invalid recovery page index')
                seen.add(index)
                data=base64.b64decode(part['pdf'],validate=True)
                with pymupdf.open(stream=data,filetype='pdf') as translated:
                    if translated.page_count!=1:raise ValueError('Expected one translated page')
                    # Only successful pages are replaced. Failed/unselected source
                    # pages retain their original position, content and annotations.
                    document.delete_page(index);document.insert_pdf(translated,start_at=index)
            if toc:document.set_toc(toc)
            output=document.tobytes(garbage=3,deflate=True)
        return {'pdf':base64.b64encode(output).decode(),'pageCount':count,'engine':'babeldoc','pipeline':'native-pdf-9020','recoveredPages':sorted(seen)}
    def health(self):
        with self.lock:
            active=[j for j in self.jobs.values() if j['state'] in ('queued','running') and not j['cancelled']]
            return {'busy':bool(active),'activeJobs':len(active),'lastActivity':max((j.get('lastActivity',j['created']) for j in active),default=None)}
    def load(self):
        from babel_runtime import layout_model
        self.layout=layout_model()
    def submit(self,payload):
        if not isinstance(payload,dict):raise ValueError('Expected a JSON object')
        if any(name in payload for name in ('liveParse','officialParse','documentId','png')):raise ValueError('Unsupported legacy parser operation')
        client_id=payload.get('clientJobId');fingerprint=None
        if client_id is not None:
            if self.key!='babeldoc' or not isinstance(client_id,str) or not re.fullmatch(r'[a-f0-9]{32}',client_id):raise ValueError('Invalid submission token')
            digest=hashlib.sha256()
            for part in json.JSONEncoder(sort_keys=True,separators=(',',':')).iterencode(payload):
                for offset in range(0,len(part),65536):digest.update(part[offset:offset+65536].encode())
            fingerprint=digest.hexdigest()
        with self.lock:
            if client_id:
                for existing in self.jobs.values():
                    if existing.get('clientJobId')==client_id:
                        if existing.get('submissionHash')!=fingerprint:raise ValueError('Conflicting submission')
                        return existing['id']
            # Expire jobs and sensitive source data; bound queued work.
            for key in list(self.jobs):
                if self.jobs[key]['state'] not in ('queued','running') and time.time()-self.jobs[key]['created']>3600:del self.jobs[key]
            # Completed pages are response history, not outstanding work. A
            # long paper must not exhaust the queue after its sixteenth page.
            active=[job for job in self.jobs.values() if job['state'] in ('queued','running') and not job['cancelled']]
            if len(active)>=MAX_ACTIVE_JOBS:raise ValueError('Too many outstanding jobs')
            while len(self.jobs)>=MAX_RETAINED_JOBS:
                finished=[(key,job) for key,job in self.jobs.items() if job['state'] not in ('queued','running') or job['cancelled']]
                if not finished:break
                oldest=min(finished,key=lambda item:(not item[1].get('delivered',False),item[1]['created']))[0]
                del self.jobs[oldest]
            key=secrets.token_hex(16);job={'id':key,'state':'queued','created':time.time(),'requests':{},'cancelled':False,'cancel_event':threading.Event()};self.jobs[key]=job
            if client_id:job.update(clientJobId=client_id,submissionHash=fingerprint)
        self.pool.submit(self.run,job,payload);return key
    def run(self,job,payload):
        try:
            job['state']='running';job['startedMonotonic']=time.monotonic();job['stageStartedMonotonic']=job['startedMonotonic'];job['stageTimings']={}
            if job['cancelled']:raise RuntimeError('Cancelled')
            if self.key=='babeldoc' and payload.get('reflowNative'):
                from native_artifacts import reflow
                if not self.artifacts:raise ValueError('native_artifact_expired')
                artifact=self.artifacts.get(payload.get('artifactId'))
                with tempfile.TemporaryDirectory(prefix='twintext-reflow-') as temp:
                    index=payload.get('currentPage')
                    try:
                        if isinstance(index,int) and not isinstance(index,bool) and any(p.page_number==index for p in artifact['document'].page):
                            import copy,pymupdf
                            part={**artifact,'document':copy.copy(artifact['document']),'pages':str(index+1)}
                            part['document'].page=[copy.deepcopy(p) for p in artifact['document'].page if p.page_number==index]
                            first=reflow(part,Path(temp)/'current',payload.get('documentOptions'),job['cancel_event'])
                            with pymupdf.open(stream=base64.b64decode(first['pdf']),filetype='pdf') as full,pymupdf.open() as one:
                                one.insert_pdf(full,from_page=index,to_page=index)
                                preview={'type':'native-page-preview','profile':'native-document-9029-r1','pageIndex':index,'revision':1,'cursor':1,'pdf':base64.b64encode(one.tobytes()).decode()}
                            with self.lock:job['previewCursor']=1;job['previews']={index:preview}
                    except Exception:
                        if job['cancelled']:raise
                        # The full reflow remains authoritative if a fast visible-page preview fails.
                        pass
                    result=reflow(artifact,Path(temp)/'full',payload.get('documentOptions'),job['cancel_event'])
                result['artifactId']=payload['artifactId']
            elif self.key=='babeldoc' and payload.get('extractNative'):
                from native_artifacts import extract
                result=extract(payload)
            elif self.key=='babeldoc' and payload.get('comparisonNative'):
                from native_artifacts import comparison
                result=comparison(payload)
            elif self.key=='babeldoc' and payload.get('assembleNative'):
                result=self.assemble(payload)
            elif self.key=='babeldoc':
                from babel_adapter import run
                pdf=pdf_input(payload)
                translator=self.translator_factory(payload,job['cancel_event']) if self.translator_factory else None
                def bridge(text):
                    if not isinstance(text,str):raise ValueError('Translation bridge accepts text only')
                    if translator:
                        try:
                            translated=translator(text)
                            if translated==text and len(re.findall(r'[A-Za-z]',text))>=12:bridge.retained_count+=1
                            return translated
                        except Exception:
                            if not job['cancelled']:job['bridgeFailure']=True
                            raise
                    request_id=secrets.token_hex(8);event=threading.Event();request={'id':request_id,'event':event,'startedMonotonic':time.monotonic(),'text':text}
                    with self.lock:job['requests'][request_id]=request;job['lastActivity']=time.time()
                    while not event.wait(.25):
                        if job['cancelled']:raise RuntimeError('Translation bridge cancelled')
                    with self.lock:job['requests'].pop(request_id,None)
                    if request.get('error'):
                        job['bridgeFailure']=True;raise RuntimeError(request['error'])
                    translated=request['translation']
                    if translated==text and len(re.findall(r'[A-Za-z]',text))>=12:bridge.retained_count+=1
                    return translated
                bridge.retained_count=0
                def progress(**event):
                    with self.lock:
                        now=time.monotonic();old=job.get('progress',{}).get('stage');new=event.get('stage')
                        if new and new!=old:
                            if old:job['stageTimings'][old]=job['stageTimings'].get(old,0)+round((now-job['stageStartedMonotonic'])*1000)
                            job['stageStartedMonotonic']=now
                        job['lastActivity']=time.time();job['progress']={k:v for k,v in event.items() if k in ('type','stage','overall_progress','stage_current','stage_total','page_count','completed_pages','total_pages','batch_first','batch_last')}
                def preview(event):
                    with self.lock:
                        if job['cancelled']:return
                        if event['type']=='preview-status':
                            job['previewHealth']={k:v for k,v in event.items() if k!='type'}
                            return
                        if event['type']=='preview-warning':
                            warnings=job.setdefault('previewWarnings',[])
                            if len(warnings)<64:warnings.append({k:event[k] for k in ('pageIndex','message','operation','errorType','recursionLimit','pythonVersion','stack') if k in event})
                            return
                        job['previewCursor']=job.get('previewCursor',0)+1
                        event={**event,'cursor':job['previewCursor']}
                        # Retain the first partial frame even when the next
                        # paragraphs finish between two client polls.
                        job.setdefault('firstPreviews',{}).setdefault(event['pageIndex'],event)
                        previews=job.setdefault('previews',{})
                        previews[event['pageIndex']]=event
                        while len(previews)>3:
                            old=next(iter(previews));previews.pop(old);job['firstPreviews'].pop(old,None)
                def control(stream):
                    with self.lock:
                        job['previewControl']=stream
                        stream.set_current_page(job.get('viewPage',int(payload.get('currentPage',0))))
                from temporary_workspace import temporary_workspace
                with temporary_workspace(prefix='twintext-babel-') as temp:
                    args=(pdf,Path(temp),payload,bridge if payload.get('nativeExport') else None,progress,job['cancel_event'])
                    collector={} if payload.get('documentExport') else None
                    regions,pdf_result=run(*args,**({'on_preview':preview,'on_control':control,'collector':collector} if payload.get('documentExport') else {}))
                    if collector and 'document' in collector and not payload.get('pageIsolation'):
                        try:
                            from native_artifacts import ArtifactStore,text_pages
                            if self.artifacts is None:self.artifacts=ArtifactStore()
                            job['artifactId']=self.artifacts.put(collector)
                            job['exportPages']=text_pages(collector)
                        except Exception as error:
                            if job['cancelled']:raise
                            from document_preview import preview_failure
                            job.setdefault('exportWarnings',[]).append(preview_failure(error,'export-text',payload.get('currentPage',0)))
                    if collector and collector.get('batched'):
                        job['exportPages']=collector.get('exportPages',[]);job['failedPages']=collector.get('failedPages',[])
                    result={'regions':regions}
                if pdf_result:
                    if isinstance(pdf_result,Path):
                        from native_batches import digest
                        result.update(pdfFile=str(pdf_result),size=pdf_result.stat().st_size,sha256=digest(pdf_result))
                    else:result['pdf']=base64.b64encode(pdf_result).decode()
                    result['failedPages']=job.pop('failedPages',[])
                    result['pageCount']=job.get('progress',{}).get('page_count')
                    result['engine']='babeldoc';result['pipeline']='native-pdf-9020'
                    if payload.get('documentExport'):
                        result['profile']='native-document-9029-r1';result['previewWarnings']=job.get('previewWarnings',[])
                        result['exportPages']=job.pop('exportPages',[]);result['artifactId']=job.pop('artifactId',None);result['exportWarnings']=job.pop('exportWarnings',[])
            if job['cancelled']:raise RuntimeError('Cancelled')
            if job.get('bridgeFailure'):raise RuntimeError('Translation provider failed')
            job['result']=result;job['state']='complete'
        except Exception as error:
            job['state']='error';job['error']=str(error)[:1200]
            if job.get('bridgeFailure') and not job['cancelled']:job['errorCode']='document_translation_failed'
            if self.key=='babeldoc' and payload.get('documentExport'):
                from document_preview import preview_failure
                job['errorDetails']={**preview_failure(error,'document-pipeline',payload.get('currentPage',0)),
                    'stage':job.get('progress',{}).get('stage'), 'pages':payload.get('pages')}
            if self.key=='babeldoc' and payload.get('documentExport') and not job.get('bridgeFailure') and not job['cancelled']:
                job['errorCode']=failure_code(error,job.get('progress',{}).get('stage'))
                job['errorDetails']['category']=job['errorCode']
        finally:
            with self.lock:job.pop('previewControl',None);job['finishedMonotonic']=time.monotonic()
    def snapshot(self,key,after=0,metadata=False):
        with self.lock:
            job=self.jobs[key]
            if job['state'] in ('complete','error'):job['delivered']=True
            now=job.get('finishedMonotonic',time.monotonic());start=job.get('startedMonotonic',now)
            pending=[r for r in job['requests'].values() if not r['event'].is_set()]
            timing={'elapsedMs':round((now-start)*1000),'stageElapsedMs':round((now-job.get('stageStartedMonotonic',now))*1000),'stageTimings':job.get('stageTimings',{}).copy(),
                    'pendingReplies':len(pending),'oldestReplyMs':round(max((now-r.get('startedMonotonic',now) for r in pending),default=0)*1000)}
            fields=('id','state','error','errorCode','errorDetails','progress','previewHealth','previewWarnings')+(('result',) if not metadata else ())
            return {k:job[k] for k in fields if k in job}|{'timing':timing,'requests':[{k:v for k,v in r.items() if k not in ('event','translation','error','startedMonotonic')} for r in pending]}|({'resultReady':True} if metadata and job['state']=='complete' else {})|(
                {'previews':sorted({v['cursor']:v for v in [*job.get('firstPreviews',{}).values(),*job.get('previews',{}).values()] if v['cursor']>after}.values(),key=lambda v:v['cursor']),
                 'previewCursor':job.get('previewCursor',0)} if 'previewCursor' in job and (not metadata or job['state']!='complete') else {})
    def result(self,key):
        with self.lock:
            job=self.jobs[key]
            if job['state']!='complete':raise KeyError('Result not ready')
            return job['result']
    def reply(self,key,payload):
        with self.lock:
            job=self.jobs[key];request_id=payload['id']
            result=payload.get('translation','');error=str(payload.get('error',''))
            fingerprint=hashlib.sha256(json.dumps([result,error],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
            receipts=job.setdefault('replyReceipts',{})
            # The HTTP response can be lost after the engine consumes its
            # answer. A matching retry is successful; conflicting or unknown
            # replies still fail and cannot replace a completed translation.
            if request_id in receipts:
                if receipts[request_id]!=fingerprint:raise ValueError('Conflicting reply')
                return
            req=job['requests'][request_id]
            if req['event'].is_set():raise ValueError('Already answered')
            if not isinstance(result,str):raise ValueError('Invalid translation reply')
            req['translation']=result;req['error']=error
            receipts[request_id]=fingerprint
            while len(receipts)>4096:receipts.pop(next(iter(receipts)))
            req['event'].set()
    def release(self,key):
        with self.lock:
            if self.jobs[key]["state"] not in ("complete","error"):raise ValueError("Job is still active")
            del self.jobs[key]
    def view(self,key,payload):
        index=payload.get("pageIndex")
        if not isinstance(index,int) or isinstance(index,bool) or not 0<=index<100000:raise ValueError("Invalid view page")
        with self.lock:
            job=self.jobs[key];job["viewPage"]=index
            if job.get("previewControl"):job["previewControl"].set_current_page(index)
    def format(self,key,payload):
        with self.lock:
            job=self.jobs[key]
            if job.get('previewControl'):job['previewControl'].set_options(payload.get('documentOptions',{}))
    def cancel(self,key):
        with self.lock:
            job=self.jobs[key];job['cancelled']=True;job['cancel_event'].set()

def handler(jobs,config):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,value):
            data=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def allowed(self):
            host=self.headers.get('Host','');origin=self.headers.get('Origin','')
            return host=='127.0.0.1:'+str(config['port']) and (not origin or origin in ('chrome://zotero','chrome://zotero/'))
        def do_GET(self):
            if not self.allowed():return self.send(403,{'error':'Origin not allowed'})
            try:
                if self.path=='/v1/source':
                    source=Path(__file__).with_name('engine-source.zip')
                    if source.is_file():
                        data=source.read_bytes();self.send_response(200);self.send_header('Content-Type','application/zip');self.send_header('Content-Disposition','attachment; filename="engine-source.zip"');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
                    manifest=Path(__file__).with_name('source-distribution.json')
                    if not manifest.is_file():return self.send(404,{'error':'See the versioned source releases at https://github.com/yiyangbyts/twintext-document-engine/releases'})
                    delivery=json.loads(manifest.read_text())
                    version=delivery.get('version','');repository='https://github.com/yiyangbyts/twintext-document-engine'
                    expected=f'{repository}/releases/download/v{version}/twintext-engine-source-{version}.zip'
                    if delivery.get('schema')!=1 or delivery.get('repository')!=repository or not isinstance(version,str) or not re.fullmatch(r'\d+\.\d+\.\d+',version) or delivery.get('archive')!=expected:
                        return self.send(503,{'error':'Invalid source delivery metadata'})
                    self.send_response(302);self.send_header('Location',expected);self.send_header('Cache-Control','no-store');self.send_header('Content-Length','0');self.end_headers();return
                if self.path=='/health':return self.send(200,{**jobs.health(),'ready':True,'protocol':5,'engine':config['id'],'backend':jobs.key,'capabilities':['native-pdf-9020','cancellable-bridge','native-paragraph-preview-9031','engine-structure-2.0.5-v1','native-reflow-export-9035','bounded-native-files-2.0.9']})
                location=urlsplit(self.path)
                if re.fullmatch(r'/v1/jobs/[^/]+(?:/result)?',location.path):
                    parts=location.path.split('/');query=parse_qs(location.query)
                    if len(parts)==5 and parts[4]=='result':return self.send(200,jobs.result(parts[3]))
                    after=max(0,int(query.get('after',['0'])[0]))
                    return self.send(200,jobs.snapshot(location.path.rsplit('/',1)[-1],after,query.get('metadata')==['1']))
                self.send(404,{'error':'Unknown route'})
            except KeyError:self.send(404,{'error':'Job expired'})
            except (ValueError,TypeError):self.send(400,{'error':'Invalid query parameters'})
        def do_POST(self):
            if not self.allowed() or not self.headers.get('Content-Type','').startswith('application/json'):return self.send(403,{'error':'JSON loopback requests only'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if size<2 or size>MAX_BYTES:raise ValueError('Invalid payload size')
                payload=json.loads(self.rfile.read(size))
                if not isinstance(payload,dict):raise ValueError('Expected a JSON object')
                if self.path=='/v1/jobs':return self.send(202,{'id':jobs.submit(payload)})
                parts=self.path.split('/')
                if len(parts)==5 and parts[1:3]==['v1','jobs']:
                    if parts[4]=='reply':jobs.reply(parts[3],payload)
                    elif parts[4]=='cancel':jobs.cancel(parts[3])
                    elif parts[4]=='view':jobs.view(parts[3],payload)
                    elif parts[4]=='format':jobs.format(parts[3],payload)
                    elif parts[4]=='release':jobs.release(parts[3])
                    else:raise ValueError('Unknown operation')
                    return self.send(200,{'ok':True})
                self.send(404,{'error':'Unknown route'})
            except (ValueError,KeyError,TypeError) as error:self.send(400,{'error':str(error)[:200]})
    return Handler

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model',required=True);parser.add_argument('--port',type=int);args=parser.parse_args()
    config=json.loads(Path(__file__).with_name('backend.json').read_text())
    if config['key']!='babeldoc':raise ValueError('Unsupported document engine')
    from asset_paths import configure
    configure(args.model)
    if args.port is not None:
        if not 1024<args.port<65536:raise ValueError('Invalid service port')
        config['port']=args.port
    jobs=Jobs(config['key'],args.model);jobs.load()
    server=ThreadingHTTPServer(('127.0.0.1',config['port']),handler(jobs,config))
    try:server.serve_forever()
    finally:server.server_close();jobs.pool.shutdown(wait=False,cancel_futures=True)
if __name__=='__main__':main()
