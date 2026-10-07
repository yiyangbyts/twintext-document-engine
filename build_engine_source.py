"""Build the independently licensed engine source with an explicit allowlist.

Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
This archive is engineering source delivery, not distribution-review approval.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parent.parent
SOURCE_REPOSITORY = 'https://github.com/yiyangbyts/twintext-document-engine'
PUBLIC_ENGINE_FILES = frozenset('''
API.md LICENSE.txt NOTICE.md README.md adapters.py asset_paths.py babel_adapter.py
babel_compat.py babel_runtime.py backend.json cli.py constraints-linux-arm64.txt
constraints-linux-x64.txt constraints-mac-arm64.txt constraints-mac-x64.txt
constraints-win-x64.txt document_options.py document_preview.py download_model.py
fetch_sources.py fixtures/README.md fixtures/structure-rows.json ignored_regions.py
install.py model-manifest.json native_artifacts.py output_safety.py page_geometry.py
preserved_regions.py reference_layout.py requirements.txt service.py structure_plan.py
test_babel_compat.py test_babel_runtime.py test_document_options.py test_document_preview.py
test_download_model.py test_native_artifacts.py test_native_service.py test_output_safety.py
test_page_geometry.py test_page_recovery.py test_reference_layout.py test_service_boundary.py
test_structure_plan.py test_translation_provider.py temporary_workspace.py translation_provider.py upstream-sources.json
'''.split())


def source_delivery(version):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid source version')
    release = f'{SOURCE_REPOSITORY}/releases/tag/v{version}'
    return dict(schema=1, version=version, repository=SOURCE_REPOSITORY, release=release,
                archive=f'{SOURCE_REPOSITORY}/releases/download/v{version}/twintext-engine-source-{version}.zip')


def read_public(root, relative):
    path = root / relative
    cursor = root
    for part in Path(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(f'Symlink in public source: {relative}')
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f'Missing or unsafe public source: {relative}')
    return path.read_bytes()


def source_files(root=ROOT):
    files = {}
    engine = root / 'engines/babeldoc'
    unknown = {p.relative_to(engine).as_posix() for p in engine.rglob('*.py')
               if not any(part in ('__pycache__', 'assets', 'model', '.venv', 'upstream-source') for part in p.relative_to(engine).parts)
               and p.relative_to(engine).as_posix() not in PUBLIC_ENGINE_FILES}
    if unknown:
        raise ValueError('Review new engine source before publishing: ' + ', '.join(sorted(unknown)))
    for name in sorted(PUBLIC_ENGINE_FILES):
        files['engine/' + name] = read_public(root, 'engines/babeldoc/' + name)
    inventory = json.loads(read_public(root, 'licenses/runtime/inventory.json'))
    notices = {'licenses/AGPL-3.0.txt', 'licenses/APACHE-2.0.txt', 'licenses/runtime/inventory.json',
               'licenses/uv/LICENSE-MIT', 'licenses/uv/LICENSE-APACHE', 'licenses/upstream/sources.json'}
    notices.update(item['path'] for item in json.loads(read_public(root, 'licenses/upstream/sources.json')))
    for platform in inventory['platforms'].values():
        notices.update(item['path'] for item in platform['runtimeNotices'])
        for package in platform['packages']:
            notices.update(item['path'] for item in package['noticeFiles'])
    notices.update(asset['attribution']['path'] for asset in inventory['assets'] if asset.get('attribution'))
    for name in sorted(notices):
        if not name.startswith('licenses/') or '..' in Path(name).parts:
            raise ValueError('Unsafe license path')
        files[name] = read_public(root, name)
    for name, target in [('THIRD-PARTY-NOTICES.md', 'THIRD-PARTY-NOTICES.md'),
                         ('docs/PUBLIC-DOCUMENTATION.zh-CN.md', 'DOCUMENTATION.zh-CN.md'),
                         ('vendor/onnxruntime-web-1.30.0/LICENSE-MIT', 'licenses/frontend/ONNX-Runtime-Web-LICENSE-MIT'),
                         ('vendor/onnxruntime-web-1.30.0/NOTICE.md', 'licenses/frontend/ONNX-Runtime-Web-NOTICE.md'),
                         ('engines/installer/runtime_probe.py', 'runtime_probe.py'),
                         ('scripts/build_engine_source.py', 'build_engine_source.py')]:
        files[target] = read_public(root, name)
    # The portable layout can reproduce the archive without client files.
    version = json.loads((root / 'package.json').read_text())['version']
    files['engine/source-distribution.json'] = (json.dumps(source_delivery(version), indent=2) + '\n').encode()
    files['LICENSE.txt'] = files['engine/LICENSE.txt']
    files['.gitignore'] = b'__pycache__/\n*.pyc\n.venv/\nassets/\nmodel/\nupstream-source/\n.env\n*.pdf\n*.part\n'
    files['README.md'] = f'''# TwinText Document Engine

Source snapshot for TwinText {version}. This repository publishes the independently
runnable document engine, its modifications, public HTTP/CLI interface, tests,
dependency constraints and necessary installation/source-building materials.

中文使用说明、版权与许可及源码下载：[GitHub 文档（中文）](DOCUMENTATION.zh-CN.md)。

The engine's TwinText-authored code, runtime probe and source builder are provided
under AGPL-3.0-only. Third-party code and resources retain their original licenses.
See LICENSE.txt, engine/NOTICE.md and licenses/runtime/inventory.json.

Installation, translation and testing: [engine/README.md](engine/README.md).
API: [engine/API.md](engine/API.md).
Versioned source archives and pinned upstream sources: [{version} release]({source_delivery(version)['release']}).
Download the engine source ZIP and twintext-upstream-sources.zip from that release;
the latter includes BabelDOC, PyMuPDF, MuPDF and Levenshtein sources with hashes.
No TwinText account or activation is required to run the independent engine.

This snapshot is exported using a reviewed file allowlist. It does not contain
the proprietary Zotero client, account/activation server, website, credentials,
customer documents or the private product repository's Git history.
Publishing this engineering snapshot does not determine the full legal scope
of a combined work or certify commercial distribution of every runtime payload.
'''.encode()
    files['SOURCE-MANIFEST.json'] = (json.dumps(dict(schema=1, version=version,
        engine='twintext-document-engine', protocol=5, license='AGPL-3.0-only',
        distributionReview='pending', dependencies='licenses/runtime/inventory.json', sourceDelivery=source_delivery(version),
        files={name: hashlib.sha256(data).hexdigest() for name, data in files.items()}), indent=2) + '\n').encode()
    return files


def archive_bytes(root=ROOT):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in source_files(root).items():
            item = zipfile.ZipInfo(name, date_time=(2026, 10, 7, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            archive.writestr(item, data)
    return stream.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Portable archives contain the source files directly under engine/.
    if not (ROOT / 'package.json').is_file():
        base = Path(__file__).resolve().parent
        manifest = json.loads((base / 'SOURCE-MANIFEST.json').read_text())
        files = {name: (base / name).read_bytes() for name in manifest['files']}
        # Recipients may modify the engine and regenerate its preferred source.
        for path in sorted((base / 'engine').rglob('*')):
            relative = path.relative_to(base)
            if path.is_file() and not any(p in ('__pycache__','assets','model','.venv','upstream-source') for p in relative.parts) and path.suffix in ('.py','.txt','.md','.json'):
                files[relative.as_posix()] = path.read_bytes()
        manifest['files'] = {name: hashlib.sha256(data).hexdigest() for name,data in files.items()}
        files['SOURCE-MANIFEST.json'] = (json.dumps(manifest,indent=2)+'\n').encode()
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(args.output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(archive_bytes())
    print(f'Engine source: {args.output} ({args.output.stat().st_size} bytes)')


if __name__ == '__main__':
    main()
