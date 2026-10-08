"""Persist bounded translated IL and reflow the visible page before the book.

Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
Only BabelDOC's fixed IL dataclasses are decoded; no pickle or client code.
"""
from __future__ import annotations
import base64,dataclasses,gzip,json,logging
from functools import lru_cache
from pathlib import Path

PROFILE='native-reflow-2.0.10-v1'


@lru_cache(maxsize=1)
def classes():
    from babeldoc.format.pdf.document_il import il_version_1
    return {name:kind for name,kind in vars(il_version_1).items() if isinstance(kind,type) and dataclasses.is_dataclass(kind)}


def encode(value):
    if dataclasses.is_dataclass(value):
        if type(value).__name__ not in classes():raise ValueError('Unsupported reflow class')
        return {'type':type(value).__name__,'fields':{f.name:encode(getattr(value,f.name)) for f in dataclasses.fields(value)}}
    if isinstance(value,bytes):return {'bytes':base64.b64encode(value).decode()}
    if isinstance(value,dict):return {'dict':[[encode(k),encode(v)] for k,v in value.items()]}
    if isinstance(value,(tuple,set)):return {'tuple' if isinstance(value,tuple) else 'set':[encode(v) for v in value]}
    if isinstance(value,list):return [encode(v) for v in value]
    if value is None or isinstance(value,(str,int,float,bool)):return value
    from babeldoc.format.pdf.document_il.frontend.il_creater_active_support import LazyPassthroughInstruction
    if isinstance(value,LazyPassthroughInstruction):return value.materialize()
    raise ValueError('Unsupported reflow value')


def decode(value,registry):
    if isinstance(value,list):return [decode(v,registry) for v in value]
    if not isinstance(value,dict):return value
    if set(value)=={'type','fields'}:
        kind=registry.get(value['type'])
        if kind is None or not isinstance(value['fields'],dict):raise ValueError('Invalid reflow class')
        fields={f.name for f in dataclasses.fields(kind)}
        if not set(value['fields'])<=fields:raise ValueError('Invalid reflow fields')
        return kind(**{k:decode(v,registry) for k,v in value['fields'].items()})
    if set(value)=={'bytes'}:return base64.b64decode(value['bytes'],validate=True)
    if set(value)=={'dict'}:return {decode(k,registry):decode(v,registry) for k,v in value['dict']}
    if set(value)=={'tuple'}:return tuple(decode(v,registry) for v in value['tuple'])
    if set(value)=={'set'}:return set(decode(v,registry) for v in value['set'])
    raise ValueError('Invalid reflow data')


def save_part(artifact,path,first,last):
    from native_batches import digest
    if not artifact or 'document' not in artifact:return None
    temporary=path.with_suffix('.tmp')
    try:
        raw=json.dumps(encode(artifact),separators=(',',':'),ensure_ascii=False).encode()
        with gzip.open(temporary,'wb',compresslevel=1) as stream:stream.write(raw)
        temporary.replace(path)
        return dict(first=first,last=last,path=path.name,sha256=digest(path))
    except Exception as error:
        temporary.unlink(missing_ok=True)
        logging.getLogger(__name__).warning('Local reflow checkpoint unavailable: %s',error)
        return None


def save_manifest(folder,source,selected,count,parts):
    from native_batches import digest
    covered={n for part in parts for n in range(part['first'],part['last']+1)}
    if not parts or not selected or not set(selected)<=covered:return None
    target=folder/'reflow.json';temporary=target.with_suffix('.tmp')
    raw=dict(profile=PROFILE,sourceFile=str(source.resolve()),sourceSHA256=digest(source),pages=selected,pageCount=count,parts=parts)
    temporary.write_text(json.dumps(raw),encoding='utf-8');temporary.replace(target)
    return str(target.resolve())


