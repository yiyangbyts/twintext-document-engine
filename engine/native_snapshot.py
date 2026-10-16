"""Page records and content-addressed PDF resources for pre-typesetting IL.

Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
Only fixed IL data types are decoded. Existing JSON/gzip snapshots stay readable.
"""
from __future__ import annotations
import base64, dataclasses, gzip, json, shutil
from pathlib import Path


def typed_tokens(value):
    from native_reflow import classes
    if dataclasses.is_dataclass(value):
        name = type(value).__name__
        if name not in classes():
            raise ValueError('Unsupported reflow class')
        yield '{"type":'+json.dumps(name)+',"fields":{'
        for i, field in enumerate(dataclasses.fields(value)):
            if i: yield ','
            yield json.dumps(field.name)+':'
            yield from typed_tokens(getattr(value, field.name))
        yield '}}'
    elif isinstance(value, bytes):
        yield '{"bytes":"'
        for start in range(0, len(value), 49152):
            yield base64.b64encode(value[start:start+49152]).decode('ascii')
        yield '"}'
    elif isinstance(value, dict):
        yield '{"dict":['
        for i, (key, item) in enumerate(value.items()):
            if i: yield ','
            yield '['
            yield from typed_tokens(key)
            yield ','
            yield from typed_tokens(item)
            yield ']'
        yield ']}'
    elif isinstance(value, (list, tuple, set)):
        kind = 'tuple' if isinstance(value, tuple) else 'set' if isinstance(value, set) else None
        yield '{"'+kind+'":[' if kind else '['
        for i, item in enumerate(value):
            if i: yield ','
            yield from typed_tokens(item)
        yield ']}' if kind else ']'
    elif value is None or isinstance(value, (str, int, float, bool)):
        yield json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    else:
        from babeldoc.format.pdf.document_il.frontend.il_creater_active_support import LazyPassthroughInstruction
        if not isinstance(value, LazyPassthroughInstruction):
            raise ValueError('Unsupported reflow value')
        yield from typed_tokens(value.materialize())


def write_typed(stream, value):
    fragments = []; size = 0
    for token in typed_tokens(value):
        fragments.append(token); size += len(token)
        if size >= 65536:
            stream.write(''.join(fragments).encode('utf-8')); fragments = []; size = 0
    if fragments:
        stream.write(''.join(fragments).encode('utf-8'))


def resource_path(folder, sha):
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
        raise ValueError('Invalid snapshot resource')
    path = folder/'resources'/(sha+'.pdf')
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError('Invalid snapshot resource path')
    return path


def copy_resource(source, folder):
    from native_batches import digest
    sha = digest(source); destination = resource_path(folder, sha)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or digest(destination) != sha:
        temporary = destination.with_suffix('.tmp')
        shutil.copyfile(source, temporary); temporary.replace(destination)
    return sha


def save(artifact, path, resources):
    """Walk the live, stable IL before typesetting; never clone the document."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    document = artifact['document']
    metadata = {k:v for k,v in artifact.items() if k not in ('document', 'sources', 'references')}
    metadata['documentFields'] = {f.name:getattr(document, f.name) for f in dataclasses.fields(document) if f.name != 'page'}
    metadata['resourceFiles'] = {key:copy_resource(value, path.parent) for key,value in resources.items()}
    temporary = path.with_suffix('.tmp')
    try:
        with gzip.open(temporary, 'wb', compresslevel=1) as stream:
            stream.write(b'{"snapshotSchema":2,"metadata":')
            write_typed(stream, metadata); stream.write(b'}\n')
            for page in document.page:
                index = page.page_number
                stream.write(str(index).encode('ascii')+b'\t')
                write_typed(stream, dict(page=page, references=artifact['references'].get(index, []),
                    sources={key:value for key,value in artifact['sources'].items() if key[0] == index}))
                stream.write(b'\n')
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return str(path)


def records(path):
    from native_reflow import decode, classes
    with gzip.open(path, 'rb') as stream:
        header = json.loads(stream.readline())
        if header.get('snapshotSchema') != 2:
            raise ValueError('Invalid incremental snapshot')
        metadata = decode(header['metadata'], classes())
        yield metadata
        for line in stream:
            index, raw = line.split(b'\t', 1)
            record = decode(json.loads(raw), classes())
            if record['page'].page_number != int(index):
                raise ValueError('Invalid snapshot page')
            yield record


def load(path):
    from native_reflow import classes
    from native_batches import digest
    values = records(path); artifact = next(values)
    fields = artifact.pop('documentFields')
    resources = artifact.pop('resourceFiles')
    artifact.update(document=classes()['Document'](**fields), sources={}, references={})
    for record in values:
        artifact['document'].page.append(record['page'])
        artifact['sources'].update(record['sources'])
        artifact['references'][record['page'].page_number] = record['references']
        if len(artifact['document'].page) > 16:
            raise ValueError('Invalid reflow size')
    for key,sha in resources.items():
        if key not in ('source', 'prepared', 'canonicalSource', 'visualSource'):
            raise ValueError('Invalid snapshot resource key')
        source = resource_path(Path(path).parent, sha)
        if digest(source) != sha:
            raise ValueError('Corrupt snapshot resource')
        artifact[key] = source.read_bytes()
    return artifact


def persist(source, destination):
    from native_batches import digest
    source = Path(source); destination = Path(destination)
    values = records(source); metadata = next(values); values.close()
    for sha in metadata['resourceFiles'].values():
        path = resource_path(source.parent, sha)
        if digest(path) != sha:
            raise ValueError('Corrupt snapshot resource')
        copy_resource(path, destination.parent)
    if source.resolve() != destination.resolve():
        temporary = destination.with_suffix('.tmp')
        shutil.copyfile(source, temporary); temporary.replace(destination)


def exported_pages(path):
    from native_artifacts import text_pages
    from native_reflow import classes
    values = records(path); metadata = next(values)
    for record in values:
        page = record['page']
        artifact = dict(metadata, document=classes()['Document'](page=[page]),
                        sources=record['sources'], references={page.page_number:record['references']})
        yield from text_pages(artifact)
