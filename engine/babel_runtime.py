"""Reuse the verified layout model within one local service process."""
from __future__ import annotations
import os,threading

_lock=threading.Lock()
_model=None
_asset_key=None

def _load():
    from babeldoc.docvision import doclayout
    providers=doclayout.onnxruntime.get_available_providers()
    if doclayout.os_name=='Darwin' and any(p.lower().startswith('coreml') for p in providers):
        # Keep upstream's static-shape rewrite and CoreML acceleration intact.
        return doclayout.DocLayoutModel.load_onnx()
    return _load_cpu(doclayout,providers)

def _load_cpu(module,providers):
    # ORT accepts a filename. The upstream CPU constructor also holds a full
    # ONNX protobuf and serialized bytes during session creation. Neither copy
    # is needed: metadata is available from the identical loaded session.
    import ast
    model=module.OnnxModel.__new__(module.OnnxModel)
    model.model_path=module.get_doclayout_onnx_model_path()
    model.model=module.onnxruntime.InferenceSession(str(model.model_path),
        providers=[p for p in providers if p.lower().startswith('cpu')])
    metadata=model.model.get_modelmeta().custom_metadata_map
    model._stride=ast.literal_eval(metadata['stride'])
    model._names=ast.literal_eval(metadata['names'])
    model.lock=threading.Lock()
    return model

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