def load_manifest(path):
    from native_batches import digest
    path=Path(path)
    if not path.is_file():raise ValueError('native_artifact_expired')
    value=json.loads(path.read_text(encoding='utf-8'))
    if value.get('profile')!=PROFILE or not isinstance(value.get('parts'),list):raise ValueError('native_artifact_expired')
    if digest(value['sourceFile'])!=value.get('sourceSHA256'):raise ValueError('Reflow source changed')
    selected=value.get('pages');count=value.get('pageCount')
    if not isinstance(count,int) or isinstance(count,bool) or count<1 or not isinstance(selected,list) or not selected or any(type(n) is not int or not 0<=n<count for n in selected):raise ValueError('Invalid reflow page range')
    covered=set()
    for part in value['parts']:
        first,last=part['first'],part['last']
        if type(first) is not int or type(last) is not int or not 0<=first<=last<count or last-first>=16:raise ValueError('Invalid reflow part')
        if covered.intersection(range(first,last+1)):raise ValueError('Overlapping reflow parts')
        covered.update(range(first,last+1))
        if Path(part['path']).name!=part['path']:raise ValueError('Invalid reflow checkpoint path')
    return path.parent,value


def load_part(folder,part):
    from native_batches import digest
    path=folder/part['path']
    if not path.is_file() or path.is_symlink() or digest(path)!=part['sha256']:raise ValueError('native_artifact_expired')
    with gzip.open(path,'rb') as stream:artifact=decode(json.load(stream),classes())
    if len(artifact['document'].page)>16:raise ValueError('Invalid reflow size')
    return artifact


def run(payload,folder,cancel,on_preview=None):
    import copy,gc,pymupdf
    from native_artifacts import reflow,exported
    from native_batches import cancelled
    root,manifest=load_manifest(payload['artifactFile'])
    selected=set(manifest['pages']);focus=payload.get('currentPage',min(selected))
    parts=sorted(manifest['parts'],key=lambda p:(not p['first']<=focus<=p['last'],p['first']))
    with pymupdf.open(manifest['sourceFile']) as output:
        toc=output.get_toc(simple=False)
        for part in parts:
            cancelled(cancel);artifact=load_part(root,part);offset=part['first'];local=focus-offset
            if on_preview and offset<=focus<=part['last'] and focus in selected:
                visible={**artifact,'document':copy.copy(artifact['document']),'pages':str(local+1)}
                visible['document'].page=[copy.deepcopy(p) for p in artifact['document'].page if p.page_number==local]
                result=reflow(visible,folder/f'visible-{offset}',payload.get('documentOptions'),cancel)
                with pymupdf.open(stream=base64.b64decode(result['pdf']),filetype='pdf') as full,pymupdf.open() as one:
                    one.insert_pdf(full,from_page=local,to_page=local)
                    on_preview(dict(type='native-page-preview',profile='native-document-9029-r1',pageIndex=focus,revision=1,cursor=1,pdf=base64.b64encode(one.tobytes()).decode()))
                del visible,result
            cancelled(cancel)
            result=reflow(artifact,folder/f'part-{offset}',payload.get('documentOptions'),cancel)
            with pymupdf.open(stream=base64.b64decode(result['pdf']),filetype='pdf') as translated:
                for index in range(part['first'],part['last']+1):
                    if index in selected:output.delete_page(index);output.insert_pdf(translated,from_page=index-offset,to_page=index-offset,start_at=index)
            del artifact,result;gc.collect()
        cancelled(cancel)
        if toc:output.set_toc(toc)
        with pymupdf.open(manifest['sourceFile']) as source:
            for index in selected:
                links=output[index].get_links()
                for link in source[index].get_links():
                    if link.get('kind')==pymupdf.LINK_GOTO and not any(x.get('kind')==link['kind'] and x.get('page')==link.get('page') and x.get('from')==link.get('from') for x in links):output[index].insert_link({k:v for k,v in link.items() if k not in ('xref','id')})
        result=exported(output,payload,'native-pdf-9020',manifest['pageCount'])
    result['artifactFile']=payload['artifactFile'];return result
