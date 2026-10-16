"""Memory admission and telemetry, including Windows private-byte samples."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from resource_budget import ResourceBudget, MIB, windows_commit_available, memory_sample


class ResourceTests(unittest.TestCase):
    def test_pressure_reduces_admission_and_preserves_stage_peaks(self):
        value=dict(rssBytes=100*MIB, privateBytes=80*MIB, childRSSBytes=20*MIB, availableBytes=4096*MIB)
        budget=ResourceBudget({'memoryBudgetMB':512},sample=lambda:dict(value))
        self.assertEqual(budget.batch_pages(1000,16),8)
        value.update(rssBytes=480*MIB,privateBytes=400*MIB,childRSSBytes=60*MIB)
        budget.observe('Typesetting')
        self.assertEqual(budget.batch_pages(1000,16),1)
        value['rssBytes']=600*MIB;budget.observe('Generate PDF')
        self.assertTrue(budget.pressured())
        value['rssBytes']=110*MIB;budget.observe('complete')
        report=budget.report()
        self.assertEqual(report['peakRSSBytes'],600*MIB)
        self.assertEqual(report['stagePeaks']['Typesetting'],480*MIB)
        self.assertEqual(report['peakPrivateBytes'],400*MIB)
        self.assertGreater(report['pressureEvents'],0)
        self.assertNotIn('text',str(report))

    def test_low_system_memory_and_large_pages_limit_work_without_cancelling(self):
        value=dict(rssBytes=100*MIB,privateBytes=100*MIB,childRSSBytes=0,availableBytes=100*MIB)
        budget=ResourceBudget(sample=lambda:dict(value))
        self.assertEqual(budget.batch_pages(10*MIB,16),1)
        self.assertTrue(budget.pressured())
        self.assertFalse(budget.stop.is_set())
    def test_windows_private_commit_pressure_survives_a_small_working_set(self):
        value=dict(rssBytes=100*MIB,privateBytes=100*MIB,childRSSBytes=0,availableBytes=4*1024*MIB)
        budget=ResourceBudget({'memoryBudgetMB':512},sample=lambda:dict(value))
        budget.completed_batch(1,100*MIB)
        value.update(rssBytes=120*MIB,privateBytes=600*MIB)
        budget.observe('paged-windows-process')
        self.assertTrue(budget.pressured());self.assertEqual(budget.batch_pages(1000,16),1)
        self.assertEqual(budget.report()['peakPrivateBytes'],600*MIB)

    def test_invalid_budget_and_monitor_lifetime(self):
        for value in [True,0,127,8193,'512']:
            with self.assertRaises(ValueError):ResourceBudget({'memoryBudgetMB':value})
        with ResourceBudget() as budget:self.assertTrue(budget.thread.is_alive())
        self.assertFalse(budget.thread.is_alive())
    def test_healthy_system_keeps_normal_batches_despite_model_and_font_residency(self):
        value=dict(rssBytes=2400*MIB,privateBytes=3000*MIB,childRSSBytes=1000*MIB,availableBytes=6*1024*MIB)
        budget=ResourceBudget(sample=lambda:dict(value))
        self.assertIsNone(budget.limit);self.assertFalse(budget.pressured())
        self.assertEqual(budget.batch_pages(1000,16),16)
        self.assertEqual(budget.report()['budgetMode'],'system-headroom')
    def test_historical_export_peak_cannot_ratchet_later_batches_to_one_page(self):
        value=dict(rssBytes=800*MIB,privateBytes=800*MIB,childRSSBytes=0,availableBytes=6*1024*MIB)
        budget=ResourceBudget(sample=lambda:dict(value))
        for n in range(12):
            value['rssBytes']=3000*MIB;budget.observe('Subset font')
            value['rssBytes']=800*MIB;budget.completed_batch(8,800*MIB)
            self.assertEqual(budget.batch_pages(1000,16),16)
        self.assertEqual(budget.report()['completedBatches'],12)
        self.assertEqual(budget.report()['peakRSSBytes'],3000*MIB)
    def test_windows_commit_headroom_controls_automatic_admission_even_with_free_ram(self):
        value=dict(rssBytes=800*MIB,privateBytes=2400*MIB,childRSSBytes=0,availableBytes=4*1024*MIB,commitAvailableBytes=100*MIB)
        budget=ResourceBudget(sample=lambda:dict(value))
        self.assertTrue(budget.pressured());self.assertEqual(budget.batch_pages(1000,16),1)
        value['commitAvailableBytes']=4*1024*MIB;budget.observe()
        self.assertFalse(budget.pressured());self.assertEqual(budget.batch_pages(1000,16),16)
    def test_native_windows_counter_has_the_correct_64_byte_layout(self):
        import ctypes
        def fill(pointer):
            status=pointer._obj
            self.assertEqual(status.length,64);self.assertEqual(ctypes.sizeof(status),64)
            status.availableCommit=777*MIB;return 1
        with patch('resource_budget.sys.platform','win32'),patch.object(ctypes,'windll',SimpleNamespace(kernel32=SimpleNamespace(GlobalMemoryStatusEx=fill)),create=True):
            self.assertEqual(windows_commit_available(),777*MIB)
    def test_unavailable_os_counters_cannot_fail_translation(self):
        with patch('psutil.Process',side_effect=RuntimeError('counter access denied')),patch('psutil.virtual_memory',return_value=SimpleNamespace(available=4*1024*MIB)):
            self.assertEqual(memory_sample()['rssBytes'],0)
            budget=ResourceBudget();self.assertEqual(budget.batch_pages(1000,16),16)
            with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=100*MIB)):
                budget.observe();self.assertTrue(budget.pressured());self.assertEqual(budget.batch_pages(1000,16),1)


if __name__=='__main__':unittest.main()
