# Modification Notice

Based on [BabelDOC 0.6.4](https://github.com/funstory-ai/BabelDOC/tree/v0.6.4), licensed under AGPL-3.0. Vendored pdfminer retains its MIT license. PyMuPDF/MuPDF and other dependencies retain their applicable licenses and original copyright notices; see the platform inventory and THIRD-PARTY-NOTICES.md.

Copyright (C) 2026 TwinText, for adapter modifications through 2026-10-08: native PDF reconstruction; runtime and temporary workspace compatibility; reference, list and contents preservation; rotated-page geometry; paragraph previews and typography reflow; ignored/preserved regions; translation retries, cancellation, page recovery and artifact lifetime; file-backed PDF transport, bounded native batches, resumable part checkpoints separation of part completion from user cancellation; persistent bounded IL checkpoints, visible-page-first local typography reflow and superseded-job cancellation. Additional changes cover sideways content without PDF rotation metadata, original-frame restoration, cached raster typography previews, unique preview streams and ASCII-safe installation progress. These changes include subclasses and runtime patches within the Python process.

Version 2.0.15 restores PDF parsing, translation and native PDF presentation to the 2.0.11 implementation. The subsequent structured reading layer and unresolved-fragment relay extensions are removed. Native typography reflow and bounded batch recovery remain available.

Version 2.0.13 adds measured asset source selection, bounded parallel downloads, range resume, slow-source failover and pinned digest verification.

TwinText-authored engine code, the runtime probe and source builder are licensed under AGPL-3.0-only. The standalone CLI and HTTP interface run the same document policies. Source and build materials are available at https://github.com/yiyangbyts/twintext-document-engine/releases without payment or activation. Original license texts and notices remain included.
