# Engine copyright and source notices

The PDF parsing, paragraph analysis, formula protection, font handling and typesetting include code ported from **BabelDOC 0.6.4**, copyright its authors, plus TwinText modifications, under **AGPL-3.0-only**. Notices remain in core/*.js. See LICENSE.txt. This repository includes the editable public engine, Zotero adapters, generation tools, tests, fonts, licenses and reconstruction instructions for the external layout model. The change in 2.2.04 restores the Zotero runtime and removes the standalone Node process.

- BabelDOC: https://github.com/funstory-ai/BabelDOC/tree/v0.6.4
- ONNX Runtime Web 1.30.0, Microsoft: MIT, unchanged; vendor/ort/LICENSE-MIT and NOTICE.md. https://github.com/microsoft/onnxruntime
- DocLayout-YOLO DocStructBench ONNX: model card declares Apache-2.0; licenses/upstream/DocLayout-ONNX-MODEL-CARD.md and licenses/APACHE-2.0.txt. Per-channel uint8 quantization: tools/quantize_layout_model.py, pinned hashes in ASSETS.json. Original-weight permission scope remains subject to distribution review. https://huggingface.co/wybxc/DocLayout-YOLO-DocStructBench-onnx
- Source Han, Noto and LXGW output fonts: OFL-1.1, unchanged; licenses/typeset-fonts.md and licenses/upstream/.
- Adobe glyph/CMap data: notices retained in licenses/upstream/Adobe-CMap-LICENSE.txt and core/font-data.js.

PDF.js, Canvas, JavaScript and workers are provided by Zotero/Gecko. No independent PDF.js distribution, Canvas native binding or Node executable is included. Third-party rights and previous license grants are unaffected. Code modularization does not determine whether a host and engine form one covered work; that remains a separate distribution review.

On 2026-11-06, TwinText created the 2.2.17-public.1 baseline using the pre-refinement paragraph, translation and typesetting rules.
