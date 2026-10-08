"""Structured entry composition after BabelDOC's normal body typesetting.

The engine plans entries directly from source glyphs. Original paragraphs still
participate in upstream translation and global font sizing unchanged. Shadows
are translated independently; only fully covered reference paragraphs are
replaced, after body glyph positions have been finalized. Numbered instructions
and contents rows use the same conservative coverage and independent slots.
"""
from __future__ import annotations
import copy,logging,re,threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from structure_plan import REVISION,analyze
log=logging.getLogger(__name__)

def characters(composition):
    if composition.pdf_character:return [composition.pdf_character]
    for name in ('pdf_line','pdf_same_style_characters','pdf_formula'):
        value=getattr(composition,name,None)
        if value:return value.pdf_character
    return []

def inside(char,box,tolerance=2):
    b=char.box
    return b is not None and box.x-tolerance<=b.x<=box.x2+tolerance and box.y-tolerance<=b.y<=box.y2+tolerance

def pdf_box(rect,page):
    from babeldoc.format.pdf.document_il.il_version_1 import Box
    crop=page.cropbox.box;w=crop.x2-crop.x;h=crop.y2-crop.y
    values=[rect.get(k) for k in ('left','top','width','height')]
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) for v in values):raise ValueError('Invalid reference rectangle')
    x,y,width,height=values
    if min(x,y)<0 or min(width,height)<=0 or x+width>1.001 or y+height>1.001:raise ValueError('Invalid reference bounds')
    return Box(x=crop.x+x*w,y=crop.y2-(y+height)*h,x2=crop.x+(x+width)*w,y2=crop.y2-y*h)

def bibliography_text_formula(formula,page):
    if getattr(formula,'pdf_curve',[]) or getattr(formula,'pdf_form',[]):return False
    fonts={f.font_id:f.name or '' for f in page.pdf_font}
    for c in formula.pdf_character:
        text=c.char_unicode or ''
        if re.search(r'[α-ωΑ-Ω∑∏∫√∞∂∇=+<>]',text) or re.search(r'(?i)math|symbol|cmmi|cmsy|cmex',fonts.get(c.pdf_style.font_id,'')):return False
    return True

def text_compositions(chars):
    from babeldoc.format.pdf.document_il.il_version_1 import PdfParagraphComposition,PdfSameStyleCharacters,Box
    bounds=Box(x=min(c.box.x for c in chars),y=min(c.box.y for c in chars),x2=max(c.box.x2 for c in chars),y2=max(c.box.y2 for c in chars))
    return [PdfParagraphComposition(pdf_same_style_characters=PdfSameStyleCharacters(box=bounds,pdf_style=copy.deepcopy(chars[0].pdf_style),pdf_character=copy.deepcopy(chars)))]

def entry_type(entries,eid):return next(e.get('kind','reference') for e in entries if e['id']==eid)

