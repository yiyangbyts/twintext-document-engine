"""Bind verified application assets before importing the upstream pipeline."""
from __future__ import annotations
import json,os
from pathlib import Path

def configure(model=None):
    folder=Path(model).parent/'assets' if model else None
    if model and not folder.is_dir():
        marker=Path(model).parent/'installed.json'
        if marker.is_file():
            value=json.loads(marker.read_text()).get('assetDirectory')
            if value:folder=Path(value)
    if folder and folder.is_dir():os.environ['TWINTEXT_BABEL_ASSETS']=str(folder.resolve())
    value=os.environ.get('TWINTEXT_BABEL_ASSETS')
    if not value:return
    folder=Path(value).resolve()
    if not folder.is_dir():raise RuntimeError('Bundled document assets are missing')
    import babeldoc.const as const
    const.CACHE_FOLDER=folder
    const.TIKTOKEN_CACHE_FOLDER=folder/'tiktoken'
    os.environ['TIKTOKEN_CACHE_DIR']=str(const.TIKTOKEN_CACHE_FOLDER)
