# TwinText Document Engine

TwinText adapts BabelDOC for PDF translation while preserving document structure. It addresses common problems with mixed text and formulas, merged reference entries, numbered lists, tables of contents and rotated pages. Paragraph previews let readers see available translations while processing continues; translation retries, bounded document batches and disk checkpoints support long documents and interrupted jobs.

Completed PDFs can provide bounded read-only page rasters for slow viewer pages. The rasters come from the final PDF, without text reconstruction, and the native viewer replaces them when its clear rendering is ready. Rendering is serial and isolated from model inference; the original PDF remains authoritative for search and export.

The engine runs independently through a CLI or HTTP interface and supports compatible translation providers. See [build and run instructions](engine/README.md) and the [API](engine/API.md).

Copyright (C) 2026 TwinText, for TwinText modifications. This code is available under [AGPL-3.0-only](LICENSE.txt); you may use, modify and redistribute it under that license. Third-party components retain their original copyrights and licenses. The software is provided without warranty except as required by law or separately agreed.

[Third-party notices](THIRD-PARTY-NOTICES.md) identify the components and license materials. [Modification notices](engine/NOTICE.md) describe the changes and their date.

[Source releases](https://github.com/yiyangbyts/twintext-document-engine/releases) provide versioned engine source, pinned core upstream sources and checksums, without payment or activation. Select the release matching the installed version; `source-distribution.json` records its exact location.

Selected pages are checked for a usable body text layer. The bundled English OCR data is used only for deficient pages, one page at a time, with disk caching. Scans receive invisible OCR text while their source images and vector graphics remain intact. For legacy bitmap fonts with an unusable text encoding, the original native page is kept as an opaque PDF Form and a separate OCR layer supplies readable text to the parser. Original font programs and vector/image content remain intact; formulas use native source crops. A selection with no body text sent for translation produces a diagnostic instead of a false success. Non-English OCR is not currently bundled.
