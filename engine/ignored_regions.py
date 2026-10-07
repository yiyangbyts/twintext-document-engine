"""Split confirmed ignored source glyphs before any upstream translation call."""
import copy
from reference_layout import characters,inside,pdf_box

def split(page, exclusions):
    from babeldoc.format.pdf.document_il.il_version_1 import Box
    boxes=[pdf_box(e['rect'],page) for e in exclusions if e.get('pageIndex')==page.page_number]
    if not boxes:return set()
    preserved=set();result=[]
    for p in page.pdf_paragraph:
        keep=[];ignore=[]
        for composition in p.pdf_paragraph_composition:
            chars=characters(composition)
            if not chars:keep.append(composition);continue
            flags=[any(inside(c,b,tolerance=.6) for b in boxes) for c in chars]
            if all(flags):ignore.append(composition);continue
            if not any(flags) or composition.pdf_formula:
                # Never split a formula to make an uncertain ignore boundary fit.
                keep.append(composition);continue
            for wanted,destination in [(False,keep),(True,ignore)]:
                selected=[c for c,flag in zip(chars,flags) if flag==wanted]
                if not selected:continue
                part=copy.deepcopy(composition)
                if part.pdf_character:
                    destination.append(part);continue
                group=part.pdf_line or part.pdf_same_style_characters
                group.pdf_character=copy.deepcopy(selected)
                group.box=Box(x=min(c.box.x for c in selected),y=min(c.box.y for c in selected),x2=max(c.box.x2 for c in selected),y2=max(c.box.y2 for c in selected))
                destination.append(part)
        if not ignore:result.append(p);continue
        if not keep:
            p.layout_label='twintext-preserved';preserved.add(p.debug_id);result.append(p);continue
        for compositions,is_preserved in [(keep,False),(ignore,True)]:
            child=copy.deepcopy(p);child.pdf_paragraph_composition=compositions
            chars=[c for comp in compositions for c in characters(comp)]
            if chars:
                child.box=Box(x=min(c.box.x for c in chars),y=min(c.box.y for c in chars),x2=max(c.box.x2 for c in chars),y2=max(c.box.y2 for c in chars))
                child.unicode=''.join(c.char_unicode or '' for c in chars)
            child.debug_id=f'{p.debug_id}-'+('preserved' if is_preserved else 'body')
            if is_preserved:child.layout_label='twintext-preserved';preserved.add(child.debug_id)
            result.append(child)
    page.pdf_paragraph=result
    return preserved
