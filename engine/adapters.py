"""Normalized geometry helpers used by the native BabelDOC adapter."""
from __future__ import annotations

def rect(box, width=1, height=1):
    a,b,c,d=map(float,box)
    a=max(0,min(1,a/width));b=max(0,min(1,b/height))
    c=max(a,min(1,c/width));d=max(b,min(1,d/height))
    if c<=a or d<=b: raise ValueError('Invalid model box')
    return [a,b,c-a,d-b]


def region(kind, box, text='', score=1):
    return {'kind':kind,'rect':box,'text':str(text or '')[:65536],
            'latex':str(text or '')[:16384] if kind in ('inline','display') else '',
            'origin':'model','score':max(0,min(1,float(score)))}
