import hashlib,json,subprocess,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import pymupdf
import page_raster

class PageRasterTests(unittest.TestCase):
    def test_exact_completed_pixels_disk_reuse_and_source_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'completed.pdf';cache=root/'cache'
            with pymupdf.open() as doc:
                p=doc.new_page(width=400,height=500);p.insert_text((40,80),'Final translated PDF');p.draw_rect((20,120,200,230),fill=(.1,.6,.9));p.set_rotation(90);doc.save(source)
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            payload=dict(sourceFile=str(source),pageIndex=0,scale=2)
            frame=page_raster.run(payload,threading.Event(),cache)
            self.assertEqual(frame['pipeline'],page_raster.REVISION);self.assertFalse(frame['cacheHit']);self.assertEqual(frame['rotation'],90)
            import base64
            with pymupdf.open(source) as doc:
                expected=doc[0].get_pixmap(matrix=pymupdf.Matrix(2,2),alpha=False)
                actual=pymupdf.Pixmap(base64.b64decode(frame['png']))
                self.assertEqual(actual.samples,expected.samples)
            with patch('page_raster.subprocess.Popen',side_effect=AssertionError('cached page must not launch a worker')):
                cached=page_raster.run(payload,threading.Event(),cache)
            self.assertTrue(cached['cacheHit']);self.assertEqual(cached['png'],frame['png']);self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),digest)
            # A source replacement must not reuse the former final-page image.
            with pymupdf.open() as doc:
                doc.new_page(width=400,height=500).insert_text((40,80),'Changed final PDF');doc.save(source)
            changed=page_raster.run(payload,threading.Event(),cache)
            self.assertFalse(changed['cacheHit']);self.assertNotEqual(changed['png'],frame['png'])
    def test_cancel_invalid_page_and_pixel_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'large.pdf'
            with pymupdf.open() as doc:doc.new_page(width=1800,height=2400);doc.save(source)
            payload=dict(sourceFile=str(source),pageIndex=0,scale=3)
            stop=threading.Event();stop.set()
            with self.assertRaisesRegex(RuntimeError,'Cancelled'):page_raster.run(payload,stop,root/'cache')
            frame=page_raster.run(payload,threading.Event(),root/'cache')
            self.assertLessEqual(frame['width']*frame['height'],4_010_000)
            for values in [dict(pageIndex=True),dict(pageIndex=-1),dict(scale=float('nan')),dict(scale=99)]:
                with self.assertRaises(ValueError):page_raster.run({**payload,**values},threading.Event(),root/'cache')
            with self.assertRaises(RuntimeError):page_raster.run({**payload,'pageIndex':10},threading.Event(),root/'cache')
    def test_worker_has_no_translation_model_or_font_runtime_imports(self):
        path=Path(__file__).with_name('pdf_worker.py')
        script='import runpy,sys;runpy.run_path('+repr(str(path))+');assert not any(n.startswith(("babeldoc","onnxruntime","numpy")) for n in sys.modules)'
        subprocess.run([sys.executable,'-B','-c',script],check=True)
    def test_render_job_never_enters_translation_and_can_release_its_raster(self):
        from service import Jobs
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.pdf'
            with pymupdf.open() as doc:doc.new_page().insert_text((40,80),'Final page');doc.save(source)
            jobs=Jobs('babeldoc','.')
            try:
                with patch('babel_adapter.run',side_effect=AssertionError('display must not translate')):
                    key=jobs.submit(dict(renderNativePage=True,sourceFile=str(source),pageIndex=0,scale=2))
                    import time
                    deadline=time.monotonic()+5
                    while jobs.snapshot(key)['state'] not in ('complete','error'):
                        self.assertLess(time.monotonic(),deadline);time.sleep(.01)
                    self.assertEqual(jobs.snapshot(key)['state'],'complete');self.assertFalse(jobs.snapshot(key)['requests'])
                    self.assertEqual(jobs.result(key)['pipeline'],page_raster.REVISION)
                    jobs.cancel(key);self.assertNotIn('result',jobs.jobs[key])
                    jobs.release(key);self.assertNotIn(key,jobs.jobs)
            finally:jobs.pool.shutdown(wait=True)

if __name__=='__main__':unittest.main()
