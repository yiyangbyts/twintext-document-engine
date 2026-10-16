"""Observe process-tree memory and admit bounded native work, without changing IL.

Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
Budgets are admission targets, not an OS hard limit or a reason to discard text.
"""
from __future__ import annotations
import sys, threading, time

MIB = 1024 * 1024


def windows_commit_available():
    if sys.platform != 'win32':return None
    try:
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_=[('length',ctypes.c_uint32),('load',ctypes.c_uint32)]+[
                (name,ctypes.c_uint64) for name in ('totalPhysical','availablePhysical',
                'totalCommit','availableCommit','totalVirtual','availableVirtual','extended')]
        value=MemoryStatus();value.length=ctypes.sizeof(value)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
            return value.availableCommit
    except (OSError,AttributeError):pass
    return None


def memory_sample():
    available=0;commit=windows_commit_available()
    try:
        import psutil
        available=psutil.virtual_memory().available
        process = psutil.Process()
        processes = [process, *process.children(recursive=True)]
        rss = private = children = 0
        for item in processes:
            try:
                info = item.memory_info()
                rss += info.rss
                private += getattr(info, 'private', info.rss)
                if item.pid != process.pid:
                    children += info.rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return dict(rssBytes=rss, privateBytes=private, childRSSBytes=children,
                    availableBytes=available,commitAvailableBytes=commit)
    except Exception:
        # Counters can race a departing child or be denied by the OS. Missing
        # telemetry must not turn a valid translation into an engine failure.
        return dict(rssBytes=0, privateBytes=0, childRSSBytes=0, availableBytes=available,commitAvailableBytes=commit)


class ResourceBudget:
    def __init__(self, payload=None, publish=None, sample=memory_sample):
        self.sample = sample
        self.publish = publish
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.stage = 'preparing'
        self.stages = {}
        self.peak = self.private_peak = self.child_peak = 0
        self.pressure_events = 0
        self.thread = None
        initial = sample()
        available = initial['availableBytes']
        requested = (payload or {}).get('memoryBudgetMB')
        if requested is not None and (isinstance(requested, bool) or not isinstance(requested, int) or not 128 <= requested <= 8192):
            raise ValueError('Invalid document memory budget')
        # Automatic admission follows real system headroom. Model/font working
        # sets routinely exceed 1.5 GiB even with several GiB still available;
        # that alone is not memory pressure. A caller may request an explicit
        # process-tree target separately.
        self.limit = requested*MIB if requested else None
        self.reserve = min(512*MIB, max(128*MIB, int(available*.10))) if available else 128*MIB
        self.current = initial
        self.per_page = 48*MIB
        self.batches = self.largest_batch = 0
        self.last_publish = 0
        self.observe()

    def observe(self, stage=None):
        value = self.sample()
        with self.lock:
            if stage:
                self.stage = stage
            self.current = value
            self.peak = max(self.peak, value['rssBytes'])
            self.private_peak = max(self.private_peak, value['privateBytes'])
            self.child_peak = max(self.child_peak, value['childRSSBytes'])
            self.stages[self.stage] = max(self.stages.get(self.stage, 0), value['rssBytes'])
            if self.pressured():
                self.pressure_events += 1
            now = time.monotonic()
            if self.publish and now-self.last_publish >= 1:
                self.last_publish = now
                try:self.publish(self.report())
                except Exception:pass
        return value

    def pressured(self):
        return bool((self.limit is not None and self.usage() > self.limit) or
                    (self.headroom() is not None and self.headroom() < self.reserve))

    def headroom(self):
        values=[]
        if self.current['availableBytes']>0:values.append(self.current['availableBytes'])
        if self.current.get('commitAvailableBytes') is not None:values.append(self.current['commitAvailableBytes'])
        return min(values) if values else None

    def usage(self):
        # Windows private commit can remain high after pages leave the working
        # set. Paging must not make a pressured document appear safe to grow.
        return max(self.current['rssBytes'],self.current['privateBytes'])

    def batch_pages(self, average, ceiling):
        self.observe()
        with self.lock:
            capacities=[]
            if self.limit is not None:capacities.append(max(0,self.limit-self.usage()))
            available=self.headroom()
            if available is not None:capacities.append(max(0,available-self.reserve))
            if not capacities:return ceiling
            capacity=min(capacities)
            unit = max(self.per_page, average*12)
            return max(1, min(ceiling, int(capacity//unit)))

    def completed_batch(self, pages, before):
        self.observe()
        if pages:
            self.batches+=1;self.largest_batch=max(self.largest_batch,pages)
            # Peak RSS includes fixed font-export and preview subprocess costs.
            # Reusing the historical peak as a per-page estimate ratchets every
            # later batch down to one page; keep it diagnostic only.

    def report(self):
        return dict(rssBytes=self.current['rssBytes'], peakRSSBytes=self.peak,
                    peakPrivateBytes=self.private_peak, peakChildRSSBytes=self.child_peak,
                    availableBytes=self.current['availableBytes'], budgetBytes=self.limit,
                    commitAvailableBytes=self.current.get('commitAvailableBytes'),
                    budgetMode='explicit' if self.limit is not None else 'system-headroom',
                    pressureEvents=self.pressure_events,completedBatches=self.batches,largestBatchPages=self.largest_batch,
                    stagePeaks=dict(self.stages))

    def __enter__(self):
        def monitor():
            while not self.stop.wait(.5):
                try:
                    self.observe()
                except Exception:
                    pass  # Telemetry cannot fail a translation.
        self.thread = threading.Thread(target=monitor, name='twintext-memory', daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        if self.thread:
            self.thread.join(1)
        try:self.observe()
        except Exception:pass
