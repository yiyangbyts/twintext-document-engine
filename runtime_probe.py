# Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
"""Offline, read-only runtime/model validation.

Run with the candidate interpreter. Recipes always come from the current XPI,
not from the installation being checked. No package manager or network calls.
"""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import importlib
import importlib.metadata as metadata
import json
import os
import platform
import re
from pathlib import Path
import sys
import sysconfig

IMPORTS = {'babeldoc': ['babeldoc.format.pdf.high_level']}

def digest(stream, algorithm='sha256', prefix=b''):
    value = hashlib.new(algorithm)
    value.update(prefix)
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        value.update(block)
    return value.hexdigest()


def requirements(path):
    return [line.split('#', 1)[0].strip() for line in path.read_text().splitlines()
            if line.split('#', 1)[0].strip()]


def dependencies(recipe, key, req_name, constraints):
    try:
        from packaging.requirements import Requirement
        from packaging.utils import canonicalize_name
    except ImportError:
        return ['缺少依赖校验组件 packaging']
    issues, seen = [], set()
    queue = requirements(recipe / req_name)
    if constraints:
        # Constraints apply to installed distributions, never force CUDA/Linux
        # packages onto a Mac. The reachable dependency closure is checked below.
        for line in requirements(recipe / constraints):
            requirement = Requirement(line)
            try:
                metadata.distribution(requirement.name)
                queue.append(line)
            except metadata.PackageNotFoundError:
                pass
    while queue:
        item = queue.pop()
        text, *extras = item if isinstance(item, tuple) else (item,)
        # OmegaConf 2.0.x metadata contains legacy "PyYAML >=5.1.*".
        # Preserve the lower bound when parsing it with modern packaging.
        req = Requirement(re.sub(r'(>=\s*\d+(?:\.\d+)*)\.\*', r'\1', text))
        if req.marker and not any(req.marker.evaluate({'extra': extra}) for extra in (extras or [''])):
            continue
        name = canonicalize_name(req.name)
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            issues.append(f'{name}: missing')
            continue
        if req.specifier and not req.specifier.contains(dist.version, prereleases=True):
            issues.append(f'{name}: {dist.version} does not match {req.specifier}')
        visit = (name, tuple(sorted(req.extras)))
        if visit in seen:
            continue
        seen.add(visit)
        queue.extend((entry, '', *req.extras) for entry in dist.requires or [])
    if not issues:
        try:
            with contextlib.redirect_stdout(sys.stderr):
                for module in IMPORTS[key]:
                    importlib.import_module(module)
        except Exception as error:
            issues.append(f'import: {type(error).__name__}: {error}')
    return sorted(set(issues))


def runtime_matches(version, target):
    if platform.python_version() != version:
        return False
    if target.startswith('win-'):
        # platform.machine() can report the ARM64 host for an emulated x64
        # interpreter. Wheel ABI describes the interpreter we actually launch.
        return sys.platform == 'win32' and sysconfig.get_platform() == 'win-amd64'
    expected = ('arm64', 'aarch64') if target in ('mac-arm64', 'linux-arm64') else ('x86_64', 'amd64', 'x64')
    if target in ('linux-x64', 'linux-arm64'):
        return sys.platform == 'linux' and platform.machine().lower() in expected
    return target in ('mac-arm64', 'mac-x64') and sys.platform == 'darwin' and platform.machine().lower() in expected


def assets(recipe, directory):
    """Validate only XPI-pinned assets without creating cache directories."""
    if directory is None:return ['BabelDOC asset directory missing']
    asset_root=directory/'assets'
    if not asset_root.is_dir():
        marker=directory/'installed.json'
        value=os.environ.get('TWINTEXT_BABEL_ASSETS')
        if not value and marker.is_file():value=json.loads(marker.read_text()).get('assetDirectory')
        if value:asset_root=Path(value)
    if not asset_root.is_dir():return ['BabelDOC asset directory missing']
    missing=[]
    manifest=json.loads((recipe/'model-manifest.json').read_text())
    if manifest.get('backend')!='babeldoc' or not manifest.get('assets'):raise ValueError('Missing pinned BabelDOC asset recipe')
    for item in manifest['assets']:
        relative=Path(item['path'])
        if relative.is_absolute() or '..' in relative.parts or relative.parts[0]!='assets':raise ValueError('Unsafe asset path')
        file=asset_root/Path(*relative.parts[1:])
        try:
            if file.stat().st_size!=item['bytes']:raise ValueError('Asset size mismatch')
            with file.open('rb') as stream:actual=digest(stream,'sha3_256')
            if actual!=item['sha3_256']:raise ValueError('Asset digest mismatch')
        except (OSError,ValueError):missing.append(relative.as_posix())
    return missing

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', required=True, choices=list(IMPORTS))
    parser.add_argument('--recipe', type=Path, required=True)
    parser.add_argument('--python-version', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--requirements', required=True)
    parser.add_argument('--constraints')
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--models-only', action='store_true')
    args = parser.parse_args()
    # Validation never invokes package managers or remote model sources.
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    python_ok = runtime_matches(args.python_version, args.target)
    issues = dependencies(args.recipe, args.engine, args.requirements, args.constraints) if python_ok and not args.models_only else []
    copied=0
    try:missing=assets(args.recipe,args.directory)
    except (OSError,ValueError,KeyError,TypeError):missing=['BabelDOC verified asset recipe']
    print(json.dumps({'protocol': 1, 'python_ok': python_ok, 'deps_ok': python_ok and not issues and not args.models_only,
                      'models_ok': bool(args.directory) and not missing, 'issues': issues[:20],
                      'missing_models': missing[:20], 'copied_models': copied}), flush=True)


if __name__ == '__main__':
    main()
