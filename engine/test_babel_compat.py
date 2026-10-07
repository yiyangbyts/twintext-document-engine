import base64,copy,importlib.util,pickle,sys,threading,unittest
from types import SimpleNamespace
from unittest.mock import patch
from babel_compat import install_graphics_copy,input_documents
from service import Jobs

class CompatTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('babeldoc'),'Requires the bundled BabelDOC SDK')
    def test_deep_graphics_chain_copies_and_transports_identical_commands(self):
        from babeldoc.format.pdf.document_il.frontend.il_creater_active_support import (
            PassthroughSnapshot,LazyPassthroughInstruction,replace_first_passthrough_operator)
        snapshot=PassthroughSnapshot()
        for i in range(3000):snapshot=replace_first_passthrough_operator(snapshot,'w',('w',str(i)))
        value=LazyPassthroughInstruction(snapshot,include_clipping=True,suffix_parts=('1 0 0 rg',))
        page=SimpleNamespace(graphics=value,other=value,box=[1,2,3,4])
        # This is the actual upstream type found in the Windows traceback.
        original=LazyPassthroughInstruction.__dict__.get('__deepcopy__')
        if original:del LazyPassthroughInstruction.__deepcopy__
        try:
            with self.assertRaises(RecursionError):copy.deepcopy(page)
            limit=sys.getrecursionlimit();install_graphics_copy()
            cloned=copy.deepcopy(page)
            self.assertEqual(cloned.graphics,value.materialize())
            self.assertIsInstance(cloned.graphics,str)
            self.assertIs(cloned.graphics,cloned.other)
            self.assertIs(value.snapshot,snapshot)
            self.assertEqual(snapshot.event_count,3000)
            self.assertEqual(pickle.loads(pickle.dumps(cloned)).graphics,value.materialize())
            cloned.box[0]=100;self.assertEqual(page.box[0],1)
            self.assertEqual(sys.getrecursionlimit(),limit)
        finally:
            if original:LazyPassthroughInstruction.__deepcopy__=original
            elif '__deepcopy__' in LazyPassthroughInstruction.__dict__:del LazyPassthroughInstruction.__deepcopy__
    @unittest.skipUnless(importlib.util.find_spec('babeldoc'),'Requires the bundled BabelDOC SDK')
    def test_pipeline_input_handles_close_on_success_and_error_and_restore_hooks(self):
        from babeldoc.format.pdf import high_level
        for failed in (False,True):
            documents=[]
            def opened(*args,**kwargs):
                doc=SimpleNamespace(is_closed=False)
                def close():doc.is_closed=True
                doc.close=close;documents.append(doc);return doc
            with patch.object(high_level,'open_pdf_with_save_fallback',side_effect=opened) as original,patch.object(high_level,'check_metadata') as metadata,patch.object(high_level,'Document',side_effect=opened) as constructor:
                try:
                    with input_documents():
                        doc=high_level.open_pdf_with_save_fallback('source','prepared')
                        self.assertFalse(doc.is_closed)
                        toc=high_level.Document('source');self.assertFalse(toc.is_closed)
                        check=opened();high_level.check_metadata(check);self.assertTrue(check.is_closed)
                        if failed:raise ValueError('parsing failed')
                except ValueError:self.assertTrue(failed)
                self.assertTrue(all(d.is_closed for d in documents))
                self.assertIs(high_level.open_pdf_with_save_fallback,original)
                self.assertIs(high_level.check_metadata,metadata)
                self.assertIs(high_level.Document,constructor)
    def test_windows_cleanup_lock_does_not_discard_translated_pdf(self):
        from temporary_workspace import temporary_workspace
        error=PermissionError('Windows file is occupied');error.winerror=32
        jobs=Jobs('babeldoc','model')
        job={'id':'locked','state':'queued','created':0,'requests':{},'cancelled':False,'cancel_event':threading.Event()}
        jobs.jobs['locked']=job
        try:
            with patch('babel_adapter.run',return_value=([],b'%PDF-translated')),patch('temporary_workspace.shutil.rmtree',side_effect=error),patch('temporary_workspace.threading.Timer') as timer:
                jobs.run(job,{'pdf':base64.b64encode(b'%PDF-source').decode(),'documentExport':True,'nativeExport':True})
                self.assertEqual(job['state'],'complete')
                self.assertEqual(base64.b64decode(job['result']['pdf']),b'%PDF-translated')
                timer.return_value.start.assert_called_once()
        finally:jobs.pool.shutdown()
    def test_cleanup_retries_owned_path_and_preserves_pipeline_exception(self):
        from temporary_workspace import temporary_workspace
        with patch('temporary_workspace.tempfile.mkdtemp',return_value='owned-temp'),patch('temporary_workspace.shutil.rmtree',side_effect=[PermissionError('occupied'),None]) as remove:
            with self.assertRaisesRegex(ValueError,'real translation failure'):
                with temporary_workspace('twintext-babel-'):raise ValueError('real translation failure')
            self.assertEqual([c.args[0] for c in remove.call_args_list],['owned-temp','owned-temp'])

if __name__=='__main__':unittest.main()