def source_shadows(page,entries):
    """Reject mixed body/reference parents; never erase an uncertain paragraph."""
    from babeldoc.format.pdf.document_il.il_version_1 import PdfParagraphComposition
    parents={p.debug_id:p for p in page.pdf_paragraph if p.debug_id and p.pdf_style and p.pdf_paragraph_composition and not p.vertical}
    boxes={e['id']:pdf_box(e['rect'],page) for e in entries}
    # The standard parser can omit an isolated numeric DOI tail. Reserve its
    # one-line gap only between confirmed entries in the same column. Never
    # extend the last entry into an appendix or declaration below it.
    for eid,box in boxes.items():
        if entry_type(entries,eid)!='reference':continue
        below=[b for other,b in boxes.items() if other!=eid and abs(b.x-box.x)<24 and b.y2<box.y2]
        if below:
            next_box=max(below,key=lambda b:b.y2)
            if 0<box.y-next_box.y2<=16:box.y=min(box.y,next_box.y2+1.5)
    selected={};coverage={};templates={}
    for key,parent in parents.items():
        chars=[c for comp in parent.pdf_paragraph_composition for c in characters(comp)]
        if not chars:continue
        memberships={id(c):[e['id'] for e in entries if inside(c,boxes[e['id']])] for c in chars}
        # Adjacent entries can have touching boundaries, but each glyph must
        # belong to exactly one source entry. Whitespace outside is harmless.
        if any(len(memberships[id(c)])!=1 for c in chars if (c.char_unicode or '').strip()):continue
        ids={v[0] for c in chars if (v:=memberships[id(c)]) and len(v)==1}
        if not ids:continue
        coverage[key]=ids
        for eid in ids:
            selected.setdefault(eid,[]);templates.setdefault(eid,parent)
            for comp in parent.pdf_paragraph_composition:
                kept=[c for c in characters(comp) if memberships[id(c)]==[eid]]
                if not kept:continue
                if comp.pdf_formula and len(kept)!=len(characters(comp)):
                    if entry_type(entries,eid) in ('reference','toc') and bibliography_text_formula(comp.pdf_formula,page):
                        selected[eid].extend(text_compositions(kept));continue
                    coverage.pop(key,None);selected[eid]=[];break
                clone=copy.deepcopy(comp)
                if clone.pdf_character:clone.pdf_character=copy.deepcopy(kept[0])
                else:
                    for name in ('pdf_line','pdf_same_style_characters','pdf_formula'):
                        value=getattr(clone,name,None)
                        if value:value.pdf_character=copy.deepcopy(kept)
                selected[eid].append(clone)
    # A shared entry must be covered by all of its native parents. Otherwise a
    # partial replacement would duplicate or omit the unclassified remainder.
    invalid=set()
    for key,parent in parents.items():
        if key in coverage:continue
        for eid,box in boxes.items():
            if any(inside(c,box) for comp in parent.pdf_paragraph_composition for c in characters(comp) if (c.char_unicode or '').strip()):invalid.add(eid)
    valid={eid for eid in selected if selected[eid] and eid not in invalid}
    changed=True
    while changed:
        changed=False
        for ids in coverage.values():
            if ids-valid:
                old=len(valid);valid-=ids;changed|=len(valid)!=old
    result=[]
    for entry in entries:
        eid=entry['id']
        if eid not in valid:continue
        paragraph=copy.deepcopy(templates[eid]);paragraph.debug_id=eid
        paragraph.box=copy.deepcopy(boxes[eid]);paragraph.first_line_indent=False
        paragraph.pdf_paragraph_composition=selected[eid]
        chars=[c for comp in selected[eid] for c in characters(comp)]
        # Separate shadows from a merged parent must not reuse its draw order.
        # Otherwise PDF text extraction interleaves the first glyph of every
        # row, even though the page looks correct. Keep each source entry's
        # earliest draw order and use a continuous order for label/body/tail.
        paragraph.render_order=min((c.render_order for c in chars if getattr(c,'render_order',None) is not None),default=getattr(paragraph,'render_order',None))
        if entry.get('kind') in ('list','toc'):
            styles=Counter((c.pdf_style.font_id,c.pdf_style.font_size) for c in chars if (c.char_unicode or '').strip())
            if styles:
                style=styles.most_common(1)[0][0]
                paragraph.pdf_style=copy.deepcopy(next(c.pdf_style for c in chars if (c.pdf_style.font_id,c.pdf_style.font_size)==style))
        label=entry.get('label','');label_chars=[]
        if label:
            first=sorted((c for c in chars if c.box.y2>=paragraph.box.y2-max(3,paragraph.pdf_style.font_size*.75)),key=lambda c:c.box.x)
            literal='';count=0;compact_label=re.sub(r'\s','',label)
            for c in first:
                literal+=(c.char_unicode or '').strip();count+=1
                if literal==compact_label:label_chars=first[:count];break
                if not compact_label.startswith(literal):break
            if not label_chars:continue
        tail_chars=[];page_chars=[]
        if entry.get('kind')=='toc':
            ordered=sorted(chars,key=lambda c:c.box.x);literal=''
            for c in reversed(ordered):
                literal=(c.char_unicode or '').strip()+literal;page_chars.insert(0,c)
                if literal==entry.get('pageLabel'):break
                if not entry.get('pageLabel','').endswith(literal):page_chars=[];break
            if not page_chars:continue
            at=ordered.index(page_chars[0]);leaders=[]
            for c in reversed(ordered[:at]):
                if re.fullmatch(r'[.·…⋯\s]*',c.char_unicode or ''):leaders.insert(0,c)
                else:break
            tail_chars=leaders+page_chars
            paragraph.box.x2=min(c.box.x for c in page_chars)-paragraph.pdf_style.font_size
        label_ids={id(c) for c in [*label_chars,*tail_chars]}
        cleaned=[]
        for comp in paragraph.pdf_paragraph_composition:
            kept=[c for c in characters(comp) if id(c) not in label_ids]
            if not kept:continue
            if comp.pdf_formula and len(kept)!=len(characters(comp)):
                if entry.get('kind','reference') in ('reference','toc') and bibliography_text_formula(comp.pdf_formula,page):
                    cleaned.extend(text_compositions(kept));continue
                cleaned=[];break
            if comp.pdf_character:comp.pdf_character=kept[0]
            else:
                for name in ('pdf_line','pdf_same_style_characters','pdf_formula'):
                    value=getattr(comp,name,None)
                    if value:value.pdf_character=kept
            cleaned.append(comp)
        if not cleaned:continue
        paragraph.pdf_paragraph_composition=cleaned
        paragraph.unicode=re.sub(r'^\s*'+re.escape(label)+r'\s*','',entry['text'],count=1) if label else entry['text']
        crop=page.cropbox.box
        left=entry.get('bodyLeft')
        body_left=crop.x+left*(crop.x2-crop.x) if isinstance(left,(int,float)) and not isinstance(left,bool) else paragraph.box.x
        if label_chars:body_left=max(body_left,max(c.box.x2 for c in label_chars)+paragraph.pdf_style.font_size*.35)
        first_body=[c for comp in cleaned for c in characters(comp) if (c.char_unicode or '').strip() and c.box.y2>=paragraph.box.y2-max(3,paragraph.pdf_style.font_size*.75)]
        if first_body:body_left=max(body_left,min(c.box.x for c in first_body))
        paragraph.box.x=body_left
        labels=copy.deepcopy(templates[eid]);labels.debug_id=eid+'-label';labels.unicode=label
        labels.first_line_indent=False;labels.pdf_paragraph_composition=[PdfParagraphComposition(pdf_character=copy.deepcopy(c)) for c in label_chars]
        tail=copy.deepcopy(labels);tail.debug_id=eid+'-page';tail.unicode=entry.get('pageLabel','')
        tail.pdf_paragraph_composition=[PdfParagraphComposition(pdf_character=copy.deepcopy(c)) for c in tail_chars]
        result.append({'id':eid,'kind':entry.get('kind','reference'),'fontBold':entry.get('fontBold'),'fontItalic':entry.get('fontItalic'),'sourceText':paragraph.unicode,'paragraph':paragraph,'label':labels,'tail':tail,'baseline':max((c.box.y for c in first_body),default=paragraph.box.y2-paragraph.pdf_style.font_size),
            'parents':sorted(k for k,v in coverage.items() if eid in v),'translated':False,'box':boxes[eid]})
    # Dropping a missing label/formula entry must also drop the whole parent.
    ready={e['id'] for e in result}
    while True:
        bad={eid for ids in coverage.values() if ids-ready for eid in ids};new=ready-bad
        if new==ready:break
        ready=new
    return [e for e in result if e['id'] in ready]

