"""Apply reader format to native typesetting, preserving source formula units."""
from contextlib import contextmanager

def options(value):
    value=value if isinstance(value,dict) else {}
    def scale(key,low,high):
        n=value.get(key,100)
        if isinstance(n,bool) or not isinstance(n,(int,float)):n=100
        return max(low,min(high,n))/100
    return {'fontScale':scale('fontScale',70,160),'lineHeightScale':scale('lineHeightScale',80,180),
        'fontFamily':{'serif':'serif','sans':'sans-serif'}.get(value.get('fontFamily')),
        'ignoreReferences':value.get('ignoreReferences') is True,'ignoreHeadersFooters':value.get('ignoreHeadersFooters') is True}

def make_typesetter(base, raw):
    settings=options(raw)
    class ReaderTypesetting(base):
        def create_typesetting_units(self,paragraph,fonts):
            units=super().create_typesetting_units(paragraph,fonts)
            if settings['fontScale'] != 1:
                for unit in units:
                    # A source glyph or math formula must keep its original geometry.
                    if unit.unicode is not None and unit.font_size:
                        unit.font_size*=settings['fontScale']
            return units
        def _layout_typesetting_units(self,units,box,scale,line_skip,paragraph,*args,**kwargs):
            return super()._layout_typesetting_units(units,box,scale,line_skip*settings['lineHeightScale'],paragraph,*args,**kwargs)
    return ReaderTypesetting

@contextmanager
def document_options(config, raw):
    from babeldoc.format.pdf import high_level
    original=high_level.Typesetting
    settings=options(raw)
    config.primary_font_family=settings['fontFamily']
    config.twintext_document_options=raw or {}
    high_level.Typesetting=make_typesetter(original,raw)
    try:yield
    finally:high_level.Typesetting=original
