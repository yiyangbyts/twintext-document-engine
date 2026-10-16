"""Progressive native PDF previews. Upstream document objects remain untouched.

Rendering runs in a separate process: PyMuPDF is never shared by translation
and preview threads. Every snapshot starts from the prepared, original page.
"""
from __future__ import annotations
import base64,copy,pickle,queue,struct,subprocess,sys,threading,time,traceback
from contextlib import contextmanager,redirect_stdout,ExitStack
from pathlib import Path

MAX_PREVIEW_BYTES=8*1024*1024
MAX_PACKET_BYTES=128*1024*1024

def compose_scan_preview(source,translated,index,boxes,crop):
    """Clip native translated paragraphs over the unchanged scanned page.

    Native OCR masks cover all paragraphs, including pending ones. Clip the
    provisional result to changed paragraphs so pending text stays readable.
    This composes PDF drawing commands and rasterizes just once.
    """
    import pymupdf
    page=source[index]
    for box in boxes:
        region=pymupdf.Rect(box.x-crop.x,crop.y2-box.y2,box.x2-crop.x,crop.y2-box.y)&page.rect
        if not region.is_empty:page.show_pdf_page(region,translated,index,clip=region)
    return page

def preview_failure(error,operation,page_index,revision=0):
    """Keep the failing operation and stack without PDF text or frame locals."""
    frames=traceback.extract_tb(error.__traceback__)
    # Keep both the origin and terminal frames for deep recursive failures.
    selected=frames if len(frames)<=32 else frames[:8]+frames[-24:]
    return {'type':'preview-warning','pageIndex':page_index,'revision':revision,
        'message':str(error)[:800],'operation':operation,'errorType':type(error).__name__,
        'recursionLimit':sys.getrecursionlimit(),'pythonVersion':sys.version.split()[0],
        'stack':[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name} for f in selected]}

def read_frame(channel):
    def exact(size):
        data=bytearray()
        while len(data)<size:
            part=channel.read(size-len(data))
            if not part:raise EOFError('Preview worker pipe closed')
            data.extend(part)
        return data
    size=struct.unpack('!I',exact(4))[0]
    if size>MAX_PACKET_BYTES:raise ValueError('Preview packet exceeds size limit')
    # Private anonymous pipes connect only this service to its own worker.
    # Neither HTTP clients nor downloaded files supply pickled data.
    return pickle.loads(exact(size))

def write_frame(channel,value):
    data=pickle.dumps(value,protocol=5)
    if len(data)>MAX_PACKET_BYTES:raise ValueError('Preview packet exceeds size limit')
    channel.write(struct.pack('!I',len(data)));channel.write(data);channel.flush()

def file_operation(action):
    # On Windows, a newly published frame can briefly be held by an indexing
    # or antivirus process. Keep the same frame and retry its acknowledgement;
    # do not abandon the receiver or repeat translation for a sharing violation.
    deadline=time.monotonic()+3
    while True:
        try:return action()
        except OSError as error:
            if getattr(error,'winerror',None) not in (32,33) or time.monotonic()>=deadline:raise
            time.sleep(.03)

def write_file(path,value):
    """Only a complete frame becomes visible to the other local process."""
    temporary=path.with_suffix('.tmp')
    with temporary.open('wb') as file:write_frame(file,value)
    file_operation(lambda:temporary.replace(path))

def read_file(path):
    with path.open('rb') as file:return read_frame(file)

class QuietProgress:
    def __init__(self,cancel):self.cancel_event=cancel
    def raise_if_cancelled(self):
        if self.cancel_event.is_set():raise RuntimeError('Preview cancelled')
    @contextmanager
    def stage_start(self,*args,**kwargs):
        self.raise_if_cancelled();yield self
    def advance(self,*args,**kwargs):self.raise_if_cancelled()

