"""File-only PDF export worker: deliberately imports no BabelDOC/model code.

Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
import json,sys

def execute(mode,args):
    import pymupdf
    with pymupdf.open(args[0]) as pdf:
        if mode=='subset':
            pdf.subset_fonts(fallback=False)
            pdf.save(args[1])
        elif mode=='save':
            _,output,garbage,deflate,clean,deflate_fonts,linear=args
            pdf.save(output,garbage=garbage,deflate=deflate,clean=clean,
                deflate_fonts=deflate_fonts,linear=linear)
        elif mode=='raster':
            import math
            _,output,index,scale=args
            if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<len(pdf):raise ValueError('Invalid page index')
            page=pdf[index]
            scale=min(3,max(1,float(scale)),math.sqrt(4_000_000/max(1,page.rect.get_area())))
            pix=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),colorspace=pymupdf.csRGB,alpha=False)
            pix.save(output)
            return dict(width=pix.width,height=pix.height,rotation=page.rotation,pageCount=len(pdf),scale=scale)
        else:raise ValueError('Unknown PDF export operation')

if __name__=='__main__':
    result=execute(sys.argv[1],json.loads(sys.argv[2]))
    if result is not None:print(json.dumps(result))
