"""Reuse the verified layout model within one local service process."""
from __future__ import annotations
import os,threading

_lock=threading.Lock()
_model=None
_asset_key=None

def _load():
    from babeldoc.docvision.doclayout import DocLayoutModel
    return DocLayoutModel.load_onnx()

def layout_model():
    # Service startup warms the model. Translation tasks and page recovery
    # reuse that same instance and its upstream inference lock. An asset-root
    # change must never borrow a model loaded from a different environment.
    global _model,_asset_key
    key=os.environ.get('TWINTEXT_BABEL_ASSETS','')
    with _lock:
        if _model is None or _asset_key!=key:
            model=_load()
            _model=model;_asset_key=key
        return _model


def monitor_type(base):
    class NativeProgressMonitor(base):
        def on_finish(self):
            # Upstream sets cancel_event even after successful synchronous
            # completion. That signal belongs to the user's whole job, so
            # normal part completion must not cancel the next native part.
            if self.disable or self.parent_monitor and self.parent_monitor.disable:return
            if self.cancel_event is not None and not self.cancel_event.is_set():
                if self.finish_event and self.loop:self.loop.call_soon_threadsafe(self.finish_event.set)
                return
            return super().on_finish()
    return NativeProgressMonitor