class SnapshotRenderer:
    """Warm fonts once, then rasterize the same upstream PDF drawing commands.

    Font subsetting / saving / reopening a PDF on every paragraph used to cost
    more than translating a page. Only the provisional transport is raster;
    the final PDF still uses the complete, unchanged BabelDOC pipeline.
    """
    def __init__(self,options,cancel):
        from asset_paths import configure
        configure()
        from font_resources import install
        install()
        from ocr_formula import install as install_source_crops
        install_source_crops()
        import pymupdf
        from babeldoc.format.pdf.translation_config import TranslationConfig,WatermarkOutputMode
        from babeldoc.format.pdf.document_il.il_version_1 import Document
        from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
        from babeldoc.format.pdf.document_il.backend.pdf_creater import PDFCreater
        self.options=options;self.pymupdf=pymupdf;self.Document=Document
        root=Path(options['root']);root.mkdir(parents=True,exist_ok=True)
        self.config=TranslationConfig(translator=None,input_file=options['source'],lang_in=options['langIn'],lang_out=options['langOut'],
            doc_layout_model=object(),working_dir=root/'work',output_dir=root/'output',
            no_dual=True,only_include_translated_page=True,skip_clean=True,watermark_output_mode=WatermarkOutputMode.NoWatermark)
        self.config.progress_monitor=QuietProgress(cancel)
        # Scanned pages need the same native background masks as formal export.
        # Repainting OCR glyphs without these masks doubles the source image.
        self.config.ocr_workaround=options.get('ocrWorkaround') is True
        self.config.twintext_scan_pages=set(options.get('scanPages',[]))
        self.config.twintext_preview_source_crops=True
        self.config.twintext_visual_source=options.get('visualSource',options['source'])
        from document_options import make_typesetter,options as reader_options
        self.config.primary_font_family=reader_options(options.get('documentOptions'))['fontFamily']
        self.Typesetting=Typesetting;self.format_options=options.get('documentOptions',{})
        self.typesetter=make_typesetter(Typesetting,self.format_options)(self.config)
        self.creator=PDFCreater(options['prepared'],Document(total_pages=0,page=[]),self.config,{})
        with pymupdf.open(options['source']) as original:
            self.boxes=[{name:original.xref_get_key(page.xref,name) for name in
                ('MediaBox','CropBox','ArtBox','BleedBox','TrimBox','Rotate')} for page in original]
            self.config.twintext_ocr_pages=set(options['ocrPages']) if 'ocrPages' in options else {p.number for p in original if any(f[4]=='TwinTextOCR' for f in p.get_fonts(full=True))}
    def render(self,packet):
        raw=packet.get('documentOptions',self.format_options)
        if raw!=self.format_options:
            from document_options import make_typesetter,options
            self.config.primary_font_family=options(raw)['fontFamily']
            self.typesetter=make_typesetter(self.Typesetting,raw)(self.config);self.format_options=copy.deepcopy(raw)
        page=packet['page'];index=page.page_number;config=self.config;pymupdf=self.pymupdf
        has_source_crops=any(form.form_type=='twintext-source-crop' for p in page.pdf_paragraph
            for comp in p.pdf_paragraph_composition if comp.pdf_formula for form in comp.pdf_formula.pdf_form)
        changed=set(packet.get('changedParagraphs',packet['paragraphs']))
        changed_boxes=[copy.copy(p.box) for i,p in enumerate(page.pdf_paragraph) if i in changed]
        document=self.Document(total_pages=packet['pageCount'],page=[page])
        self.typesetter.typesetting_document(document)
        if packet.get('references'):
            from reference_layout import render_references
            render_references(page,packet['references'],self.typesetter)
        self.creator.docs=document
        with ExitStack() as stack:
            pdf=stack.enter_context(pymupdf.open(self.options['prepared']))
            self.creator.font_mapper.add_font(pdf,document)
            self.creator.update_page_content_stream(False,page,pdf,config)
            for name,(kind,value) in self.boxes[index].items():
                if kind!='null':pdf.xref_set_key(pdf[index].xref,name,value)
            config.raise_if_cancelled()
            rendered=pdf[index]
            if self.options.get('preservedRegions'):
                if index in config.twintext_ocr_pages:
                    from ocr_formula import restore_visual_page
                    with pymupdf.open(config.twintext_visual_source) as source:restore_visual_page(source,rendered,index,self.options['preservedRegions'])
                else:
                    from preserved_regions import restore_page
                    with pymupdf.open(self.options['source']) as source:restore_page(source,rendered,index,self.options['preservedRegions'])
            if config.ocr_workaround or index in config.twintext_scan_pages:
                source=stack.enter_context(pymupdf.open(self.options['source']))
                rendered=compose_scan_preview(source,pdf,index,changed_boxes,(page.cropbox or page.mediabox).box)
            angle=self.options.get('contentRotations',{}).get(index,0)
            if angle:rendered.set_rotation((-angle)%360)
            # Bound raster memory for posters / unusually large PDF pages.
            scale=min(1.5,(12_000_000/max(1,rendered.rect.width*rendered.rect.height))**.5)
            output=rendered.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False).tobytes('png')
            if len(output)>MAX_PREVIEW_BYTES:raise ValueError('Preview exceeds size limit')
            # The pixels already have the original visual orientation. PDF.js
            # still uses the source's intrinsic rotation in its viewport.
            size={'width':rendered.rect.width,'height':rendered.rect.height,
                'rotation':self.options.get('originalRotations',{}).get(index,rendered.rotation)}
        if has_source_crops:
            # Graft maps contain native document cycles. Reclaim closed frame
            # documents before another OCR preview accumulates their resources.
            import gc
            gc.collect()
        return {'type':'native-page-preview','revision':packet['revision'],'pageIndex':index,
            'paragraphs':packet['paragraphs'],'completedParagraphs':packet['completedParagraphs'],
            'totalParagraphs':packet['totalParagraphs'],'png':base64.b64encode(output).decode(),**size,
            'profile':'native-paragraph-9031-r1','provisional':True}

