# TwinText 全文精排引擎 · 公开基线 2.2.17-public.1

这是基于 BabelDOC 0.6.4 的独立 Zotero 排版引擎。公开基线使用基础段落、公式与字号排版规则。TwinText 插件的发行版本和各自的对应源码单独管理。

引擎使用宿主提供的纯文本翻译回调，支持选页、翻译预览、旋转页面文字和 PDF 输出。运行方式见[引擎文档](typeset/README.md)，宿主接口见[API](typeset/API.md)。代码按 [AGPL-3.0-only](typeset/LICENSE.txt) 提供，字体和运行库按[各自许可](typeset/NOTICE.md)分发。

## 重建公开基线

DocLayout 模型需从上游取得。仓库提供量化工具、模型卡和预期 SHA-256。

1. 从[原 ONNX 模型仓库](https://huggingface.co/wybxc/DocLayout-YOLO-DocStructBench-onnx)按上游许可取得模型。将原始 ONNX 放到 `typeset/assets/models/doclayout_yolo_docstructbench_imgsz1024.onnx`（先创建目录），核对量化脚本中的 `SOURCE_SHA256`。
2. 在 `typeset/` 目录按 [量化工具](typeset/tools/quantize_layout_model.py) 指定的依赖运行 `python3 tools/quantize_layout_model.py`。用 [ASSETS.json](typeset/ASSETS.json) 核对输出后，将原始 ONNX 移出 `assets/`，仅保留量化后的模型。
3. 运行 `python3 build-source.py --output-dir dist`。可用 [SOURCE-MANIFEST.json](typeset/SOURCE-MANIFEST.json) 逐文件校验。
