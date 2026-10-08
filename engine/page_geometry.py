"""Canonical visual coordinates for rotated native PDF pages.

BabelDOC 0.6.4's active parser mixes an unrotated MediaBox with a rotated
legacy CropBox (including a negative height at 270 degrees). Bake the page
rotation into vector drawing commands before that parser sees the page.
"""
from __future__ import annotations
import copy,math

def content_rotation(page):
    """Turn a dominant sideways body upright; marginal labels cannot vote.

    PDF /Rotate and individual text drawing directions are independent.
    Require substantial interior prose and a clear majority, keeping small
    rotated labels and ordinary landscape pages in their original frame.
    """
    import pymupdf
    weights={0:0,90:0,180:0,270:0}
    rect=page.rect;inner=rect+(rect.width*.06,rect.height*.06,-rect.width*.06,-rect.height*.06)
    for block in page.get_text('dict',flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)['blocks']:
        for line in block.get('lines',[]):
            if line.get('wmode',0):continue
            if not inner.contains(pymupdf.Rect(line['bbox'])):continue
            text=''.join(span['text'] for span in line['spans'])
            weight=sum(c.isalpha() for c in text)
            if weight<3:continue
            x,y=line['dir'];angle=math.degrees(math.atan2(y,x))%360
            nearest=(round(angle/90)*90)%360
            if abs((angle-nearest+180)%360-180)<5:weights[nearest]+=weight
    direction=max(weights,key=weights.get);total=sum(weights.values())
    return (-direction)%360 if direction and weights[direction]>=80 and weights[direction]>=total*.7 else 0

def _bake_rotation(page):
    import pymupdf
    crop,media=page.cropbox,page.mediabox
    page.set_cropbox(pymupdf.Rect(media.x0,0,media.x1,media.height))
    clip=(crop+(-media.x0,0,-media.x0,0))*page.rotation_matrix
    page.remove_rotation();offset=page.mediabox.x0
    page.set_cropbox(clip+(offset,0,offset,0))

def normalize(data,config):
    import pymupdf
    rotations={};content={};source_rotations={}
    with pymupdf.open(stream=data,filetype='pdf') as pdf:
        for page in pdf:
            if not config.should_translate_page(page.number+1):continue
            source_rotations[page.number]=page.rotation
            if page.rotation:
                rotations[page.number]=page.rotation
                # PyMuPDF transforms content, annotations and page boxes together;
                # simply clearing /Rotate would turn the visible table sideways.
                # remove_rotation expands CropBox to MediaBox at 90/270.
                # Work in the full media frame, then reinstate the visible clip.
                _bake_rotation(page)
            angle=content_rotation(page)
            if angle:
                content[page.number]=angle
                rotations[page.number]=(rotations.get(page.number,0)+angle)%360
                page.set_rotation(angle);_bake_rotation(page)
        config.twintext_content_rotations=content
        config.twintext_source_rotations=source_rotations
        return (pdf.tobytes() if rotations else data),rotations

def restore_content(data,rotations,selected=None,isolated=False):
    """Map translated drawing commands back into the original visual frame."""
    if not rotations:return data
    import pymupdf
    with pymupdf.open(stream=data,filetype='pdf') as pdf:
        for position,index in enumerate(selected if isolated else range(pdf.page_count)):
            angle=rotations.get(index,0)
            if angle:
                page=pdf[position if isolated else index]
                page.set_rotation((-angle)%360);_bake_rotation(page)
        return pdf.tobytes()

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
