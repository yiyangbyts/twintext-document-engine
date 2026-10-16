"""Bounded read-only rasters of the completed PDF; no model or layout imports.

Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
import base64,hashlib,json,os,subprocess,sys,tempfile,threading,time
from pathlib import Path

REVISION='native-final-raster-2.0.32-r1'
MAX_BYTES=96*1024*1024
_render_lock=threading.Lock()

def run(payload,cancel,cache_root=None):
    source=Path(payload.get('sourceFile','')).resolve()
    index=payload.get('pageIndex')
    scale=payload.get('scale',2)
    if not source.is_file() or source.suffix.lower()!='.pdf':raise ValueError('Expected a completed PDF file')
    if isinstance(index,bool) or not isinstance(index,int) or index<0:raise ValueError('Invalid page index')
    if isinstance(scale,bool) or not isinstance(scale,(int,float)) or not 1<=scale<=3:raise ValueError('Invalid raster scale')
    stat=source.stat()
    key=hashlib.sha256(json.dumps([str(source),stat.st_mtime_ns,stat.st_size,index,scale,REVISION]).encode()).hexdigest()
    folder=Path(cache_root or Path(tempfile.gettempdir())/'twintext-final-pages-2.0.32')
    folder.mkdir(parents=True,exist_ok=True)
    png=folder/(key+'.png');metadata=folder/(key+'.json')
    def read():
        try:
            info=json.loads(metadata.read_text());data=png.read_bytes()
            if not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data)>9*1024*1024 or hashlib.sha256(data).hexdigest()!=info.pop('sha256'):return None
            os.utime(png,None)
            return dict(**info,png=base64.b64encode(data).decode(),pipeline=REVISION,cacheHit=True)
        except (OSError,ValueError,KeyError):return None
    result=read()
    if result:return result
    while not _render_lock.acquire(timeout=.05):
        if cancel.is_set():raise RuntimeError('Cancelled page rendering')
    try:
        if cancel.is_set():raise RuntimeError('Cancelled page rendering')
        result=read()
        if result:return result
        temporary=folder/(key+'.tmp.png');process=None
        try:
            with tempfile.TemporaryFile() as errors:
                options=dict(stdout=subprocess.PIPE,stderr=errors)
                if sys.platform=='win32':options['creationflags']=subprocess.CREATE_NO_WINDOW
                started=time.monotonic()
                process=subprocess.Popen([sys.executable,'-B',str(Path(__file__).with_name('pdf_worker.py')),'raster',json.dumps([str(source),str(temporary),index,scale])],**options)
                while process.poll() is None:
                    if cancel.wait(.02):raise RuntimeError('Cancelled page rendering')
                    if time.monotonic()-started>12:raise RuntimeError('Page rendering timed out')
                output=process.stdout.read()
                if process.returncode:raise RuntimeError('Completed PDF page could not be rendered')
            info=json.loads(output)
            if not 0<info['width']*info['height']<=4_010_000:raise ValueError('Invalid raster dimensions')
            temporary.replace(png)
            metadata.write_text(json.dumps(dict(**info,sha256=hashlib.sha256(png.read_bytes()).hexdigest())))
            files=sorted(folder.glob('*.png'),key=lambda p:p.stat().st_mtime,reverse=True);size=0
            for file in files:
                size+=file.stat().st_size
                if size>MAX_BYTES and file!=png:
                    file.unlink(missing_ok=True);file.with_suffix('.json').unlink(missing_ok=True)
            result=read()
            if not result:raise RuntimeError('Invalid cached raster')
            result['cacheHit']=False
            return result
        finally:
            if process is not None:
                if process.poll() is None:process.kill();process.wait()
                if process.stdout:process.stdout.close()
            temporary.unlink(missing_ok=True)
    finally:_render_lock.release()
