import os,subprocess,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import font_resources as resources
from babel_runtime import _load_cpu

class FontResourcesTests(unittest.TestCase):
    def test_cpu_session_uses_path_and_preserves_metadata_without_onnx_copy(self):
        class Model:pass
        session=SimpleNamespace(get_modelmeta=lambda:SimpleNamespace(custom_metadata_map={
            'stride':'32','names':"{0: 'title', 1: 'text'}"}))
        from unittest.mock import Mock
        ort=SimpleNamespace(InferenceSession=Mock(return_value=session))
        module=SimpleNamespace(OnnxModel=Model,onnxruntime=ort,get_doclayout_onnx_model_path=lambda:Path('layout.onnx'))
        result=_load_cpu(module,['CUDAExecutionProvider','CPUExecutionProvider'])
        ort.InferenceSession.assert_called_once_with('layout.onnx',providers=['CPUExecutionProvider'])
        self.assertIs(result.model,session);self.assertEqual(result._stride,32)
        self.assertEqual(result._names,{0:'title',1:'text'})
        with result.lock:self.assertTrue(result.lock.locked())

    def test_font_bundle_reuses_resources_but_keeps_config_and_caches_local(self):
        class Family:
            from_str=staticmethod(lambda value:value)
        class Mapper:
            def has_char(self,value):return self.translation_config.lang_out+value
            def map_in_type(self,value):return self.primary_font_family,value
        calls=[]
        def original(mapper,config):
            calls.append(config);mapper.fonts={'base':object()};mapper.translation_config=config
            mapper.primary_font_family=config.primary_font_family
        a,b,c,d,e=(Mapper() for _ in range(5))
        config=SimpleNamespace(lang_out='zh-CN',primary_font_family='serif')
        resources._font_init(original,a,config,Family)
        config.primary_font_family='sans-serif'
        resources._font_init(original,b,config,Family)
        self.assertIs(a.fonts,b.fonts);self.assertIs(b.translation_config,config)
        self.assertEqual(b.map_in_type('x'),('sans-serif','x'))
        self.assertIsNot(a.has_char,b.has_char);self.assertEqual(len(calls),1)
        with patch.dict(os.environ,{'TWINTEXT_BABEL_ASSETS':'changed'}):
            resources._font_init(original,c,config,Family)
        config.lang_out='ja'
        resources._font_init(original,d,config,Family)
        resources._font_init(original,e,SimpleNamespace(lang_out='ja',primary_font_family=None),Family)
        self.assertEqual(len(calls),4);self.assertIsNot(c.fonts,a.fonts);self.assertIsNot(d.fonts,e.fonts)

    def test_pdf_worker_real_subset_and_clean_preserve_text_and_pixels(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.pdf';subset=root/'subset.pdf';clean=root/'clean.pdf'
            with pymupdf.open() as pdf:
                page=pdf.new_page();page.insert_text((72,72),'Font export 123');pdf.save(source)
            for mode,args in [('subset',(str(source),str(subset))),('save',(str(subset),str(clean),1,True,True,True,False))]:
                process=resources.PDFProcess(mode,args);process.start();process.join(20)
                self.assertFalse(process.is_alive());self.assertEqual(process.exitcode,0)
            with pymupdf.open(source) as a,pymupdf.open(clean) as b:
                self.assertEqual(a[0].get_text(),b[0].get_text())
                self.assertEqual(a[0].get_pixmap().samples,b[0].get_pixmap().samples)

    def test_worker_imports_no_model_dependencies_while_processing_pdf(self):
        import pymupdf
        script=Path(resources.__file__).with_name('pdf_worker.py')
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.pdf';output=Path(folder)/'output.pdf'
            with pymupdf.open() as pdf:pdf.new_page();pdf.save(source)
            command="import runpy,sys;w=runpy.run_path("+repr(str(script))+");w['execute']('subset',"+repr([str(source),str(output)])+");assert not any(n.startswith(('babeldoc','onnxruntime','numpy')) for n in sys.modules)"
            subprocess.run([sys.executable,'-c',command],check=True,timeout=20)
            self.assertTrue(output.exists())

    def test_worker_failure_remains_observable(self):
        process=resources.PDFProcess('subset',('missing.pdf','unused.pdf'))
        process.start();process.join(20)
        self.assertFalse(process.is_alive());self.assertNotEqual(process.exitcode,0)

    def test_worker_can_be_terminated_and_reaped_without_spawn_state(self):
        process=resources.PDFProcess('unused',())
        process.process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
        self.assertTrue(process.is_alive());process.terminate();process.join(5)
        self.assertFalse(process.is_alive());self.assertIsNotNone(process.exitcode)

    def test_batch_config_and_font_resources_can_be_collected(self):
        import functools,gc,weakref
        class Config:lang_out='zh-CN';primary_font_family=None
        class Font:pass
        class Mapper:
            def has_char(self,value):return value
            def map_in_type(self,value):return value
        class Family:from_str=staticmethod(lambda value:value)
        def original(mapper,config):
            mapper.translation_config=config;mapper.fonts={'base':Font()}
            mapper.has_char=functools.lru_cache(maxsize=10)(mapper.has_char)
        config=Config();mapper=Mapper()
        resources._font_init(original,mapper,config,Family)
        config_ref,font_ref=weakref.ref(config),weakref.ref(mapper.fonts['base'])
        del config,mapper;gc.collect()
        self.assertIsNone(config_ref());self.assertIsNone(font_ref())

    def test_font_initialization_failure_does_not_publish_partial_bundle(self):
        from unittest.mock import Mock
        class Family:from_str=staticmethod(lambda value:value)
        mapper=SimpleNamespace();config=SimpleNamespace(lang_out='zh-CN',primary_font_family=None)
        original=Mock(side_effect=RuntimeError('font unavailable'))
        with self.assertRaisesRegex(RuntimeError,'unavailable'):
            resources._font_init(original,mapper,config,Family)
        self.assertFalse(hasattr(config,'twintext_font_bundle'))

    def test_windows_worker_hides_console_and_preserves_unicode_paths(self):
        with patch('font_resources.sys.platform','win32'),patch('font_resources.subprocess.CREATE_NO_WINDOW',134217728,create=True),patch('font_resources.subprocess.Popen') as popen:
            process=resources.PDFProcess('subset',('中文 输入.pdf','中文 输出.pdf'));process.start()
        import json
        self.assertEqual(json.loads(popen.call_args.args[0][-1]),['中文 输入.pdf','中文 输出.pdf'])
        self.assertEqual(popen.call_args.kwargs['creationflags'],134217728)

    def test_upstream_subset_failure_and_save_timeout_still_use_original_fallbacks(self):
        from babeldoc.format.pdf.document_il.backend import pdf_creater
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            config=SimpleNamespace(get_working_file_path=lambda name:Path(folder)/name)
            pdf=Mock();failed=Mock();failed.is_alive.return_value=False;failed.exitcode=1
            with patch.object(pdf_creater,'Process',return_value=failed):
                self.assertIs(pdf_creater.PDFCreater.subset_fonts_in_subprocess(pdf,config,'test'),pdf)
            hung=Mock();hung.is_alive.side_effect=[True,False]
            clock=SimpleNamespace(time=Mock(side_effect=[0,121]),sleep=Mock())
            with patch.object(pdf_creater,'Process',return_value=hung),patch.object(pdf_creater,'time',clock):
                self.assertFalse(pdf_creater.PDFCreater.save_pdf_with_timeout(pdf,'output.pdf',config))
            hung.terminate.assert_called_once();hung.join.assert_called_once_with(5)
            self.assertEqual(pdf.save.call_args.kwargs['clean'],False)

if __name__=='__main__':unittest.main()