def worker_main(folder=None):
    # Explicit stdio transport also works when Zotero starts Python without a
    # console on Windows. Avoid multiprocessing spawn/main/queue feeder state.
    cancel=threading.Event()
    if folder:
        folder=Path(folder)
        def incoming():
            path=folder/'request.bin'
            while not path.exists():time.sleep(.03)
            value=read_file(path);file_operation(path.unlink);return value
        def outgoing(value):write_file(folder/'result.bin',value)
        options=read_file(folder/'options.bin')
    else:
        incoming=lambda:read_frame(sys.stdin.buffer)
        outgoing=lambda value:write_frame(sys.stdout.buffer,value)
        options=incoming()
    try:
        with redirect_stdout(sys.stderr):renderer=SnapshotRenderer(options,cancel)
        outgoing({'type':'preview-ready'})
        while True:
            packet=incoming()
            if packet is None:return
            try:
                with redirect_stdout(sys.stderr):result=renderer.render(packet)
            except Exception as error:
                result=preview_failure(error,'render-page',packet['page'].page_number,packet['revision'])
            outgoing(result)
    except EOFError:return
    except Exception as error:
        outgoing(preview_failure(error,'worker-initialize-or-receive',options['currentPage']))

class PreviewStream:
    def __init__(self,publish,current_page=0):
        self.publish=publish;self.current_page=current_page;self.lock=threading.RLock()
        self.pages={};self.locations={};self.completed={};self.changed={};self.revision=0;self.references={}
        self.pending={};self.first={};self.seen=set();self.started=False;self.closed=False
        self.worker_stop_lock=threading.RLock()
        self.resources=None;self.snapshot_count=0;self.update_count=0;self.last_sent={};self.interval=.35;self.memory_deferred=False;self.restart_count=0
    def start(self,config):
        self.resources=getattr(config,'twintext_resources',None)
        if self.started:return
        self.transport='files' if sys.platform=='win32' else 'stdio'
        if self.resources and hasattr(self.resources,'observe'):self.resources.observe()
        if self.resources and self.resources.pressured():
            self.memory_deferred=True;self._status('deferred-memory');return
        options={'source':str(config.input_file),'prepared':str(config.get_working_file_path('input.pdf')),
            'root':str(config.get_working_file_path('previews')),'langIn':config.lang_in,'langOut':config.lang_out,
            'currentPage':self.current_page,'documentOptions':getattr(config,'twintext_document_options',{}),
            'originalRotations':getattr(config,'twintext_source_rotations',getattr(config,'twintext_original_rotations',{})),
            'contentRotations':getattr(config,'twintext_content_rotations',{}),
            'preservedRegions':getattr(config,'twintext_preserved_regions',[])}
        options['ocrWorkaround']=bool(getattr(config,'ocr_workaround',False))
        options['scanPages']=sorted(getattr(config,'twintext_scan_pages',set()))
        options['ocrPages']=sorted(getattr(config,'twintext_ocr_pages',set()))
        options['visualSource']=str(getattr(config,'twintext_visual_source',config.input_file))
        with self.lock:
            if not hasattr(self,'options'):self.options=copy.deepcopy(options['documentOptions'])
            options['documentOptions']=copy.deepcopy(self.options);self.worker_options=options
        self.cancel=threading.Event();self.restart_count=0
        # Hidden Windows hosts and native DLL output must not be part of a
        # binary stdout protocol. Both modes use the identical native renderer.
        self.transport='files' if sys.platform=='win32' else 'stdio'
        self._launch();self.started=True
        self.pump=threading.Thread(target=self._pump,daemon=True);self.pump.start()
    def _status(self,state,**extra):
        self.publish({'type':'preview-status','state':state,'pageIndex':self.current_page,
            'transport':'isolated-'+self.transport+'-9040','restarts':self.restart_count,
            'snapshotCount':self.snapshot_count,'updateCount':self.update_count,'memoryDeferred':self.memory_deferred,**extra})
    def _launch(self):
        root=Path(self.worker_options['root']);root.mkdir(parents=True,exist_ok=True)
        self.log=(root/'worker.log').open('ab',buffering=0)
        try:
            folder=root/('transport-'+str(self.restart_count));folder.mkdir(mode=0o700,exist_ok=True)
            for name in ('request.bin','result.bin','options.bin','request.tmp','result.tmp','options.tmp'):
                (folder/name).unlink(missing_ok=True)
            if self.transport=='files':write_file(folder/'options.bin',self.worker_options)
            self.process=subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'--worker',
                *(['--files',str(folder)] if self.transport=='files' else [])],
                stdin=subprocess.DEVNULL if self.transport=='files' else subprocess.PIPE,
                stdout=subprocess.DEVNULL if self.transport=='files' else subprocess.PIPE,stderr=self.log,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if sys.platform=='win32' else 0)
            self.outbox=queue.Queue(maxsize=2);self.inbox=queue.Queue(maxsize=1)
            self.worker_ready=False;self.inflight=None;self.worker_started=time.monotonic()
            self.receiver_stop=threading.Event()
            process=self.process;outbox=self.outbox;inbox=self.inbox;stopped=self.receiver_stop
            def send_results(item):
                while not self.cancel.is_set() and not stopped.is_set():
                    try:outbox.put(item,timeout=.1);return
                    except queue.Full:continue
            def read_results():
                try:
                    while True:
                        if self.transport=='files':
                            path=folder/'result.bin'
                            while not path.exists():
                                if stopped.is_set() or self.cancel.is_set():return
                                if process.poll() is not None:raise EOFError('Preview worker exited: '+str(process.returncode))
                                time.sleep(.03)
                            item=read_file(path);file_operation(path.unlink)
                        else:item=read_frame(process.stdout)
                        send_results(item)
                        if self.cancel.is_set() or stopped.is_set():return
                except Exception as error:
                    # EOF/invalid frame is observable rather than a silent exit.
                    send_results({'type':'preview-worker-error','message':str(error)[:800]})
            self.receiver=threading.Thread(target=read_results,daemon=True);self.receiver.start()
            if self.transport=='stdio':write_frame(process.stdin,self.worker_options)
            def write_packets():
                while not self.cancel.is_set() and not stopped.is_set():
                    try:packet=inbox.get(timeout=.1)
                    except queue.Empty:continue
                    try:
                        if self.transport=='files':write_file(folder/'request.bin',packet)
                        else:write_frame(process.stdin,packet)
                    except Exception as error:
                        send_results({'type':'preview-worker-error','message':str(error)[:800]});return
            self.writer=threading.Thread(target=write_packets,daemon=True);self.writer.start()
            self._status('starting')
        except Exception:
            self._stop_worker();raise
    def _stop_worker(self):
        with self.worker_stop_lock:self._stop_worker_impl()
    def _stop_worker_impl(self):
        stopped=getattr(self,'receiver_stop',None)
        if stopped:stopped.set()
        process=getattr(self,'process',None)
        if process:
            if process.poll() is None:process.terminate()
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
            for channel in (process.stdin,process.stdout):
                try:
                    if channel:channel.close()
                except (OSError,ValueError):pass
        for thread in (getattr(self,'receiver',None),getattr(self,'writer',None)):
            if thread and thread is not threading.current_thread():thread.join(.3)
        log=getattr(self,'log',None)
        if log:log.close()
    def _recover(self,message):
        try:
            with (Path(self.worker_options['root'])/'worker.log').open('rb') as log:
                log.seek(0,2);log.seek(max(0,log.tell()-600));detail=log.read().decode('utf-8','replace').strip()
            if detail:message+=': '+detail
        except OSError:pass
        self.publish({'type':'preview-warning','pageIndex':self.current_page,'revision':0,'message':message[:800]})
        self._stop_worker()
        if self.cancel.is_set() or self.closed or self.restart_count>=1:
            self._status('unavailable',message=message[:800]);return False
        self.restart_count+=1
        # A polluted/closed stdout pipe gets an independent channel on retry.
        self.transport='files'
        # Rebuild from completed copies. Never repeat model/API translation.
        with self.lock:
            for index in self.pages:
                if abs(index-self.current_page)<=1:self._enqueue(index)
        try:self._launch();return True
        except Exception as error:
            self._status('unavailable',message=str(error)[:800]);return False
    def set_options(self,raw):
        with self.lock:
            self.options=raw if isinstance(raw,dict) else {}
            for index in self.pages:
                if abs(index-self.current_page)<=1:self._enqueue(index)
    def prepare(self,document,config,force=False):
        with self.lock:
            if self.memory_deferred:return
            if self.pages and not force:return
        # Start only once paragraphs exist, after the layout model's peak.
        # Publishing worker status must not hold the preview lock: view/control
        # requests acquire the job lock before entering this stream.
        self.start(config)
        with self.lock:
            if self.memory_deferred:return
            if force:self.pages={};self.locations={};self.completed={};self.changed={}
            for page in document.page:
                self.pages[page.page_number]=copy.deepcopy(page)
                self.completed[page.page_number]=set()
                self.changed[page.page_number]=set()
                for index,paragraph in enumerate(page.pdf_paragraph):self.locations[id(paragraph)]=(page.page_number,index)
            self.page_count=document.total_pages
    def _snapshot(self,index,packet):
        self.snapshot_count+=1
        page=copy.deepcopy(self.pages[index])
        return {**packet,'page':page,
            'references':copy.deepcopy(self.references.get(index,[])),
            'documentOptions':copy.deepcopy(getattr(self,'options',{}))}
    def _enqueue(self,index):
        if not self.completed.get(index):return
        self.revision+=1;self.update_count+=1
        packet={'revision':self.revision,'paragraphs':sorted(self.completed[index]),'changedParagraphs':sorted(self.changed.get(index,set())),
            'completedParagraphs':len(self.completed[index]),'totalParagraphs':len(self.pages[index].pdf_paragraph),
            'currentPage':self.current_page,'pageCount':getattr(self,'page_count',len(self.pages))}
        self.pending[index]=packet
        # Preserve exactly the first partial frame; subsequent completions only
        # mark this page dirty. Snapshot after coalescing, when the worker is free.
        if index not in self.seen:
            self.seen.add(index);self.first[index]=self._snapshot(index,self.pending.pop(index))
    def set_current_page(self,index):
        if not isinstance(index,int) or isinstance(index,bool) or index<0:raise ValueError('Invalid view page')
        with self.lock:
            if self.closed:return
            self.current_page=index
            self.pending={i:v for i,v in self.pending.items() if abs(i-index)<=1}
            self.first={i:v for i,v in self.first.items() if abs(i-index)<=1}
            for i in self.pages:
                if abs(i-index)<=1:self._enqueue(i)
    def completed_paragraph(self,paragraph,preserve_source=False):
        with self.lock:
            if self.closed or id(paragraph) not in self.locations:return
            index,position=self.locations[id(paragraph)]
            if not preserve_source:
                previous=self.pages[index].pdf_paragraph[position]
                if paragraph.unicode!=previous.unicode:self.changed.setdefault(index,set()).add(position)
                self.pages[index].pdf_paragraph[position]=copy.deepcopy(paragraph)
            self.completed[index].add(position)
            if abs(index-self.current_page)<=1:self._enqueue(index)
    def reference_updated(self,index,plan):
        with self.lock:
            if self.closed:return
            self.references[index]=plan
            if abs(index-self.current_page)<=1:self._enqueue(index)
    def seal(self):
        # No more paragraphs will arrive. Drain the first/latest visible frames
        # asynchronously, then retire the renderer before final font export.
        # Formal typesetting never waits for this optional work.
        with self.lock:self.closed=True
    def _pump(self):
        while not self.cancel.is_set():
            # Optional raster previews yield the budget to formal translation.
            # This event belongs only to the preview worker, never the job's
            # cancellation signal or the upstream document being typeset.
            if self.resources and self.resources.pressured():
                with self.lock:
                    self.memory_deferred=True;self.closed=True
                    for values in (self.pages,self.locations,self.completed,self.changed,self.references,self.pending,self.first):values.clear()
                self._stop_worker();self._status('deferred-memory');return
            try:
                result=self.outbox.get(timeout=.05)
                if result['type']=='preview-ready':
                    self.worker_ready=True;self._status('ready')
                elif result['type']=='preview-worker-error':
                    if self._recover(result['message']):continue
                    return
                else:
                    self.inflight=None;self.publish(result)
                    if result['type']=='native-page-preview':self._status('rendered',revision=result['revision'])
            except queue.Empty:pass
            age=time.monotonic()-self.worker_started
            if (not self.worker_ready and age>120) or (self.inflight and time.monotonic()-self.sent_at>120):
                if self._recover('Preview worker did not respond within 120 seconds'):continue
                return
            with self.lock:
                candidates={**self.pending,**self.first}
                index=min(candidates,key=lambda i:(abs(i-self.current_page),candidates[i]['revision'])) if candidates else None
                packet=None
                if self.worker_ready and self.inflight is None and index is not None:
                    first=index in self.first
                    latest=candidates[index]
                    complete=latest['completedParagraphs']==latest['totalParagraphs']
                    due=first or complete or self.closed or time.monotonic()-self.last_sent.get(index,0)>=self.interval
                    if due:
                        packet=self.first.pop(index) if first else self._snapshot(index,self.pending.pop(index))
                        self.last_sent[index]=time.monotonic()
                finishing=self.closed and packet is None and not self.pending and not self.first and self.inflight is None
            if packet:
                try:
                    # The writer reports serialization/pipe errors explicitly;
                    # this monitor stays responsive if a large pipe write blocks.
                    self.inflight=packet;self.sent_at=time.monotonic()
                    self.inbox.put_nowait(packet)
                except Exception as error:
                    if self._recover(str(error)):continue
                    return
            if finishing:
                self._stop_worker()
                with self.lock:
                    for values in (self.pages,self.locations,self.completed,self.changed,self.references,self.pending,self.first):values.clear()
                self._status('drained');return
    def finish(self,cancelled=False):
        if not self.started or getattr(self,'finished',False):return
        self.finished=True
        with self.lock:self.closed=True
        if cancelled:self.cancel.set()
        deadline=time.monotonic()+3
        while self.pump.is_alive() and time.monotonic()<deadline:self.pump.join(.1)
        self.cancel.set();self._stop_worker();self.pump.join(1)
        self._status('closed')

