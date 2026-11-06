"""Build the separately maintained engine source archive; never reads the client."""
# Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
from pathlib import Path
import argparse,hashlib,json,zipfile
ROOT=Path(__file__).resolve().parent
def sha(data):return hashlib.sha256(data).hexdigest()
def source_files():
    top=['package.json','LICENSE.txt','README.md','API.md','NOTICE.md','DEPENDENCIES.json','ASSETS.json','runtime.json','build-source.py']
    files={name:ROOT/name for name in top}
    for p in ROOT.glob('*.js'):files[p.name]=p
    for folder in ['core','adapters','assets','vendor','licenses','tools','test']:
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and not any(part.startswith('.') or part=='__pycache__' for part in p.relative_to(ROOT).parts):files[p.relative_to(ROOT).as_posix()]=p
    assert all(p.resolve().is_relative_to(ROOT.resolve()) for p in files.values()),'Source archive cannot follow links outside the engine'
    for name,wanted in json.loads((ROOT/'ASSETS.json').read_text()).items():assert sha(files[name].read_bytes())==wanted,name
    return files
def inventory(files):
    return [dict(path=name,sha256=sha(p.read_bytes())) for name,p in sorted(files.items())]
def build(outdir):
    version=json.loads((ROOT/'package.json').read_text())['version'];files=source_files();records=inventory(files)
    manifest=json.dumps({'version':version,'files':records},ensure_ascii=False,indent=2).encode()+b'\n'
    revision=sha(manifest);outdir=Path(outdir);outdir.mkdir(parents=True,exist_ok=True);out=outdir/f'twintext-engine-source-{version}.zip'
    # All sources and assets have content hashes. Reuse only a verified identical archive.
    if out.exists():
        with zipfile.ZipFile(out) as z:
            if z.read('SOURCE-MANIFEST.json')==manifest and set(z.namelist())==set(files)|{'SOURCE-MANIFEST.json'} and all(sha(z.read(r['path']))==r['sha256'] for r in records):return out,revision,records
    tmp=out.with_suffix('.tmp')
    try:
        with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for name,p in sorted(files.items()):
                info=zipfile.ZipInfo(name,(2026,11,4,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o644<<16;z.writestr(info,p.read_bytes(),compresslevel=6)
            z.writestr('SOURCE-MANIFEST.json',manifest)
        tmp.replace(out)
    finally:tmp.unlink(missing_ok=True)
    out.with_suffix('.zip.sha256').write_text(f'{sha(out.read_bytes())}  {out.name}\n')
    return out,revision,records
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-dir',type=Path,default=ROOT/'dist');args=parser.parse_args();print(build(args.output_dir)[0])
