"""Rich styles over the text relay and opt-in native figure/table labels.

Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
from collections import defaultdict
import re

GRAPHICS = {'figure', 'image', 'chart', 'table'}
CAPTIONS = {'figure_caption', 'table_caption', 'figure_title', 'chart_title',
            'table_title', 'table_footnote', 'formula_caption'}


def repair_standard_fonts(fonts):
    # Base-14 fonts need no FontDescriptor. The parser can report all of their
    # traits as false; recover only the PDF-standard, unambiguous font names.
    standard = {'helvetica', 'helvetica-bold', 'helvetica-oblique', 'helvetica-boldoblique',
                'times-roman', 'times-bold', 'times-italic', 'times-bolditalic',
                'courier', 'courier-bold', 'courier-oblique', 'courier-boldoblique'}
    for font in (fonts or {}).values():
        name = (font.name or '').split('+')[-1].lower()
        if name in standard:
            font.bold = 'bold' in name
            font.italic = 'italic' in name or 'oblique' in name
            font.serif = name.startswith(('times-', 'courier'))
            font.monospace = name.startswith('courier')


def make_translator(base):
    class RelayStylesTranslator(base):
        def pre_translate_paragraph(self, paragraph, tracker, page_font_map, xobj_font_map):
            # BabelDOC normally enables style placeholders only for its prompt
            # interface. TwinText's text relay already validates these markers;
            # keep the plain translation route and its paragraph-local fallback.
            if paragraph.vertical:
                return None, None
            tracker.set_pdf_unicode(paragraph.unicode)
            fonts = (xobj_font_map or {}).get(paragraph.xobj_id, page_font_map)
            repair_standard_fonts(fonts)
            prepared = self.get_translate_input(paragraph, fonts,
                self.translation_config.disable_rich_text_translate)
            if prepared is None:
                return None, None
            tracker.set_input(prepared.unicode)
            tracker.set_placeholders(prepared.placeholders)
            tracker.set_original_placeholders(getattr(prepared, 'original_placeholder_tokens', None))
            if len(prepared.unicode) < self.translation_config.min_text_length:
                return None, None
            # A selected table/figure-only page has no body paragraph. Count
            # its actual text requests at the same completion gate; the outer
            # quality tracker restores this thread-local flag after each call.
            config = self.translation_config
            context = getattr(config, 'twintext_translation_context', None)
            if context is not None:
                graphic_text = (config.twintext_document_options.get('translateFigureTableText') is True
                    and paragraph.layout_label in {'table_text', 'figure_text', 'table_cell_hybrid',
                                                  'wired_table_cell', 'wireless_table_cell', 'table_cell', 'figure_text_hybrid'})
                caption = paragraph.layout_label in {'figure_caption', 'table_caption', 'figure_title', 'chart_title', 'table_title'}
                if ((graphic_text or caption)
                        and sum(c.isalpha() for c in re.sub(r'</?b\d+>', '', prepared.unicode)) >= 2):
                    context.body = True
            return prepared.unicode, prepared
    return RelayStylesTranslator


def character_box(char):
    visual = getattr(char, 'visual_bbox', None)
    return visual.box if visual is not None else char.box


def contains(outer, inner):
    width, height = inner.x2 - inner.x, inner.y2 - inner.y
    if width <= 0 or height <= 0:
        return False
    return (max(0, min(outer.x2, inner.x2) - max(outer.x, inner.x)) *
            max(0, min(outer.y2, inner.y2) - max(outer.y, inner.y))) >= width * height * .8


def graphic_characters(page):
    """Assign glyphs to a graphic, leaving captions and formula layouts alone."""
    from babeldoc.format.pdf.document_il.utils.layout_helper import build_layout_index, get_character_layout
    regions = {layout.id: layout for layout in page.page_layout
               if layout.class_name in GRAPHICS and (layout.conf or 0) >= .5}
    if not regions:
        return {}
    index, layouts = build_layout_index(page)
    result = {}
    for char in page.pdf_character:
        box = character_box(char)
        candidates = [layouts[key] for key in index.intersection((box.x, box.y, box.x2, box.y2))
                      if layouts[key].id in regions and contains(layouts[key].box, box)]
        if not candidates:
            continue
        selected = get_character_layout(char, index, layouts)
        if selected and (selected.name in CAPTIONS or 'formula' in selected.name):
            continue
        # Prefer an inner table to an enclosing image/figure.
        result[id(char)] = min(candidates, key=lambda r:
            (r.box.x2 - r.box.x) * (r.box.y2 - r.box.y))
    return result


def label_groups(chars):
    """Keep physical rows and separated cells independent; never merge columns."""
    rows = []
    for char in sorted(chars, key=lambda c: (-character_box(c).y2, character_box(c).x)):
        box = character_box(char)
        center = (box.y + box.y2) / 2
        height = box.y2 - box.y
        row = next((r for r in reversed(rows[-3:])
                    if abs(center - r[0]) <= min(height, r[1]) * .35), None)
        if row is None:
            rows.append([center, height, [char]])
        else:
            row[2].append(char)
    for _, _, row in rows:
        group, right = [], None
        for char in sorted(row, key=lambda c: character_box(c).x):
            box = character_box(char)
            size = getattr(char.pdf_style, 'font_size', None) or box.y2 - box.y
            if group and box.x - right > max(3, size * .9):
                yield group
                group = []
            group.append(char)
            right = max(right or box.x2, box.x2)
        if group:
            yield group


def make_paragraph_finder(base):
    class GraphicTextParagraphFinder(base):
        def process_page(self, page):
            membership = graphic_characters(page)
            if not membership:
                return super().process_page(page)
            enabled = self.translation_config.twintext_document_options.get('translateFigureTableText') is True
            if not enabled:
                # Keep the exact source glyphs out of both translation and
                # typesetting. In scan mode their pixels already exist below.
                kept = [c for c in page.pdf_character if id(c) in membership]
                page.pdf_character = [c for c in page.pdf_character if id(c) not in membership]
                try:
                    return super().process_page(page)
                finally:
                    if not self.translation_config.ocr_workaround:
                        page.pdf_character.extend(kept)
            from babeldoc.format.pdf.document_il import Box, PageLayout
            buckets = defaultdict(list)
            for char in page.pdf_character:
                region = membership.get(id(char))
                if region is not None:
                    buckets[(region.id, char.xobj_id)].append(char)
            next_id = max((layout.id for layout in page.page_layout), default=0) + 1
            regions = {r.id: r for r in membership.values()}
            for (region_id, _), chars in buckets.items():
                region = regions[region_id]
                for group in label_groups(chars):
                    boxes = [character_box(c) for c in group]
                    page.page_layout.append(PageLayout(id=next_id, conf=1,
                        class_name='table_text' if region.class_name == 'table' else 'figure_text',
                        box=Box(min(b.x for b in boxes), min(b.y for b in boxes),
                                max(b.x2 for b in boxes), max(b.y2 for b in boxes))))
                    next_id += 1
            return super().process_page(page)
    return GraphicTextParagraphFinder
