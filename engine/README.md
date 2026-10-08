# TwinText Document Engine

Copyright (C) 2026 TwinText. The engine's first-party source is licensed under
AGPL-3.0-only; see LICENSE.txt. The bundled runtime probe and engine source builder are covered by the same license. Upstream software retains its original licenses.
This is a standalone BabelDOC 0.6.4 adaptation with reference/list/contents
preservation, rotated-page handling, paragraph previews, reflow and recovery.
The read-only structured-page API lets a client change reading typography
without repeating translation or rewriting the native PDF. Original formula
graphics and fixed obstacles keep math and figures distinct from flowing prose.
Explicit unresolved-fragment metadata prevents partial answers being mistaken
for completed pages while allowing other paragraphs to continue.

## Install and run

Use CPython 3.12 and the constraint file matching the interpreter ABI. Windows
ARM64 currently uses x64 Python under Windows emulation and constraints-win-x64.txt.
Use a dedicated virtual environment; do not install into another application's environment.

```sh
python -m venv .venv
# macOS/Linux: .venv/bin/python; Windows: .venv/Scripts/python.exe
.venv/bin/python -m pip install -r requirements.txt -c constraints-mac-arm64.txt
.venv/bin/python download_model.py
```

Download_model.py verifies all fonts/models using model-manifest.json. Existing
verified assets can instead be supplied with --assets. For offline installation,
use the corresponding platform payload shipped with the TwinText full package;
its interpreter, dependencies and assets are reusable without Zotero running.

```sh
export DOCUMENT_API_KEY='your provider key'
.venv/bin/python cli.py input.pdf --output translated.pdf \
  --assets ./assets --api-base https://your-provider.example/v1 \
  --translation-model your-model --source en --target zh-CN --previews ./previews
.venv/bin/python cli.py --serve --assets ./assets \
  --api-base http://127.0.0.1:11434/v1 --translation-model your-local-model
```

PowerShell: set `$env:DOCUMENT_API_KEY` and use `.venv\Scripts\python.exe`.
A local compatible provider may work without a key. Credentials are read from
the environment and are never included in job JSON, health or source archives.
No TwinText license or account is required by this engine. Omitting the provider
in --serve mode allows any native HTTP client to answer plain-text requests via
/v1/jobs/{id}/reply. See API.md. Service.py retains automatic client startup.

Run regressions with `python -m unittest discover -s . -p 'test_*.py'`.
Structure fixtures retain source geometry only; tests never call a client parser.

## Source and dependencies

Versioned source archives are freely available at
https://github.com/yiyangbyts/twintext-document-engine/releases. The installed
source-distribution.json identifies the exact release and archive for that version;
/v1/source redirects there without a TwinText account or activation.

The source archive includes the engine, interface, dependency constraints,
asset hashes, runtime probe, source builder, tests and referenced license materials.

Pinned core upstream sources:
- https://github.com/funstory-ai/BabelDOC/tree/v0.6.4
- https://github.com/pymupdf/PyMuPDF/tree/1.28.2
- https://github.com/rapidfuzz/Levenshtein/tree/v0.27.5
- https://mupdf.com/downloads/archive/mupdf-1.28.2-source.tar.gz

The release also provides twintext-upstream-sources.zip containing these pinned
upstream source distributions. `fetch_sources.py` can download them directly,
without executing or extracting them, verifying upstream-sources.json sizes and
SHA-256 digests. Checksums accompany the GitHub release assets.

The exact dependency and asset inventory, with original license and copyright
materials, is in licenses/runtime/inventory.json in the source package.