def render_references(page,plan,typesetter):
    """Confine shadows to source reference slots. Body objects are not touched."""
    if not plan:return
    from babeldoc.format.pdf.document_il.il_version_1 import PdfParagraphComposition
    fonts={f.font_id:f for f in page.pdf_font if f.font_id};fonts.update(typesetter.font_mapper.fontid2font)
    for xobj in page.pdf_xobject:
        if xobj.xobj_id is not None:fonts[xobj.xobj_id]={f.font_id:f for f in [*page.pdf_font,*xobj.pdf_font] if f.font_id}
    # Use a consistent scale within each reference column. Each entry keeps
    # its source start and reserves a gap before the next entry.
    columns=[]
    for entry in sorted(copy.deepcopy(plan),key=lambda e:(e['box'].x,-e['box'].y2)):
        column=next((c for c in columns if c[0].get('kind')==entry.get('kind') and abs(c[0]['box'].x-entry['box'].x)<24),None)
        if column is None:column=[];columns.append(column)
        column.append(entry)
    rendered={};failures=set();orders=Counter()
    # OCR workaround clears drawing orders. The upstream creator maps a null
    # order/suborder to 9999999999999999, including its white masks. Keep new
    # source labels/page numbers above those masks instead of erasing them.
    orders[None]=10**16
    for column in columns:
        column.sort(key=lambda e:-e['box'].y2)
        right=max(e['box'].x2 for e in column)
        for i,e in enumerate(column):
            p=e['paragraph'];p.box.x2=min(p.box.x2,right) if e.get('kind')=='toc' else right
            if i+1<len(column):p.box.y=max(p.box.y,column[i+1]['box'].y2+1.5)
        units={}
        for e in column:
            if not e['translated']:continue
            scoped=fonts.copy();p=e['paragraph'];scope=scoped
            if p.xobj_id in scoped:scope=scoped[p.xobj_id].copy();scoped[p.xobj_id]=scope
            source_font=scope.get(p.pdf_style.font_id)
            if source_font and hasattr(source_font,'bold') and e.get('kind') in ('toc','list'):
                source_font=copy.copy(source_font);scope[p.pdf_style.font_id]=source_font
                if isinstance(e.get('fontBold'),bool):source_font.bold=e['fontBold']
                if isinstance(e.get('fontItalic'),bool):source_font.italic=e['fontItalic']
            units[e['id']]=typesetter.create_typesetting_units(p,scoped)
        chosen=None
        for scale in (1,.95,.9,.85,.8,.75,.7,.65,.6,.55,.5):
            layouts={};fits=True
            for e in column:
                if not e['translated']:continue
                p=e['paragraph'];laid,fit=typesetter._layout_typesetting_units(units[e['id']],p.box,scale,1.15,p)
                if not fit or not laid or any(u.box.x<p.box.x-.1 or u.box.x2>p.box.x2+1 or u.box.y<p.box.y-.1 for u in laid):fits=False;break
                layouts[e['id']]=laid
            if fits:chosen=(scale,layouts);break
        if chosen is None:
            failures.update(k for e in column for k in e['parents']);continue
        scale,layouts=chosen
        for e in column:
            p=e['paragraph'];label=e['label']
            if e['translated']:
                laid=layouts[e['id']];p.scale=scale
                p.pdf_paragraph_composition=[];extra_curves=[];extra_forms=[]
                for unit in laid:
                    chars,curves,forms=unit.render()
                    p.pdf_paragraph_composition.extend(PdfParagraphComposition(pdf_character=c) for c in chars)
                    extra_curves.extend(curves);extra_forms.extend(forms)
                if not p.pdf_paragraph_composition:
                    failures.update(e['parents']);continue
                if label.pdf_paragraph_composition:
                    # Keep numbering as source glyphs, aligned with the first
                    # translated baseline. No provider can renumber an entry.
                    original=[c for comp in label.pdf_paragraph_composition for c in characters(comp)]
                    baseline=max(u.box.y for u in laid if abs(u.box.y2-max(v.box.y2 for v in laid))<p.pdf_style.font_size)
                    top=max(c.box.y for c in original);shift=baseline-top
                    for c in original:
                        c.box.y+=shift;c.box.y2+=shift
                        if c.visual_bbox:c.visual_bbox.box.y+=shift;c.visual_bbox.box.y2+=shift
            else:
                p.pdf_paragraph_composition=typesetter.create_passthrough_composition(typesetter.create_typesetting_units(p,fonts))
                extra_curves=[];extra_forms=[]
            tail=e.get('tail')
            if tail and e['translated']:
                end=max(u.box.x2 for u in layouts[e['id']]);chars=[c for comp in tail.pdf_paragraph_composition for c in characters(comp)]
                tail.pdf_paragraph_composition=[PdfParagraphComposition(pdf_character=c) for c in chars if (c.char_unicode or '').strip() not in '.·…⋯' or c.box.x>=end+p.pdf_style.font_size*.35]
                baseline=max(u.box.y for u in layouts[e['id']] if abs(u.box.y2-max(v.box.y2 for v in layouts[e['id']]))<p.pdf_style.font_size)
                shift=baseline-e.get('baseline',baseline)
                for c in chars:
                    c.box.y+=shift;c.box.y2+=shift
                    if c.visual_bbox:c.visual_bbox.box.y+=shift;c.visual_bbox.box.y2+=shift
            # Native glyphs can share one drawing order across several source
            # entries. Reserve a distinct continuous suborder for each entry;
            # otherwise extraction interleaves every row's first character.
            sequence=orders[p.render_order]
            for part in (label,p,tail):
                if not part:continue
                part.render_order=p.render_order
                for composition in part.pdf_paragraph_composition:
                    for c in characters(composition):
                        sequence+=1;c.render_order=p.render_order;c.sub_render_order=sequence
            orders[p.render_order]=sequence
            rendered[e['id']]=(p,label,tail,e['parents'],extra_curves,extra_forms)
    # Connected entries can span several native fragments. Roll back every
    # member if any fragment failed, leaving BabelDOC's existing result.
    while True:
        old=len(failures)
        for e in plan:
            if e['id'] not in rendered or failures.intersection(e['parents']):failures.update(e['parents'])
        if len(failures)==old:break
    replacement={};removed=set()
    for eid,(p,label,tail,parents,curves,forms) in rendered.items():
        if failures.intersection(parents):continue
        removed.update(parents);replacement.setdefault(parents[0],[]).extend([p,*([label] if label.pdf_paragraph_composition else []),*([tail] if tail and tail.pdf_paragraph_composition else [])])
        page.pdf_curve.extend(curves);page.pdf_form.extend(forms)
    page.pdf_paragraph=[new for p in page.pdf_paragraph for new in (replacement.get(p.debug_id,[]) if p.debug_id in removed else [p])]

