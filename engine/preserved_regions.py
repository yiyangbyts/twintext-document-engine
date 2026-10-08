"""Keep ignored regions as source PDF vectors, including original encodings."""
def restore_page(source,target,index,regions):
    """Restore one preview page without saving/subsetting a complete PDF."""
    import pymupdf
    page=source[index];clips=[]
    for region in regions:
        if region.get('pageIndex')!=index:continue
        r=region['rect'];clip=pymupdf.Rect(r['left']*page.rect.width,r['top']*page.rect.height,(r['left']+r['width'])*page.rect.width,(r['top']+r['height'])*page.rect.height)
        clip=(clip+(-.8,-.8,.8,.8)) & page.rect
        if not clip.is_empty:clips.append(clip);target.add_redact_annot(clip,fill=None)
    if clips:target.apply_redactions(images=0,graphics=0,text=0)
    for clip in clips:target.show_pdf_page(clip,source,index,clip=clip,overlay=True)

def restore(source,translated,regions,isolated=False,config=None):
    if not regions:return translated
    import pymupdf
    with pymupdf.open(stream=source,filetype='pdf') as original,pymupdf.open(stream=translated,filetype='pdf') as output:
        slots=[]
        for region in regions:
            index=region.get('pageIndex')
            if not isinstance(index,int) or isinstance(index,bool) or not 0<=index<original.page_count:continue
            if config and not config.should_translate_page(index+1):continue
            target=0 if isolated else index
            if target>=output.page_count:continue
            r=region['rect'];page=original[index]
            clip=pymupdf.Rect(r['left']*page.rect.width,r['top']*page.rect.height,(r['left']+r['width'])*page.rect.width,(r['top']+r['height'])*page.rect.height)
            clip=(clip+(-.8,-.8,.8,.8)) & page.rect
            if not clip.is_empty:slots.append((target,index,clip))
        # Numeric/formula fragments may live outside the paragraph list. Clear
        # reconstructed text in all confirmed slots before restoring any source
        # text, so neighboring annotations cannot erase restored source glyphs.
        for target,index,clip in slots:output[target].add_redact_annot(clip,fill=None)
        for target in {s[0] for s in slots}:output[target].apply_redactions(images=0,graphics=0,text=0)
        for target,index,clip in slots:output[target].show_pdf_page(clip,original,index,clip=clip,overlay=True)
        return output.tobytes()
