# Engine module API

Runtime entry list: `runtime.json`. Load those scripts in order into an engine-only global/context. They define `TwinTextTypesetModule`, with `run(request)` and `normalize(bytes, check)`. The client does not load algorithm globals into its own namespace. This is code/context separation inside Zotero, not a separate operating-system process or a legal determination about licensing scope.

The context provides WebCrypto, TextEncoder/TextDecoder, ChromeWorker, setTimeout/clearTimeout, and `TwinTextTypesetEnvironment`:

- `resourceURI`: URI prefix of this engine directory; in the XPI it is `chrome://twintext/content/engines/typeset/`.
- `io`: IOUtils read/write/readJSON/writeJSON/makeDirectory operations; write supports tmpPath for atomic replacement.
- `path`: PathUtils join/parent/filename.
- `version`: Zotero version for layout-cache invalidation.
- `machine()`: `{cores,memoryBytes}` for worker scheduling.
- `boundedRequest(work,{timeout,timeoutError})`: timed promise execution for reader rasterization.
- `logError(error)`: optional runtime diagnostics.

`run` takes input/output file paths, readerWindow (the source PDF iframe with PDFViewerApplication and Zotero PDF.js), pageCount, options, translate(text), optional AbortSignal and onEvent(event). Input and output must differ. Options include inclusive zero-based first/last, sourceLanguage, targetLanguage, fontFamily, translationConcurrency and backgroundExport. The module has no account, license receipt, official API key or paid-feature check. A host supplies translated strings and decides which options its product exposes.

Events are status, progress, preview (file/sha256), warning. The result contains file/sha256/stats/failedPages/unsupportedPages/translatedFragments/previewUpdates/documentScale/pageCount. Failed paragraphs retain the source and produce a `.partial.pdf` instead of a complete-result cache file. Cancellation closes engine-owned workers and releases the temporary reader document. The invoking host must cancel its translation requests as well.

`normalize(bytes,check)` provides the previous password-free RC4/AES-128 PDF normalization, used by PDF export. It does not remove unknown passwords. The source PDF is not overwritten. Engine internals stay in this module; presentation, authorization and service selection belong to the caller.
