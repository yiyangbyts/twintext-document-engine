"""Reject silent blank pages so existing page isolation can preserve the source."""
from __future__ import annotations


def validate(source, output, selected, isolated=False):
    import pymupdf
    with pymupdf.open(stream=source, filetype='pdf') as original, pymupdf.open(stream=output, filetype='pdf') as translated:
        for position, index in enumerate(selected):
            page = translated[position if isolated else index]
            if page.get_text().strip() or page.get_images() or page.get_drawings():
                continue
            # Do not turn a deliberately empty source page into a failure.
            if len(original[index].get_text().strip()) >= 20:
                raise ValueError(f'Native PDF output lost page content: {index + 1}')
