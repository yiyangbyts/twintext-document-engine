"""Compatibility fixes for BabelDOC's lazy graphics and input PDF lifetime."""
from contextlib import contextmanager
import logging

def materialized_copy(self,memo):
    # GraphicState.passthrough_per_char_instruction is a string field. The
    # lazy wrapper's persistent parent chain can contain thousands of nodes.
    # Render it iteratively before copying; preserve exactly the PDF commands,
    # including clipping and suffixes, without copying or pickling that chain.
    value=self.materialize();memo[id(self)]=value
    return value

def install_graphics_copy():
    from babeldoc.format.pdf.document_il.frontend.il_creater_active_support import LazyPassthroughInstruction
    if '__deepcopy__' not in LazyPassthroughInstruction.__dict__:
        LazyPassthroughInstruction.__deepcopy__=materialized_copy

@contextmanager
def input_documents():
    """Close only documents opened by this synchronous translation pipeline.

    Upstream keeps the source document in reference cycles after returning.
    Windows cannot remove its temporary source.pdf until the handle closes.
    Do not patch pymupdf.open globally: preview rendering is a separate process.
    """
    from babeldoc.format.pdf import high_level
    opened=[];original=high_level.open_pdf_with_save_fallback
    metadata=high_level.check_metadata;constructor=high_level.Document
    def created(*args,**kwargs):
        document=constructor(*args,**kwargs);opened.append(document);return document
    def tracked(*args,**kwargs):
        document=original(*args,**kwargs);opened.append(document);return document
    def checked(document):
        try:return metadata(document)
        finally:
            if not document.is_closed:document.close()
    high_level.Document=created
    high_level.open_pdf_with_save_fallback=tracked;high_level.check_metadata=checked
    try:yield
    finally:
        high_level.Document=constructor
        high_level.open_pdf_with_save_fallback=original;high_level.check_metadata=metadata
        for document in opened:
            try:
                if not document.is_closed:document.close()
            except Exception:
                logging.getLogger(__name__).warning('Input PDF handle cleanup deferred',exc_info=True)