class ReferencePolicy:
    def __init__(self,config,publish=None):
        self.config=config;self.publish=publish;self.plans={};self.preserved=set();self.lock=threading.RLock()
    def prepare(self,document):
        response=analyze(document,self.config)
        if not isinstance(response,dict) or response.get('revision')!=REVISION:return
        entries=response.get('entries',[])
        if not isinstance(entries,list) or len(entries)>10000:raise ValueError('Invalid reference entries')
        exclusions=response.get('exclusions',[])
        if not isinstance(exclusions,list) or len(exclusions)>20000:raise ValueError('Invalid ignored regions')
        self.config.twintext_preserved_regions=exclusions
        from ignored_regions import split
        for page in document.page:
            self.preserved.update(split(page,exclusions))
            chosen=[e for e in entries if e.get('pageIndex')==page.page_number and e.get('kind','reference') in ('reference','list','toc') and isinstance(e.get('id'),str) and isinstance(e.get('text'),str) and len(e['text'])<=40000 and isinstance(e.get('label',''),str) and len(e.get('label',''))<=16 and re.fullmatch(r'(?:\[\d{1,4}\]|[（(]?[\dA-Za-z]+(?:\.\d+)*[.)）、．]?|[•●◦▪▫‣⁃∙]|Model\s+[A-Z][.:])?',e.get('label',''))]
            self.plans[page.page_number]=source_shadows(page,chosen)
    def snapshot(self,index):
        with self.lock:return copy.deepcopy(self.plans.get(index,[]))
    def contains(self,key):
        return any(key in entry['parents'] for plan in self.plans.values() for entry in plan)
    def translate(self,translator,document,stream=None):
        from babeldoc.format.pdf.document_il.midend.il_translator import ParagraphTranslateTracker
        pages={p.page_number:p for p in document.page}
        def entry(index,e):
            self.config.raise_if_cancelled();page=pages[index]
            fonts={f.font_id:f for f in page.pdf_font if f.font_id}
            xfonts={x.xobj_id:{f.font_id:f for f in [*page.pdf_font,*x.pdf_font] if f.font_id} for x in page.pdf_xobject if x.xobj_id is not None}
            paragraph=copy.deepcopy(e['paragraph'])
            class EntryProgress:
                def advance(self):pass
            translator.translate_paragraph(paragraph,page,pbar=EntryProgress(),tracker=ParagraphTranslateTracker(),page_font_map=fonts,xobj_font_map=xfonts)
            self.config.raise_if_cancelled()
            with self.lock:e['paragraph']=paragraph;e['translated']=paragraph.unicode!=e['sourceText']
            if stream:stream.reference_updated(index,self.snapshot(index))
        with ThreadPoolExecutor(max_workers=self.config.pool_max_workers) as pool:
            work=[pool.submit(entry,index,e) for index,entries in self.plans.items() for e in entries]
            for future in work:future.result()

