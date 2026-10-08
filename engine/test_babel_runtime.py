from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import os,threading,time,unittest
import babel_runtime
from service import Jobs

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.state=babel_runtime._model,babel_runtime._asset_key
        babel_runtime._model=None;babel_runtime._asset_key=None
    def tearDown(self):babel_runtime._model,babel_runtime._asset_key=self.state
    def test_service_warmup_and_concurrent_tasks_share_one_model(self):
        model=object();calls=[]
        def load():calls.append(threading.get_ident());time.sleep(.02);return model
        jobs=Jobs('babeldoc','unused')
        try:
            with patch('babel_runtime._load',side_effect=load):
                jobs.load()
                with ThreadPoolExecutor(max_workers=8) as pool:
                    results=list(pool.map(lambda _:babel_runtime.layout_model(),range(16)))
                self.assertIs(jobs.layout,model)
                self.assertTrue(all(item is model for item in results));self.assertEqual(len(calls),1)
        finally:jobs.pool.shutdown(wait=False,cancel_futures=True)
    def test_successful_native_part_does_not_set_user_cancel_signal(self):
        from babeldoc.progress_monitor import ProgressMonitor
        event=threading.Event();messages=[]
        Monitor=babel_runtime.monitor_type(ProgressMonitor)
        monitor=Monitor([('translation',1)],cancel_event=event,finish_callback=lambda **value:messages.append(value))
        monitor.on_finish();self.assertFalse(event.is_set());self.assertEqual(messages,[])
        # A second part remains runnable; a real cancel still propagates.
        second=Monitor([('translation',1)],cancel_event=event,finish_callback=lambda **value:messages.append(value))
        second.raise_if_cancelled();second.cancel();self.assertTrue(event.is_set());second.on_finish();self.assertEqual(messages[0]['type'],'error')
    def test_changed_asset_root_reloads_and_failed_load_can_retry(self):
        first,second=object(),object()
        with patch('babel_runtime._load',side_effect=[first,RuntimeError('Model unavailable'),second]) as load:
            with patch.dict(os.environ,{'TWINTEXT_BABEL_ASSETS':'first'}):
                self.assertIs(babel_runtime.layout_model(),first)
            with patch.dict(os.environ,{'TWINTEXT_BABEL_ASSETS':'second'}):
                with self.assertRaisesRegex(RuntimeError,'unavailable'):babel_runtime.layout_model()
                self.assertIs(babel_runtime.layout_model(),second)
                self.assertIs(babel_runtime.layout_model(),second)
            self.assertEqual(load.call_count,3)

if __name__=='__main__':unittest.main()
