"""Expose one translated IL page for browser reading without changing the PDF.

Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
Formula glyphs remain original graphics; no translator is used by this API.
"""
from __future__ import annotations
import base64,copy,json,statistics
from pathlib import Path

PROFILE='native-reading-2.0.12-v1'

def character_obstacles(characters,coordinates):
    # BabelDOC keeps display formulas outside translated paragraphs. Group
    # their glyphs into compact line spans so text cannot expand over them.
    rows={}
    for char in characters:
        if not char.box:continue
        rect=coordinates(char.box)
        if min(rect['width'],rect['height'])<=0:continue
        rows.setdefault(round((rect['top']+rect['height']/2)/4),[]).append(rect)
    result=[]
    for row in rows.values():
        span=None
        for rect in sorted(row,key=lambda r:r['left']):
            if span is None or rect['left']>span['left']+span['width']+32:
                span=rect.copy();result.append(span)
            else:
                right=max(span['left']+span['width'],rect['left']+rect['width'])
                bottom=max(span['top']+span['height'],rect['top']+rect['height'])
                span['top']=min(span['top'],rect['top']);span['width']=right-span['left'];span['height']=bottom-span['top']
    return result

def font_map(page,typesetter):
    fonts={f.font_id:f for f in page.pdf_font if f.font_id}
    fonts.update(typesetter.font_mapper.fontid2font)
    for xobj in page.pdf_xobject:
        if xobj.xobj_id is not None:
            fonts[xobj.xobj_id]={f.font_id:f for f in [*page.pdf_font,*xobj.pdf_font] if f.font_id}
    return fonts

