"""Measured source selection and resumable downloads of pinned, owned assets."""
from __future__ import annotations
import asyncio
import hashlib
from pathlib import Path
import time
from urllib.parse import urlsplit
import httpx

def valid(path, item):
    if not path.is_file() or path.stat().st_size != item['bytes']:return False
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha3_256').hexdigest() == item['sha3_256']

def urls_for(item):
    from babeldoc.assets import embedding_assets_metadata as metadata
    relative=Path(item['path']);family,name=relative.parts[1:]
    if family=='models':return list(dict.fromkeys(metadata.DOC_LAYOUT_ONNX_MODEL_URL.values()))
    if family in {'fonts','cmap'}:
        sources=metadata.FONT_URL_BY_UPSTREAM if family=='fonts' else metadata.CMAP_URL_BY_UPSTREAM
        urls=list(dict.fromkeys(factory(name) for factory in sources.values()))
        # The alternate HF endpoint hosts the same digest-verified assets.
        urls += [url.replace('https://huggingface.co/','https://hf-mirror.net/') for url in urls if url.startswith('https://huggingface.co/')]
        return list(dict.fromkeys(urls))
    if family=='tiktoken':
        for encoding in ('o200k_base','cl100k_base'):
            url=f'https://openaipublic.blob.core.windows.net/encodings/{encoding}.tiktoken'
            if hashlib.sha1(url.encode()).hexdigest()==name:return [url]
    raise ValueError('Unknown pinned asset family')

async def measure(client,url):
    started=time.monotonic();received=0
    try:
        async with asyncio.timeout(6):
            async with client.stream('GET',url,headers={'Range':'bytes=0-65535'},follow_redirects=True) as response:
                response.raise_for_status()
                if 'text/html' in response.headers.get('content-type',''):return 0
                async for chunk in response.aiter_bytes():
                    received+=len(chunk)
                    if received>=65536:break
        return min(received,65536)/max(.001,time.monotonic()-started)
    except (httpx.HTTPError,TimeoutError):return 0

async def ranked(client,urls):
    scores=await asyncio.gather(*(measure(client,url) for url in urls))
    return [url for _,url in sorted(zip(scores,urls),key=lambda pair:pair[0],reverse=True)]

async def transfer(client,url,path,item):
    partial=path.with_suffix(path.suffix+'.part')
    offset=partial.stat().st_size if partial.is_file() else 0
    if offset>=item['bytes']:partial.unlink(missing_ok=True);offset=0
    async with client.stream('GET',url,headers={'Range':f'bytes={offset}-'} if offset else {},follow_redirects=True) as response:
        response.raise_for_status()
        if offset and (response.status_code!=206 or not response.headers.get('content-range','').startswith(f'bytes {offset}-')):offset=0
        if response.status_code==206 and not response.headers.get('content-range','').startswith(f'bytes {offset}-'):
            raise ValueError('Invalid asset resume range')
        received=offset;window=time.monotonic();window_bytes=received
        with partial.open('ab' if offset else 'wb') as stream:
            async for chunk in response.aiter_bytes(262144):
                received+=len(chunk)
                if received>item['bytes']:raise ValueError('Asset exceeds pinned size')
                stream.write(chunk)
                elapsed=time.monotonic()-window
                if elapsed>=20:
                    if (received-window_bytes)/elapsed < 16384:raise TimeoutError('Asset source too slow')
                    window=time.monotonic();window_bytes=received
    if not valid(partial,item):partial.unlink(missing_ok=True);raise ValueError('Pinned asset digest mismatch')
    partial.replace(path)

async def prepare_async(root,items,emit):
    missing=[]
    for item in items:
        relative=Path(item['path'])
        if relative.is_absolute() or '..' in relative.parts or len(relative.parts)!=3 or relative.parts[0]!='assets':raise ValueError('Unsafe asset path')
        path=root/relative
        if not valid(path,item):missing.append((path,item))
    if not missing:return
    sem=asyncio.Semaphore(4);ordering={};locks={};completed=0
    async with httpx.AsyncClient(timeout=httpx.Timeout(30,connect=6),follow_redirects=True) as client:
        async def one(path,item):
            nonlocal completed
            async with sem:
                path.parent.mkdir(parents=True,exist_ok=True);urls=urls_for(item)
                family=Path(item['path']).parts[1];hosts=tuple(urlsplit(url).netloc for url in urls);key=(family,hosts)
                async with locks.setdefault(key,asyncio.Lock()):
                    if key not in ordering:
                        emit('download','正在测速并选择资源下载源…')
                        measured=await ranked(client,urls);ordering[key]=[urlsplit(url).netloc for url in measured]
                urls.sort(key=lambda url:ordering[key].index(urlsplit(url).netloc))
                errors=[]
                for attempt in range(2):
                    for url in urls:
                        try:await transfer(client,url,path,item);break
                        except (httpx.HTTPError,ValueError,TimeoutError) as error:
                            errors.append(type(error).__name__)
                            emit('download','当前资源下载源未完成，正在自动切换…')
                    else:
                        urls=await ranked(client,urls);continue
                    break
                else:raise RuntimeError('Pinned asset download unavailable: '+item['path']+' ('+','.join(errors)+')')
                completed+=1;emit('download',f'已校验资源 {completed} / {len(missing)}',round(completed/len(missing)*95))
        async with asyncio.TaskGroup() as group:
            for path,item in missing:group.create_task(one(path,item))

def prepare(root,items,emit):asyncio.run(prepare_async(Path(root),items,emit))
