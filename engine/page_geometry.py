"""Canonical visual coordinates for rotated native PDF pages.

BabelDOC 0.6.4's active parser mixes an unrotated MediaBox with a rotated
legacy CropBox (including a negative height at 270 degrees). Bake the page
rotation into vector drawing commands before that parser sees the page.
"""
from __future__ import annotations
import copy

def normalize(data,config):
    import pymupdf
    rotations={}
    with pymupdf.open(stream=data,filetype='pdf') as pdf:
        for page in pdf:
            if page.rotation and config.should_translate_page(page.number+1):
                rotations[page.number]=page.rotation
                # PyMuPDF transforms content, annotations and page boxes together;
                # simply clearing /Rotate would turn the visible table sideways.
                crop,media=page.cropbox,page.mediabox
                # remove_rotation expands CropBox to MediaBox at 90/270.
                # Work in the full media frame, then reinstate the visible clip.
                page.set_cropbox(pymupdf.Rect(media.x0,0,media.x1,media.height))
                clip=(crop+(-media.x0,0,-media.x0,0))*page.rotation_matrix
                page.remove_rotation()
                offset=page.mediabox.x0
                page.set_cropbox(clip+(offset,0,offset,0))
        return (pdf.tobytes() if rotations else data),rotations

def reference_response(response,rotations):
    """Standard parser reports normalized rectangles in the raw source frame."""
    if not rotations or not isinstance(response,dict):return response
    result=copy.deepcopy(response)
    def rect(r,angle):
        x,y,w,h=(r[k] for k in ('left','top','width','height'))
        if angle==90:return dict(left=1-y-h,top=x,width=h,height=w)
        if angle==180:return dict(left=1-x-w,top=1-y-h,width=w,height=h)
        if angle==270:return dict(left=y,top=1-x-w,width=h,height=w)
        return r
    for key in ('entries','exclusions'):
        for entry in result.get(key,[]):
            angle=(rotations.get(entry.get('pageIndex'),0)-entry.get('coordinateRotation',0))%360 if entry.get('pageIndex') in rotations else 0
            if not angle:continue
            if isinstance(entry.get('rect'),dict):entry['rect']=rect(entry['rect'],angle)
            for line in entry.get('lines',[]):
                if isinstance(line.get('rect'),dict):line['rect']=rect(line['rect'],angle)
            # A raw horizontal indent becomes vertical after rotation. Native
            # shadow geometry derives its new indent from the transformed lines.
            entry['bodyLeft']=None
    return result