def page_data(artifact,index,folder,cancel):
    from document_preview import SnapshotRenderer
    import pymupdf
    folder.mkdir(parents=True,exist_ok=True)
    source=folder/'source.pdf';source.write_bytes(artifact.get('canonicalSource',artifact['source']))
    prepared=folder/'prepared.pdf';prepared.write_bytes(artifact['prepared'])
    renderer=SnapshotRenderer(dict(source=str(source),prepared=str(prepared),root=str(folder/'renderer'),
        langIn=artifact['langIn'],langOut=artifact['langOut'],documentOptions={},
        originalRotations={},contentRotations={},preservedRegions=artifact['preserved']),cancel)
    page=copy.deepcopy(next(p for p in artifact['document'].page if p.page_number==index))
    fonts=font_map(page,renderer.typesetter)
    plans=artifact['references'].get(index,[])
    parents={key for e in plans if e.get('translated') for key in e['parents']}
    candidates=[(p,None) for p in page.pdf_paragraph if p.debug_id not in parents and p.debug_id not in artifact['preserved_ids']]
    candidates.extend((e['paragraph'],e) for e in plans if e.get('translated'))
    frame=page.cropbox.box if page.cropbox else page.mediabox.box
    blocks=[];removed=set();graphic_bytes=0;obstacles=[]
    with pymupdf.open(source) as pdf:
        original=pdf[index]
        for image in original.get_image_info():
            x,y,x2,y2=image['bbox'];obstacles.append(dict(left=x,top=y,width=x2-x,height=y2-y))
        for drawing in original.get_drawings():
            box=drawing['rect']
            if box.width>100 and box.height>40 and box.get_area()>4000:
                obstacles.append(dict(left=box.x0,top=box.y0,width=box.width,height=box.height))
        def coordinates(box):return dict(left=box.x-frame.x,top=frame.y2-box.y2,width=box.x2-box.x,height=box.y2-box.y)
        def atom(box,text):
            nonlocal graphic_bytes
            rect=coordinates(box)
            clip=pymupdf.Rect(rect['left'],rect['top'],rect['left']+rect['width'],rect['top']+rect['height']) & original.rect
            if clip.is_empty:return {'type':'text','text':text,'fontSize':10}
            # Clip the original drawing rather than reconstructing formula text.
            # SVG keeps vector glyphs; large embedded resources use a bounded raster.
            with pymupdf.open() as snippet:
                target=snippet.new_page(width=clip.width,height=clip.height)
                target.show_pdf_page(target.rect,pdf,index,clip=clip)
                svg=target.get_svg_image(text_as_path=True).encode()
                if len(svg)<=256000 and graphic_bytes+len(svg)<=4*1024*1024:
                    data=svg;mime='image/svg+xml'
                else:data=original.get_pixmap(matrix=pymupdf.Matrix(3,3),clip=clip,alpha=True).tobytes('png');mime='image/png'
            graphic_bytes+=len(data)
            return {'type':'graphic','text':text,'width':clip.width,'height':clip.height,
                'mime':mime,'data':base64.b64encode(data).decode()}
        for paragraph,entry in candidates:
            renderer.config.raise_if_cancelled()
            units=renderer.typesetter.create_typesetting_units(paragraph,fonts)
            if not units or all(u.can_passthrough for u in units):continue
            rect=coordinates(paragraph.box)
            if min(rect['width'],rect['height'])<=0:continue
            source_sizes=[u.font_size for u in units if u.font_size]
            base=statistics.median(source_sizes) if source_sizes else (paragraph.pdf_style.font_size if paragraph.pdf_style else 10)
            runs=[]
            if entry and entry.get('label') and entry['label'].unicode:
                runs.append({'type':'text','text':entry['label'].unicode+' ','fontSize':base})
            for unit in units:
                if unit.formular:
                    formula=unit.formular
                    text=''.join(c.char_unicode or '' for c in formula.pdf_character)
                    runs.append(atom(formula.box,text));continue
                if unit.char:
                    runs.append(atom(unit.char.box,unit.char.char_unicode or ''));continue
                font=unit.original_font
                style=dict(type='text',text=unit.unicode or '',fontSize=unit.font_size or base,
                    bold=bool(getattr(font,'bold',False)),italic=bool(getattr(font,'italic',False)))
                if runs and all(runs[-1].get(k)==style[k] for k in ('type','fontSize','bold','italic')):
                    runs[-1]['text']+=style['text']
                else:runs.append(style)
            if entry and entry.get('tail') and entry['tail'].unicode:runs.append({'type':'text','text':' '+entry['tail'].unicode,'fontSize':base})
            blocks.append(dict(id=str(paragraph.debug_id or len(blocks)),rect=rect,fontSize=base,
                kind=entry.get('kind','reference') if entry else str(paragraph.layout_label or 'body'),
                label=entry.get('label').unicode if entry and entry.get('label') else None,runs=runs))
            removed.add(paragraph.debug_id)
        removed.update(parents)
        obstacles.extend(character_obstacles(page.pdf_character,coordinates))
        obstacles.extend(coordinates(p.box) for p in page.pdf_paragraph if p.debug_id not in removed and p.box)
    page.pdf_paragraph=[p for p in page.pdf_paragraph if p.debug_id not in removed and p.debug_id not in artifact['preserved_ids']]
    background=renderer.render(dict(page=page,pageCount=artifact['pageCount'],revision=1,paragraphs=[],
        completedParagraphs=0,totalParagraphs=len(page.pdf_paragraph),documentOptions={}))
    return dict(profile=PROFILE,pipeline=PROFILE,pageIndex=index,width=background['width'],height=background['height'],
        rotation=(-artifact.get('contentRotations',{}).get(index,0))%360,background=background['png'],blocks=blocks,obstacles=obstacles)

def run(payload,folder,cancel,artifacts=None):
    from native_reflow import load_manifest,load_part
    index=payload.get('currentPage')
    if type(index) is not int or index<0:raise ValueError('Invalid reading page')
    if payload.get('artifactFile'):
        root,manifest=load_manifest(payload['artifactFile'])
        if index not in manifest['pages']:raise ValueError('Reading page outside translated range')
        part=next(p for p in manifest['parts'] if p['first']<=index<=p['last'])
        # Validate the checkpoint before serving a derived cached page.
        artifact=load_part(root,part);local=index-part['first']
        cached=root/('reading-2.0.12-'+part['sha256'][:16]+'-'+str(index)+'.json')
        if cached.is_file():
            value=json.loads(cached.read_text())
            if value.get('profile')==PROFILE and value.get('pageIndex')==index:return value
        value=page_data(artifact,local,folder,cancel);value['pageIndex']=index
        temporary=cached.with_suffix('.tmp');temporary.write_text(json.dumps(value,separators=(',',':')),encoding='utf-8');temporary.replace(cached)
        # A reading cache is optional and disposable, unlike the IL checkpoint.
        files=sorted(root.glob('reading-2.0.12-*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
        total=0
        for entry in files:
            total+=entry.stat().st_size
            if total>64*1024*1024 and entry!=cached:entry.unlink(missing_ok=True)
        return value
    if artifacts is None:raise ValueError('native_artifact_expired')
    return page_data(artifacts.get(payload.get('artifactId')),index,folder,cancel)
