"""Share unchanged font metrics within a process; keep PDF workers lean.

Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only

No font selection, glyph metrics, subsetting, save flags or timeout policy is
changed. Preview owns a separate process and a separate font pool.
"""
from __future__ import annotations
import functools,os,subprocess,sys,threading
from pathlib import Path

_lock=threading.RLock()
_installed=False

def _font_init(original,mapper,config,family_type):
    assert config.primary_font_family in (None,'serif','sans-serif','script')
    key=(os.environ.get('TWINTEXT_BABEL_ASSETS',''),config.lang_out)
    with _lock:
        cached=getattr(config,'twintext_font_bundle',None)
        if cached is None or cached[0]!=key:
            original(mapper,config)
            # Only immutable font resources are shared. Never retain another
            # job's config/progress monitor or mapper-bound lookup caches.
            bundle={k:v for k,v in vars(mapper).items() if k not in
                ('translation_config','primary_font_family','has_char','map_in_type')}
            # The config owns one native batch. A global pool retains hundreds
            # of MiB into the next batch's parser/model peak, even after GC.
            config.twintext_font_bundle=(key,bundle)
            return
        mapper.__dict__.update(cached[1])
    mapper.translation_config=config
    mapper.primary_font_family=family_type.from_str(config.primary_font_family)
    mapper.has_char=functools.lru_cache(maxsize=10240,typed=True)(mapper.has_char)
    mapper.map_in_type=functools.lru_cache(maxsize=10240,typed=True)(mapper.map_in_type)

class PDFProcess:
    """The upstream Process interface, without importing BabelDOC in children.

    Windows spawn normally imports pdf_creater, TranslationConfig and their
    model/numpy/scipy dependency graph just to call two PyMuPDF operations.
    File arguments already exist in upstream; keep its caller and fallbacks.
    """
    def __init__(self,mode,args):self.mode=mode;self.args=args;self.process=None
    def start(self):
        import json
        options={'creationflags':subprocess.CREATE_NO_WINDOW} if sys.platform=='win32' else {}
        self.process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('pdf_worker.py')),
            self.mode,json.dumps(self.args)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**options)
    def is_alive(self):return self.process.poll() is None
    @property
    def exitcode(self):return self.process.poll()
    def terminate(self):
        if self.is_alive():self.process.terminate()
    def kill(self):
        if self.is_alive():self.process.kill()
    def join(self,timeout=None):
        try:self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:pass

def install():
    global _installed
    with _lock:
        if _installed:return
        from babeldoc.format.pdf.document_il.utils import fontmap
        from babeldoc.format.pdf.document_il.backend import pdf_creater
        original=fontmap.FontMapper.__init__
        def init(mapper,config):return _font_init(original,mapper,config,fontmap.PrimaryFontFamily)
        fontmap.FontMapper.__init__=init
        process=pdf_creater.Process
        def factory(*args,**kwargs):
            target=kwargs.get('target')
            if target is pdf_creater._subset_fonts_process:
                return PDFProcess('subset',kwargs['args'])
            if target is pdf_creater._save_pdf_clean_process:
                return PDFProcess('save',kwargs['args'])
            return process(*args,**kwargs)
        pdf_creater.Process=factory
        _installed=True
