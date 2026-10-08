"""Explicit one-click download. Commit, size and hashes are pinned in the XPI."""
from __future__ import annotations
import hashlib,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def emit(stage,message,progress=None): print(json.dumps({'stage':stage,'message':message,'progress':progress},ensure_ascii=True),flush=True)
def main():
    manifest=json.loads((ROOT/'model-manifest.json').read_text())
    if manifest['backend']!='babeldoc':raise ValueError('Unsupported document engine')
    assets=ROOT/'assets'
    assets.mkdir(parents=True,exist_ok=True)
    # A downloader may only repair its own installation, never inherited assets.
    os.environ['TWINTEXT_BABEL_ASSETS']=str(assets.resolve())
    from asset_paths import configure
    configure(ROOT/'model')
    from babeldoc.assets.assets import warmup,generate_all_assets_file_list,verify_file
    from babeldoc.const import CACHE_FOLDER
    emit('download','下载并校验 BabelDOC 原生版面模型、字体与资源…')
    from asset_downloads import prepare
    prepare(ROOT,manifest['assets'],emit)
    warmup()
    listing=generate_all_assets_file_list()
    # Check the pinned XPI recipe as well as upstream verification.
    for item in manifest['assets']:
        relative=Path(item['path'])
        if relative.is_absolute() or '..' in relative.parts or relative.parts[0]!='assets':raise ValueError('Unsafe asset path')
        path=assets/Path(*relative.parts[1:])
        with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha3_256').hexdigest()
        if path.stat().st_size!=item['bytes'] or actual!=item['sha3_256']:raise RuntimeError('Pinned BabelDOC asset verification failed: '+str(relative))
    # Record verified upstream digests for diagnostics.
    entries=[]
    for folder,files in listing.items():
        for desc in files:
            name=desc['name'];path=CACHE_FOLDER/folder/name
            if not verify_file(path,desc['sha3_256']):raise RuntimeError('BabelDOC asset verification failed: '+name)
            entries.append({'path':str(path),'sha3_256':desc['sha3_256'],'size':path.stat().st_size})
    (ROOT/'model').mkdir(exist_ok=True)
    (ROOT/'model'/'babel-assets.json').write_text(json.dumps(entries))
    emit('ready','模型文件校验完成。',100)
if __name__=='__main__':
    try:main()
    except Exception as error:emit('error',str(error));raise
