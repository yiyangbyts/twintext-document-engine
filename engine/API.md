# Document Engine API, protocol 5

The engine binds only 127.0.0.1. It accepts native loopback JSON HTTP clients;
web origins are blocked except the explicit Zotero application origin. Clients
never supply PDF glyph/IL objects or reference/layout analysis implementations.
Translation relay requests contain opaque request IDs, plain text, a zero-based
pageIndex and a paragraph kind. No parser implementation is supplied by clients.
The current concurrency/format/view controls remain available for incremental use.

- `GET /health`: protocol, engine identifier, capabilities and activity. Require
  protocol 5 and `engine-structure-2.0.5-v1` before starting a new client session.
- `POST /v1/jobs`: create a job. `sourceFile` is a local PDF path;
  use `outputFile` for the resulting PDF and `cacheKey` for resumable batches.
  `pdf` (base64) remains available for small in-memory clients;
  `nativeExport: true`, `documentExport: true`, optional `pages: "1-12"`,
  `sourceLanguage`, `targetLanguage`, `currentPage` (zero-based), `concurrency`.
  `documentOptions` contains fontScale/lineHeightScale percentages, fontFamily
  (serif/sans), ignoreReferences and ignoreHeadersFooters booleans. Optional
  clientJobId is 32 hexadecimal characters; exact retries are idempotent.
- `GET /v1/jobs/{id}?after={cursor}&metadata=1`: state queued/running/complete/error,
  progress, timing, requests, previews and warnings. Preview PNG/PDF frames contain
  translated paragraphs as they become ready, before full-document completion.
  Polling and preview display must not block outstanding translation replies.
- `POST /v1/jobs/{id}/reply`: `{id, translation, retained}`. Translation must be a string.
  Optional retained marks unresolved prose, including partially translated answers;
  false explicitly accepts literal identifiers or names. Results expose their
  actual incompletePages separately from failedPages. Legacy replies remain accepted.
  Preserve BabelDOC's `<bN>` and `</bN>` placeholders. Idempotent exact retries are
  accepted. No structure analysis operations exist in protocol 5.
- `POST /v1/jobs/{id}/view`: `{pageIndex}` to prioritize the visible page.
- `POST /v1/jobs/{id}/format`: `{documentOptions}` for preview typography.
- `POST /v1/jobs/{id}/cancel`: cancel and stop awaiting translation replies.
- `GET /v1/jobs/{id}/result`: complete PDF, pageCount, pipeline, optional artifactId
  and exportPages. File-backed results return `pdfFile`, `size`, `sha256` and
  `failedPages` without transferring the full PDF in JSON. Require capability
  `bounded-native-files-2.0.9` for this mode. Optional `batchPages` (1–16) caps
  native part size; available memory and PDF size can reduce it further. Preview warnings do not imply that the final PDF failed.
- `POST /v1/jobs/{id}/release`: release completed job data.
- `GET /v1/source`: redirect to the exact version's publicly available GitHub
  source archive, using source-distribution.json. Older installations with a local
  engine-source.zip still return that archive. Unpackaged development checkouts
  return 404 with the source release location when no version metadata is present.

Reflow/extract/comparison/page-recovery jobs use the same queue with reflowNative,
extractNative, comparisonNative or assembleNative respectively. The opaque
artifactId is process-local and expires; it is not a serialized BabelDOC document.
Final input/output uses ordinary PDF bytes; preview frames use PNG or PDF bytes. Exported text is a neutral
page/paragraph collection; internal parser classes are never part of the API.

In --serve mode with an independently configured translator, requests are
translated inside the engine and the requests list stays empty. All layout and
structure policies are identical in relay, standalone server and CLI modes.

Error snapshots distinguish translator failures, document-page exceptions,
resource/environment failures and transport failures. A client may recover only
failed document pages with the same engine. Never mistake an unchanged source
PDF or a failed provider request for a completed translation.

Large documents use the same native pipeline in bounded parts (at most 16 pages),
then assemble selected pages in their original positions. Completed parts are
checksummed on disk and reused on restart. Content failures can be narrowed to
a single page; original content and a failure warning remain visible. Credentials,
quota, missing environment and disk failures remain explicit job errors.

Completed file-backed documents retain checksummed, gzip-compressed IL checkpoints
of at most 16 pages. `artifactFile` identifies their manifest for `reflowNative`;
`outputFile` keeps the resulting PDF out of progress JSON. A focused-page preview
precedes the complete reflow. Superseded jobs can be cancelled without new model
requests. Checkpoints use a fixed IL dataclass allowlist, never pickle or executable
client data, and remain usable after the engine restarts.

`POST /v1/jobs` with `readingNative: true`, `artifactFile` (or an unexpired
artifactId) and currentPage returns a read-only structured page. It includes
profile `native-reading-2.0.12-v1`, dimensions, rotation, a PNG background,
paragraph rectangles, text runs, original formula graphics and fixed obstacles.
Only the requested checkpoint part is loaded. This operation never translates
or changes the native PDF. Derived disk caches are bounded to 64 MiB per
checkpoint directory. Release completed reading jobs using the usual endpoint.