@contextmanager
def reference_layout(config,publish=None):
    from babeldoc.format.pdf import high_level
    original_translator=high_level.ILTranslator;original_typesetter=high_level.Typesetting
    policy=ReferencePolicy(config,publish)
    class ReferenceTranslator(original_translator):
        def translate_paragraph(self,paragraph,page,pbar=None,*args,**kwargs):
            if paragraph.layout_label=='twintext-preserved' or paragraph.debug_id in policy.preserved:
                if pbar:pbar.advance()
                return
            return super().translate_paragraph(paragraph,page,pbar,*args,**kwargs)
        def translate(self,document):
            try:policy.prepare(document)
            except Exception as error:
                config.raise_if_cancelled();log.warning('Reference layout preparation skipped: %s',error);policy.plans={}
            self._reference_policy=policy
            stream=getattr(self,'_reference_stream',None)
            if stream:
                if policy.preserved:stream.prepare(document,config,force=True)
                for index in policy.plans:stream.reference_updated(index,policy.snapshot(index))
            result=super().translate(document)
            # Upstream paragraphs remain intact for its global sizing pass.
            shadow_translator=original_translator(self.translate_engine,config)
            try:policy.translate(shadow_translator,document,getattr(self,'_reference_stream',None))
            except Exception as error:
                config.raise_if_cancelled();log.warning('Reference translation kept upstream output: %s',error);policy.plans={}
            return result
    class ReferenceTypesetting(original_typesetter):
        def render_page(self,page):
            # Omit confirmed ignored text from reconstruction. Its exact source
            # PDF content is restored as clipped vector content at export.
            page.pdf_paragraph=[p for p in page.pdf_paragraph if p.debug_id not in policy.preserved]
            result=super().render_page(page)
            try:render_references(page,policy.snapshot(page.page_number),self)
            except Exception as error:log.warning('Reference layout kept upstream output: %s',error)
            return result
    high_level.ILTranslator=ReferenceTranslator;high_level.Typesetting=ReferenceTypesetting
    try:yield policy
    finally:high_level.ILTranslator=original_translator;high_level.Typesetting=original_typesetter
