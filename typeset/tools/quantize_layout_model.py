"""Derive the typeset engine's bundled layout model from the DocLayout-YOLO file BabelDOC 0.6.4 pins.

Every Conv weight of more than 16 values is stored per output channel as uint8 and turned back into float32 by a DequantizeLinear
node; the dfl head, the biases and the small tensors stay float32. Graph, inputs, outputs and classes are unchanged, and the file
records what was done in its metadata. 75.3 MB becomes 19.3 MB; docs/qa/typeset-engine-revision32-u8-20261102.md compares it with the
original weights in Zotero.

The output is the same file on every run with onnx 1.23.1 and numpy 2.5.3 (.dev/venv-engine):
  .dev/venv-engine/bin/python scripts/quantize_layout_model.py
"""
import hashlib
from pathlib import Path

import numpy as np
import onnx
from onnx import helper, numpy_helper

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "models" / "doclayout_yolo_docstructbench_imgsz1024.onnx"
SOURCE_SHA256 = "fece9af02f618b603ff7921ccec6861d13e7e1f9830e091dfb7e8ad9311e5b21"
TARGET = SOURCE.with_name("doclayout_yolo_docstructbench_imgsz1024_u8.onnx")

assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA256, "not the file BabelDOC 0.6.4 pins"
model = onnx.load(SOURCE)
graph = model.graph
conv_weights = {node.input[1] for node in graph.node if node.op_type == "Conv"}
initializers, dequantize = [], []
for tensor in graph.initializer:
    values = numpy_helper.to_array(tensor)
    if tensor.name not in conv_weights or values.ndim != 4 or values.size <= 16 or "dfl" in tensor.name:
        initializers.append(tensor)
        continue
    name, channels = tensor.name, values.shape[0]
    flat = values.reshape(channels, -1)
    low, high = np.minimum(flat.min(1), 0), np.maximum(flat.max(1), 0)
    scale = np.maximum((high - low) / 255, 1e-12).astype(np.float32)
    zero = np.clip(np.round(-low / scale), 0, 255).astype(np.uint8)
    shape = (channels, 1, 1, 1)
    quantized = np.clip(np.round(values / scale.reshape(shape) + zero.reshape(shape)), 0, 255).astype(np.uint8)
    initializers += [numpy_helper.from_array(quantized, name + "_q"), numpy_helper.from_array(scale, name + "_s"), numpy_helper.from_array(zero, name + "_z")]
    dequantize.append(helper.make_node("DequantizeLinear", [name + "_q", name + "_s", name + "_z"], [name], axis=0))
del graph.initializer[:]
graph.initializer.extend(initializers)
nodes = dequantize + list(graph.node)
del graph.node[:]
graph.node.extend(nodes)
note = model.metadata_props.add()
note.key = "twintext_modification"
note.value = (f"TwinText stored the {len(dequantize)} Conv weights of more than 16 values per output channel as uint8, restored by DequantizeLinear; "
              f"everything else is unchanged. Source: {SOURCE.name}, sha256 {SOURCE_SHA256}.")
onnx.checker.check_model(model)
onnx.save(model, TARGET)
print(TARGET.relative_to(ROOT), round(TARGET.stat().st_size / 1e6, 1), "MB", hashlib.sha256(TARGET.read_bytes()).hexdigest())
