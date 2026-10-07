"""Engine-local reference/list/contents planning from source glyph geometry.

Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
Coordinates use the canonical input PDF crop frame. No reader or client parser
is needed. Uncertain parents are rejected later by source_shadows, preserving
BabelDOC's ordinary result instead of partially erasing source content.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from statistics import median

REVISION = 'engine-structure-2.0.5-v1'
REFERENCES = re.compile(r'^(?:(?:\d+(?:\.\d+)*|[IVXLCDM]+)[.)]?\s+)?(?:references|bibliography|literature cited|参考文献|參考文獻)\s*[:：]?$', re.I)
CONTENTS = re.compile(r'^(?:table of contents|contents|目录|目錄)\s*[:：]?$', re.I)
END = re.compile(r'^(?:appendix|appendices|supplement(?:ary|al)(?:\s+(?:material|information))?)\b|^(?:附录|附錄)', re.I)
STATEMENT = re.compile(r'^(?:disclaimer(?:\s*/\s*publisher[’\']?s?\s+note)?|publisher[’\']?s?\s+note|author contributions?|funding|data availability(?: statement)?|conflicts? of interest|acknowledg(?:e)?ments?|ethics statement|免责声明|出版者声明|作者贡献|数据可用性声明|利益冲突)\s*[:：]', re.I)
REF_MARKER = re.compile(r'^\s*(\[\d{1,4}\]|\d{1,4}[.)])\s+(\S.*)')
LIST_MARKER = re.compile(r'^\s*([（(]?(?:\d{1,3}|[A-Za-z])[.)）、．]|[•●◦▪▫‣⁃∙])\s+(\S.*)')
PAGE_TAIL = re.compile(r'^(.+?)\s*((?:[.·…⋯]\s*){2,})?\s+(\d{1,4}|[ivxlcdm]{1,8})\s*$', re.I)
PUBLICATION = re.compile(r'\b(?:19|20)\d{2}\b|\bdoi\b|\barxiv\b', re.I)
PROTECTED = {'table', 'figure', 'image', 'formula', 'code', 'footnote', 'caption', 'table_caption', 'figure_caption'}


def characters(composition):
    if composition.pdf_character:
        return [composition.pdf_character]
    for name in ('pdf_line', 'pdf_same_style_characters', 'pdf_formula'):
        value = getattr(composition, name, None)
        if value:
            return value.pdf_character
    return []


def rows_from_page(page):
    """Keep parent identity, baseline, columns and font style from native IL."""
    crop = page.cropbox.box
    width, height = crop.x2 - crop.x, crop.y2 - crop.y
    if width <= 0 or height <= 0:
        return []
    fonts = {f.font_id: f for f in page.pdf_font}
    result = []
    for parent in page.pdf_paragraph:
        kind = getattr(parent, 'layout_label', '') or ''
        if parent.vertical or not parent.pdf_style or kind.lower() in PROTECTED:
            continue
        glyphs = [c for comp in parent.pdf_paragraph_composition for c in characters(comp)
                  if c.box and c.pdf_style and c.char_unicode]
        lines = []
        for c in sorted(glyphs, key=lambda c: (-c.box.y, c.box.x)):
            size = max(1, c.pdf_style.font_size)
            line = next((l for l in reversed(lines) if abs(l[0].box.y - c.box.y) <= size * .35), None)
            if line is None:
                lines.append([c])
            else:
                line.append(c)
        for line in lines:
            # A merged native parent can contain both columns on one baseline.
            parts = [[]]
            for c in sorted(line, key=lambda c: c.box.x):
                if parts[-1] and c.box.x - parts[-1][-1].box.x2 > max(24, c.pdf_style.font_size * 3):
                    parts.append([])
                parts[-1].append(c)
            for part in parts:
                literal = ''
                previous = None
                for c in part:
                    if previous and c.box.x - previous.box.x2 > max(.6, c.pdf_style.font_size * .16) and not literal.endswith(' '):
                        literal += ' '
                    literal += c.char_unicode
                    previous = c
                if not literal.strip():
                    continue
                x, y = min(c.box.x for c in part), min(c.box.y for c in part)
                x2, y2 = max(c.box.x2 for c in part), max(c.box.y2 for c in part)
                if x < crop.x - 2 or y < crop.y - 2 or x2 > crop.x2 + 2 or y2 > crop.y2 + 2:
                    continue
                dominant = Counter(c.pdf_style.font_id for c in part).most_common(1)[0][0]
                font = fonts.get(dominant)
                result.append(dict(text=literal.strip(), parent=parent.debug_id, kind=kind,
                                   fontSize=median(c.pdf_style.font_size for c in part),
                                   fontBold=bool(getattr(font, 'bold', False)), fontItalic=bool(getattr(font, 'italic', False)),
                                   tailLeft=(part[-1].box.x - crop.x) / width,
                                   rect=dict(left=max(0, (x - crop.x) / width), top=max(0, (crop.y2 - y2) / height),
                                             width=(x2 - x) / width, height=(y2 - y) / height)))
    return result


def ordered(rows):
    # Require several compact rows in each half before assuming two columns.
    left = [r for r in rows if r['rect']['left'] < .45 and r['rect']['left'] + r['rect']['width'] < .58]
    right = [r for r in rows if r['rect']['left'] >= .45]
    two = len(left) >= 3 and len(right) >= 3
    if not two:
        return sorted(rows, key=lambda r: (r['rect']['top'], r['rect']['left']))
    # Full-width headings partition column flow, instead of being sorted after
    # the entire left column. This also keeps a later appendix outside references.
    spans = sorted([r for r in rows if r['rect']['width'] >= .6], key=lambda r: r['rect']['top'])
    out, remaining = [], [r for r in rows if r not in spans]
    for boundary in [*spans, None]:
        top = boundary['rect']['top'] if boundary else 2
        band = [r for r in remaining if r['rect']['top'] < top]
        remaining = [r for r in remaining if r['rect']['top'] >= top]
        out.extend(sorted(band, key=lambda r: (r['rect']['left'] >= .45, r['rect']['top'], r['rect']['left'])))
        if boundary:
            out.append(boundary)
    return out


def margin(row):
    r, text = row['rect'], row['text']
    if row.get('kind', '').lower() in PROTECTED or r['height'] > .035 or len(text) > 180:
        return ''
    if row.get('kind', '').lower() in ('header', 'footer', 'page_header', 'page_footer'):
        return 'header' if 'header' in row['kind'].lower() else 'footer'
    if r['top'] + r['height'] <= .12:
        return 'header'
    if r['top'] >= .89:
        return 'footer'
    return ''


def margin_key(row):
    return margin(row) + ':' + re.sub(r'\d+', '#', re.sub(r'\s+', ' ', row['text'].lower())).strip()


def joined_entry(kind, page, rows, label='', **extra):
    rects = [r['rect'] for r in rows]
    left, top = min(r['left'] for r in rects), min(r['top'] for r in rects)
    right, bottom = max(r['left'] + r['width'] for r in rects), max(r['top'] + r['height'] for r in rects)
    return dict(kind=kind, pageIndex=page, label=label,
                text=' '.join(r['text'] for r in rows),
                rect=dict(left=left, top=top, width=right-left, height=bottom-top),
                lines=[dict(rect=r['rect'], text=r['text']) for r in rows],
                bodyLeft=min((r['rect']['left'] for r in rows[1:]), default=None),
                fontSize=rows[0].get('fontSize'), fontBold=rows[0].get('fontBold'), fontItalic=rows[0].get('fontItalic'), **extra)


def section_heading(row, body_size):
    return row.get('kind', '').lower() in ('title', 'heading', 'section_header', 'section-title') or (
        row.get('fontBold') and (row.get('fontSize') or body_size) > body_size * 1.08 and len(row['text'].split()) <= 12)


def analyze_rows(pages, settings=None, check=lambda: None):
    """Input is source rows, never already translated text. Does not mutate it."""
    settings = settings or {}
    if len(pages) > 10000:
        raise ValueError('Too many structure pages')
    repeated = defaultdict(set)
    for page in pages:
        for row in page['rows']:
            if margin(row):
                repeated[margin_key(row)].add(page['pageIndex'])
    entries, exclusions, in_refs, previous_page = [], [], False, None
    for page in sorted(pages, key=lambda p: p['pageIndex']):
        check()
        index = page['pageIndex']
        if previous_page is not None and index != previous_page + 1:
            in_refs = False
        previous_page = index
        source = ordered(page['rows'])
        rows = []
        for row in source:
            band = margin(row)
            explicit = row.get('kind', '').lower() in ('header', 'footer', 'page_header', 'page_footer')
            page_number = bool(re.fullmatch(r'[-–—]?\s*\d+\s*[-–—]?', row['text']))
            if band and (explicit or page_number or len(repeated[margin_key(row)]) >= 2):
                if settings.get('ignoreHeadersFooters'):
                    exclusions.append(dict(pageIndex=index, reason='headersFooters', rect=row['rect'], text=row['text']))
                continue
            if row.get('kind', '').lower() not in PROTECTED:
                rows.append(row)
        # Bibliographies without a heading need sequential labels AND multiple
        # publication cues. Ordinary numbered instructions are not references.
        body_size = median(r.get('fontSize') or 10 for r in rows) if rows else 10
        markers = [(i, m, r) for i, r in enumerate(rows) if not section_heading(r, body_size) and (m := REF_MARKER.match(r['text']))]
        confirmed = set()
        for j in range(len(markers)-2):
            triple = markers[j:j+3]
            nums = [int(re.search(r'\d+', m[1]).group()) for _, m, _ in triple]
            texts = [' '.join(r['text'] for r in rows[pos:(markers[j+k+1][0] if j+k+1 < len(markers) else len(rows))]) for k, (pos, _, _) in enumerate(triple)]
            if nums[1] == nums[0]+1 and nums[2] == nums[1]+1 and sum(bool(PUBLICATION.search(t)) for t in texts) >= 2:
                confirmed.add(triple[0][0])
        heading = any(CONTENTS.fullmatch(r['text']) for r in rows)
        toc = []
        for row in rows:
            match = PAGE_TAIL.match(row['text'])
            if not match or not (heading or match[2]):
                continue
            title = re.sub(r'[.·…⋯\s]+$', '', match[1]).strip()
            if len(title) < 2 or CONTENTS.fullmatch(title):
                continue
            if not match[2] and row.get('tailLeft', 0) < row['rect']['left'] + row['rect']['width'] * .65:
                continue
            label = re.match(r'^((?:\d+(?:\.\d+)*[.)]?|[A-Z][.)])\s+)', title)
            item = joined_entry('toc', index, [row], label[1].strip() if label else '', pageLabel=match[3])
            item['text'] = title
            toc.append((row, item))
        if len(toc) >= (2 if heading else 3):
            entries.extend(e for _, e in toc)
            rows = [r for r in rows if not any(r is t for t, _ in toc)]
        reference_rows, list_rows = [], []
        current = None
        for position, row in enumerate(rows):
            check()
            text = row['text']
            if REFERENCES.fullmatch(text) or position in confirmed:
                in_refs = True
            if END.match(text) or STATEMENT.match(text):
                in_refs = False
                current = None
            if in_refs:
                if settings.get('ignoreReferences'):
                    exclusions.append(dict(pageIndex=index, reason='references', rect=row['rect'], text=text))
                if REFERENCES.fullmatch(text):
                    current = None
                    continue
                marker = REF_MARKER.match(text)
                if marker:
                    current = ([row], marker[1], False)
                    reference_rows.append(current)
                elif current and abs(row['rect']['left'] - current[0][0]['rect']['left']) < .12 and row['rect']['top'] >= current[0][-1]['rect']['top']:
                    current[0].append(row)
                else:
                    current = ([row], '', True)
                    reference_rows.append(current)
            else:
                list_rows.append(row)
        if not settings.get('ignoreReferences'):
            entries.extend(joined_entry('reference', index, r, label, continuation=continuation) for r, label, continuation in reference_rows)
        # Build groups before admitting a list: require two consecutive literal
        # numeric/alphabetic markers in a column; exclude dates and prose numbers.
        groups, active = [], None
        for row in list_rows:
            if section_heading(row, body_size):
                active = None
                continue
            marker = LIST_MARKER.match(row['text'])
            if marker:
                label = marker[1]
                token = re.sub(r'[^\w]', '', label)
                category = 'number' if token.isdigit() else 'letter' if token.isalpha() else 'bullet'
                ordinal = int(token) if token.isdigit() else ord(token.lower()) if len(token)==1 else None
                item = ([row], label, category, ordinal)
                if active and category == active[-1][2] and abs(row['rect']['left'] - active[-1][0][0]['rect']['left']) < .04 and (category=='bullet' or ordinal == active[-1][3]+1):
                    active.append(item)
                else:
                    active = [item]
                    groups.append(active)
            elif active:
                prior = active[-1][0][-1]
                gap = row['rect']['top'] - prior['rect']['top'] - prior['rect']['height']
                if -.003 <= gap < max(.018, prior['rect']['height'] * 1.1) and row['rect']['left'] >= active[-1][0][0]['rect']['left']-.01 and row['rect']['left'] < active[-1][0][0]['rect']['left']+.18:
                    active[-1][0].append(row)
                else:
                    active = None
        for group in groups:
            if len(group) >= 2:
                entries.extend(joined_entry('list', index, rows, label) for rows, label, _, _ in group)
    for ordinal, entry in enumerate(entries):
        entry['id'] = f"{entry['kind']}-{entry['pageIndex']}-{ordinal}"
    return dict(revision=REVISION, entries=entries, exclusions=exclusions)


def analyze(document, config):
    check = getattr(config, 'raise_if_cancelled', lambda: None)
    pages = []
    for page in document.page:
        check()
        pages.append(dict(pageIndex=page.page_number, rows=rows_from_page(page)))
    return analyze_rows(pages, getattr(config, 'twintext_document_options', None), check)
