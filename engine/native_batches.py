"""Bound native PDF processing by pages; checkpoint completed parts on disk.

Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
The same BabelDOC pipeline typesets every part. Source page indexes, bookmarks
and unselected pages remain authoritative when the parts are assembled.
"""
from __future__ import annotations
import base64,errno,gc,hashlib,json,os,shutil,tempfile
from pathlib import Path


def selected_pages(value,count):
    if value in (None,''):return list(range(count))
    selected=set()
    for entry in str(value).split(','):
        bounds=entry.strip().split('-')
        if len(bounds)>2 or any(not n.isdigit() for n in bounds):raise ValueError('Invalid page range')
        first=int(bounds[0]);last=int(bounds[-1])
        if not 1<=first<=last<=count:raise ValueError('Invalid page range')
        selected.update(range(first-1,last))
    if not selected:raise ValueError('Empty page range')
    return sorted(selected)


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def cancelled(event):
    if event is not None and event.is_set():raise RuntimeError('Translation cancelled')


def fatal(error):
    if getattr(error,'twintext_translation_failure',False):return True
    if isinstance(error,(ImportError,FileNotFoundError,PermissionError)):return True
    return isinstance(error,OSError) and error.errno in (errno.ENOSPC,errno.EDQUOT,errno.EACCES,errno.EPERM,errno.EROFS)


def available_memory():
    try:
        if os.name=='nt':
            import ctypes
            class Memory(ctypes.Structure):
                _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(name,ctypes.c_ulonglong) for name in ('total','available','totalPage','availablePage','totalVirtual','availableVirtual','extended')]
            memory=Memory();memory.length=ctypes.sizeof(memory)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):return memory.available
        if Path('/proc/meminfo').is_file():
            for line in Path('/proc/meminfo').read_text().splitlines():
                if line.startswith('MemAvailable:'):return int(line.split()[1])*1024
        # Conservative share of physical RAM where a portable available-memory
        # counter is absent; never depend on an optional Python package.
        return os.sysconf('SC_PHYS_PAGES')*os.sysconf('SC_PAGE_SIZE')//2
    except (OSError,ValueError,AttributeError):return 4*1024**3


