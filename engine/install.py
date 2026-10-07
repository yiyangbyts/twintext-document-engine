"""Create a private standalone engine environment with platform constraints.

Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
Run using CPython 3.12; this script never installs into the invoking environment.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import platform
import subprocess
import sys
import sysconfig
import venv


def target():
    system, abi = platform.system(), sysconfig.get_platform().lower()
    if system == 'Windows':
        if abi != 'win-amd64':
            raise RuntimeError('Use x64 CPython 3.12 on Windows, including Windows ARM64 compatibility mode')
        return 'win-x64'
    architecture = 'arm64' if platform.machine().lower() in ('aarch64', 'arm64') else 'x64' if platform.machine().lower() in ('amd64', 'x86_64') else None
    if system not in ('Darwin', 'Linux') or architecture is None:
        raise RuntimeError('Unsupported standalone engine platform')
    return ('mac' if system == 'Darwin' else 'linux') + '-' + architecture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment', type=Path, default=Path(__file__).with_name('.venv'))
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12) or platform.python_implementation() != 'CPython':
        parser.error('Use CPython 3.12 to create the engine environment')
    root = Path(__file__).resolve().parent
    directory = args.environment.resolve()
    if directory.exists():
        parser.error('Environment already exists; choose an empty location')
    constraint = root / f'constraints-{target()}.txt'
    venv.EnvBuilder(with_pip=True).create(directory)
    python = directory / ('Scripts/python.exe' if platform.system()=='Windows' else 'bin/python')
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(root/'requirements.txt'), '-c', str(constraint)], check=True)
    subprocess.run([str(python), str(root/'download_model.py')], check=True)
    print(f'Engine ready: {python} {root / "cli.py"}')


if __name__ == '__main__':
    main()
