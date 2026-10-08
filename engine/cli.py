"""Translate a PDF or serve the public loopback API without a Zotero client.

Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import threading


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', nargs='?', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--port', type=int, default=27194)
    parser.add_argument('--assets', type=Path, help='Verified assets directory, including fonts and models')
    parser.add_argument('--api-base', default=os.environ.get('DOCUMENT_API_BASE', ''))
    parser.add_argument('--translation-model', default=os.environ.get('DOCUMENT_TRANSLATION_MODEL', ''))
    parser.add_argument('--source', default='en')
    parser.add_argument('--target', default='zh-CN')
    parser.add_argument('--pages')
    parser.add_argument('--concurrency', type=int, default=3)
    parser.add_argument('--ignore-references', action='store_true')
    parser.add_argument('--ignore-headers-footers', action='store_true')
    parser.add_argument('--previews', type=Path, help='Write successive PNG/PDF preview frames atomically to this directory')
    args = parser.parse_args(argv)
    if not args.serve and (args.input is None or args.output is None):
        parser.error('Specify an input PDF and --output, or use --serve')
    if args.serve and (args.input or args.output):
        parser.error('--serve does not accept input/output paths')
    if args.assets:
        os.environ['TWINTEXT_BABEL_ASSETS'] = str(args.assets.resolve())
    if bool(args.api_base) != bool(args.translation_model) or (not args.serve and not args.api_base):
        parser.error('Specify both --api-base and --translation-model; use DOCUMENT_API_KEY for credentials')
    from asset_paths import configure
    configure()
    from translation_provider import HTTPTranslator
    cancel = threading.Event()
    def translator(payload, event):
        return HTTPTranslator(args.api_base, args.translation_model, os.environ.get('DOCUMENT_API_KEY', ''),
                              payload.get('sourceLanguage', args.source), payload.get('targetLanguage', args.target), event)
    if args.serve:
        if not 1024 < args.port < 65536:
            parser.error('Service port must be between 1025 and 65535')
        from http.server import ThreadingHTTPServer
        from service import Jobs, handler
        config = json.loads(Path(__file__).with_name('backend.json').read_text())
        config['port'] = args.port
        jobs = Jobs('babeldoc', '.', translator_factory=translator if args.api_base else None)
        jobs.load()
        server = ThreadingHTTPServer(('127.0.0.1', args.port), handler(jobs, config))
        try:
            print(json.dumps(dict(type='ready', endpoint=f'http://127.0.0.1:{args.port}', protocol=5)), flush=True)
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            with jobs.lock:
                for job in jobs.jobs.values():
                    job['cancelled'] = True
                    job['cancel_event'].set()
            server.server_close()
            jobs.pool.shutdown(wait=True, cancel_futures=True)
        return 0
    def progress(**event):
        print(json.dumps({k: v for k, v in event.items() if k in ('type', 'stage', 'overall_progress', 'stage_current', 'stage_total')}, ensure_ascii=False), flush=True)
    def preview(event):
        if event.get('type') in ('preview-warning', 'preview-status'):
            print(json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True)
        if not args.previews or event.get('type') != 'native-page-preview':
            return
        import base64
        try:
            args.previews.mkdir(parents=True, exist_ok=True)
            format = 'png' if event.get('png') else 'pdf'
            destination = args.previews / f"page-{event['pageIndex']+1}.{format}"
            temporary = destination.with_suffix('.tmp')
            temporary.write_bytes(base64.b64decode(event[format], validate=True))
            temporary.replace(destination)
        except (OSError, ValueError, KeyError) as error:
            print(json.dumps(dict(type='preview-warning', message=str(error))), file=sys.stderr, flush=True)
    try:
        from service import pdf_input
        pdf = pdf_input(dict(sourceFile=str(args.input.resolve())))
        payload = dict(nativeExport=True, documentExport=True, pages=args.pages, outputFile=str(args.output.resolve()),
                       sourceLanguage=args.source, targetLanguage=args.target, concurrency=args.concurrency,
                       documentOptions=dict(ignoreReferences=args.ignore_references, ignoreHeadersFooters=args.ignore_headers_footers))
        from babel_adapter import run
        from temporary_workspace import temporary_workspace
        with temporary_workspace(prefix='document-engine-') as temporary:
            _, output = run(pdf, Path(temporary), payload, translator(payload, cancel), progress, cancel,
                            on_preview=preview if args.previews else None)
        if not output:
            raise RuntimeError('The document engine produced no PDF')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(args.output.name + '.tmp')
        if not isinstance(output, Path):
            temporary.write_bytes(output)
            temporary.replace(args.output)
        print(json.dumps(dict(type='complete', output=str(args.output.resolve())), ensure_ascii=False), flush=True)
        return 0
    except KeyboardInterrupt:
        cancel.set()
        print(json.dumps(dict(type='interrupted', reason='cancelled')), file=sys.stderr)
        return 130
    except Exception as error:
        # Provider errors deliberately exclude credentials and raw HTTP bodies.
        print(json.dumps(dict(type='interrupted', reason=str(error)), ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