def page_limit(average,payload):
    memory=available_memory();ram_limit=1 if memory<2*1024**3 else 4 if memory<4*1024**3 else 8 if memory<8*1024**3 else 16
    requested=payload.get('batchPages',16)
    if isinstance(requested,bool) or not isinstance(requested,int) or not 1<=requested<=16:raise ValueError('Invalid native batch size')
    return max(1,min(requested,ram_limit,(16*1024*1024)//max(1,average)))


class BatchControl:
    def __init__(self,stream,offset):self.stream=stream;self.offset=offset
    def set_current_page(self,index):self.stream.set_current_page(max(0,index-self.offset))
    def set_options(self,options):self.stream.set_options(options)


def run_document(source,folder,payload,single,bridge=None,progress=None,cancel_event=None,on_preview=None,on_control=None,collector=None):
    import pymupdf
    from structure_plan import REFERENCES,END,STATEMENT
    from native_artifacts import text_pages
    from native_reflow import save_part,save_manifest
    folder.mkdir(parents=True,exist_ok=True)
    source_file=source if isinstance(source,Path) else folder/'original.pdf'
    if not isinstance(source,Path):source_file.write_bytes(source)
    with pymupdf.open(source_file) as original:
        count=original.page_count;selected=selected_pages(payload.get('pages'),count)
        if payload.get('pageIsolation') and len(selected)!=1:raise ValueError('Expected one isolated page')
        average=max(1,source_file.stat().st_size//max(1,count));limit=page_limit(average,payload)
        # Preserve small-document reflow only within the same resource budget.
        if count<=limit and source_file.stat().st_size<=16*1024*1024:
            regions,output=single(source_file.read_bytes(),folder,payload,bridge,progress,cancel_event,on_preview,on_control,collector)
            if output is not None and payload.get('outputFile'):
                destination=Path(payload['outputFile']);destination.parent.mkdir(parents=True,exist_ok=True)
                if destination.resolve()==source_file.resolve():raise ValueError('Cannot overwrite source PDF')
                temporary=destination.with_name(destination.name+'.tmp');temporary.write_bytes(output);temporary.replace(destination)
                if collector and 'document' in collector:
                    checkpoint=Path(str(destination)+'.parts');checkpoint.mkdir(parents=True,exist_ok=True)
                    part=save_part(collector,checkpoint/'0.il.gz',0,count-1)
                    if not isinstance(source,Path):shutil.copyfile(source_file,checkpoint/'source.pdf');source_file=checkpoint/'source.pdf'
                    collector['artifactFile']=save_manifest(checkpoint,source_file,selected,count,[part] if part else [])
                return regions,destination
            return regions,output

        chunks=[]
        for start in range(selected[0],selected[-1]+1,limit):
            end=min(selected[-1],start+limit-1)
            if any(start<=n<=end for n in selected):chunks.append((start,end))
        focus=int(payload.get('currentPage',selected[0]));chunks.sort(key=lambda part:(not part[0]<=focus<=part[1],part[0]))
        # A light text scan supplies bibliography context without retaining IL
        # or running the layout model over preceding parts before the first preview.
        reference_states={};in_refs=False
        for index in range(selected[-1]+1):
            cancelled(cancel_event);reference_states[index]=in_refs
            for line in original[index].get_text('text').splitlines():
                text=line.strip()
                if REFERENCES.fullmatch(text):in_refs=True
                elif END.match(text) or STATEMENT.match(text):in_refs=False

        destination=Path(payload.get('outputFile') or folder/'translated.pdf')
        if destination.resolve()==source_file.resolve():raise ValueError('Cannot overwrite source PDF')
        destination.parent.mkdir(parents=True,exist_ok=True)
        checkpoint=Path(str(destination)+'.parts') if payload.get('outputFile') else folder/'parts'
        checkpoint.mkdir(parents=True,exist_ok=True)
        if not isinstance(source,Path):shutil.copyfile(source_file,checkpoint/'source.pdf');source_file=checkpoint/'source.pdf'
        signature=hashlib.sha256(json.dumps(dict(source=digest(source_file),pages=selected,cacheKey=payload.get('cacheKey'),
            sourceLanguage=payload.get('sourceLanguage'),targetLanguage=payload.get('targetLanguage'),documentOptions=payload.get('documentOptions')),sort_keys=True).encode()).hexdigest()
        failed=[];export=[];completed=set();revisions={};selected_set=set(selected);reflow_parts=[]
        with pymupdf.open(source_file) as assembled:
            toc=assembled.get_toc(simple=False)
            def publish(event,offset):
                if not on_preview:return
                value=dict(event)
                if isinstance(value.get('pageIndex'),int):
                    value['pageIndex']+=offset
                    if value['type'] not in ('preview-warning','preview-status'):
                        index=value['pageIndex'];revisions[index]=revisions.get(index,0)+1;value['revision']=revisions[index]
                on_preview(value)
            def part(start,end):
                cancelled(cancel_event)
                indexes=[n for n in selected if start<=n<=end]
                part_file=checkpoint/f'{start}-{end}.pdf';metadata=part_file.with_suffix('.json');cached=None
                try:
                    data=json.loads(metadata.read_text())
                    if data['signature']==signature and data['sha256']==digest(part_file):
                        with pymupdf.open(part_file) as saved:
                            if saved.page_count==end-start+1:cached=data
                except (OSError,ValueError,KeyError):pass
                if cached is None:
                    metadata.unlink(missing_ok=True)
                    before=getattr(bridge,'retained_count',0)
                    local_collector={} if collector is not None else None
                    try:
                        with tempfile.TemporaryDirectory(prefix='part-',dir=folder) as temporary:
                            work=Path(temporary)
                            with pymupdf.open() as document:
                                document.insert_pdf(original,from_page=start,to_page=end)
                                data=document.tobytes(garbage=3,deflate=True)
                            local={**payload,'pages':','.join(str(n-start+1) for n in indexes),'pageIsolation':False,
                                'currentPage':max(0,min(end-start,focus-start)),'_structureState':{'inReferences':reference_states[start]}}
                            local.pop('outputFile',None)
                            def update(**event):
                                if progress:progress(**{**event,'overall_progress':100*len(completed)/len(selected),
                                    'completed_pages':len(completed),'total_pages':len(selected),'batch_first':start,'batch_last':end,'page_count':count})
                            _,output=single(data,work,local,bridge,update,cancel_event,
                                (lambda event:publish(event,start)) if on_preview else None,
                                (lambda stream:on_control(BatchControl(stream,start))) if on_control else None,local_collector)
                            if output is None:raise ValueError('Native batch has no PDF')
                            with pymupdf.open(stream=output,filetype='pdf') as result:
                                if result.page_count!=end-start+1:raise ValueError('Native batch page alignment failed')
                            temporary_file=part_file.with_suffix('.tmp');temporary_file.write_bytes(output);temporary_file.replace(part_file)
                            pages=text_pages(local_collector) if local_collector and 'document' in local_collector else []
                            pages=[{**p,'index':p['index']+start} for p in pages]
                            cached=dict(signature=signature,sha256=digest(part_file),exportPages=pages)
                            reflow_part=save_part(local_collector,checkpoint/f'{start}-{end}.il.gz',start,end)
                            if reflow_part:cached['reflowPart']=reflow_part
                            # A retained/refused paragraph must be eligible for
                            # translation again, rather than becoming a success cache.
                            if getattr(bridge,'retained_count',0)==before:
                                temporary_meta=metadata.with_suffix('.tmp');temporary_meta.write_text(json.dumps(cached));temporary_meta.replace(metadata)
                    except Exception as error:
                        cancelled(cancel_event)
                        if fatal(error):raise
                        if start<end:
                            middle=(start+end)//2;part(start,middle);part(middle+1,end);return
                        failed.append(start)
                        if on_preview:on_preview({'type':'preview-warning','pageIndex':start,'message':'Native page kept its source after page processing failed.','operation':'batch-page','errorType':type(error).__name__})
                        completed.add(start)
                        return
                    finally:
                        local_collector=None;gc.collect()
                with pymupdf.open(part_file) as translated:
                    for index in indexes:
                        assembled.delete_page(index);assembled.insert_pdf(translated,from_page=index-start,to_page=index-start,start_at=index)
                    # Completed checkpoint pages can become visible before
                    # the rest of a resumed book has finished.
                    if on_preview and start<=focus<=end and focus in selected_set:
                        with pymupdf.open() as one:
                            one.insert_pdf(translated,from_page=focus-start,to_page=focus-start)
                            publish({'type':'native-page-preview','profile':'native-document-9029-r1','pageIndex':focus-start,
                                'revision':1,'pdf':base64.b64encode(one.tobytes()).decode()},start)
                export.extend(p for p in cached.get('exportPages',[]) if p['index'] in selected_set)
                if cached.get('reflowPart'):reflow_parts.append(cached['reflowPart'])
                completed.update(indexes)
                if progress:progress(type='batch-complete',stage='completed-native-batch',completed_pages=len(completed),total_pages=len(selected),overall_progress=100*len(completed)/len(selected),page_count=count)
            for start,end in chunks:part(start,end)
            cancelled(cancel_event)
            if toc:assembled.set_toc(toc)
            # Copy original cross-part destinations which cannot survive
            # extraction into an independently typeset part.
            for index in selected:
                links=assembled[index].get_links()
                for link in original[index].get_links():
                    if link.get('kind')!=pymupdf.LINK_GOTO:continue
                    if not any(x.get('kind')==link['kind'] and x.get('page')==link.get('page') and x.get('from')==link.get('from') for x in links):
                        assembled[index].insert_link({k:v for k,v in link.items() if k not in ('xref','id')})
            if payload.get('pageIsolation'):
                with pymupdf.open() as isolated:
                    isolated.insert_pdf(assembled,from_page=selected[0],to_page=selected[0]);isolated.save(destination)
                output_count=1
            else:
                if progress:progress(type='progress_update',stage='assembling-native-document',completed_pages=len(completed),total_pages=len(selected),page_count=count)
                temporary=destination.with_name(destination.name+'.tmp');assembled.save(temporary,garbage=3,deflate=True);temporary.replace(destination);output_count=count
        with pymupdf.open(destination) as result:
            if result.page_count!=output_count:raise ValueError('Native assembled page alignment failed')
        if collector is not None:collector.update(exportPages=sorted(export,key=lambda p:p['index']),failedPages=sorted(failed),batched=True,
            artifactFile=save_manifest(checkpoint,source_file,sorted(selected_set-set(failed)),count,reflow_parts))
        if progress:progress(type='validated',page_count=output_count,completed_pages=len(completed),total_pages=len(selected),overall_progress=100)
        return [],destination if payload.get('outputFile') else destination.read_bytes()
