# Third-Party Notices

Third-party software and resources retain their original copyrights, licenses and applicable warranty disclaimers. Original notices and license texts are preserved in the linked materials and distributed packages. Component names identify technical sources and do not imply endorsement.

| Component | Version / license |
| --- | --- |
| BabelDOC | 0.6.4; AGPL-3.0, with separately licensed vendored code |
| PyMuPDF / MuPDF | 1.28.2; AGPL editions used in this runtime |
| Levenshtein | 0.27.5; GPL-2.0-or-later |
| certifi, orjson, tqdm and other runtime dependencies | Applicable MPL, MIT, Apache, BSD and other licenses; see the platform inventory |
| PP-DocLayoutV2 model and conversion resources | Apache-2.0 as stated by the model cards; pinned conversion revision 358310b4f64b95f9fefc372ad899356e4111f376 |
| ONNX Runtime Web | 1.30.0; MIT and accompanying notices |
| Python | 3.12.11; PSF and incorporated-software licenses |
| uv | 0.8.22; MIT or Apache-2.0 |
| Fonts, models, CMaps and tokenizer resources | Applicable OFL, NAVER font, Apache, BSD, MIT and resource licenses; see the inventory |

The [platform and resource inventory](licenses/runtime/inventory.json) identifies exact versions, original copyright notices, license files and checksums. [Resource provenance](licenses/upstream/sources.json) identifies model and font notice sources. Applicable components depend on the enabled features and installed platform. Standard parsing uses PDF.js supplied by Zotero; the plugin does not redistribute PDF.js. Windows payloads also retain the Microsoft runtime notices and applicable redistribution terms.

See [AGPL](licenses/AGPL-3.0.txt), [Apache-2.0](licenses/APACHE-2.0.txt), [uv licenses](licenses/uv/), and [ONNX Runtime Web notices](licenses/frontend/). Other original texts are indexed by the inventory.

TwinText modifications are described in [engine/NOTICE.md](engine/NOTICE.md). [Source releases](https://github.com/yiyangbyts/twintext-document-engine/releases) provide the versioned engine source and pinned BabelDOC, PyMuPDF, MuPDF and Levenshtein upstream source archives. Build and installation instructions are in [engine/README.md](engine/README.md). Use, modification and redistribution remain subject to the applicable licenses.