@contextmanager
def paragraph_previews(config,publish,current_page=0,ignore_references=False,ignore_headers=False):
    from babeldoc.format.pdf import high_level
    original=high_level.ILTranslator
    stream=PreviewStream(publish,current_page)
    # Rendering has no work during parsing/layout. Launch lazily in prepare()
    # instead of keeping a second font runtime resident beside model inference.
    class StreamingTranslator(original):
        def translate(self,document):
            self._reference_stream=stream
            try:stream.prepare(document,config)
            except Exception as error:publish(preview_failure(error,'prepare-document',current_page))
            # Queue the viewed page first without changing document order,
            # title context or the objects used by final typesetting.
            self._preview_target=min((p.page_number for p in document.page),key=lambda i:abs(i-stream.current_page),default=None)
            self._preview_deferred=[];self._preview_queued=False
            try:return super().translate(document)
            finally:stream.seal()
        def post_translate_paragraph(self,paragraph,*args,**kwargs):
            result=super().post_translate_paragraph(paragraph,*args,**kwargs)
            try:
                policy=getattr(self,'_reference_policy',None)
                stream.completed_paragraph(paragraph,bool(policy and policy.contains(paragraph.debug_id)))
            except Exception as error:publish(preview_failure(error,'snapshot-paragraph',current_page))
            return result
        def process_page(self,page,executor,*args,**kwargs):
            if not self._preview_queued and page.page_number!=self._preview_target:
                self._preview_deferred.append((page,executor,args,kwargs));return
            self._preview_queued=True
            class VisiblePriority:
                def submit(self,fn,*a,**k):
                    k['priority']=k.get('priority',0)+abs(page.page_number-stream.current_page)*10**9
                    return executor.submit(fn,*a,**k)
            result=super().process_page(page,VisiblePriority(),*args,**kwargs)
            deferred=self._preview_deferred;self._preview_deferred=[]
            for p,e,a,k in deferred:self.process_page(p,e,*a,**k)
            return result
    high_level.ILTranslator=StreamingTranslator
    try:yield stream
    finally:
        high_level.ILTranslator=original
        stream.finish(config.progress_monitor.cancel_event.is_set())

if __name__=='__main__' and sys.argv[1:2]==['--worker']:
    worker_main(sys.argv[3] if len(sys.argv)==4 and sys.argv[2]=='--files' else None)
