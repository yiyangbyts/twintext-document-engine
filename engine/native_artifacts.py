"""Keep translated IL for local reflow and export; never deserialize client code."""
from __future__ import annotations
import base64,copy,logging,secrets,time
from contextlib import contextmanager
from pathlib import Path

def paragraph_text(paragraph):
    from babeldoc.format.pdf.document_il.utils.layout_helper import get_paragraph_unicode
    return get_paragraph_unicode(paragraph).strip()

@contextmanager
def capture(config,policy,collector):
    from babeldoc.format.pdf import high_level
    translator,typesetter=high_level.ILTranslator,high_level.Typesetting
    sources={}
    class ExportTranslator(translator):
        def translate_paragraph(self,paragraph,page,*args,**kwargs):
            try:sources[(page.page_number,paragraph.debug_id)]=paragraph_text(paragraph)
            except Exception:sources[(page.page_number,paragraph.debug_id)]=paragraph.unicode or ''
            return super().translate_paragraph(paragraph,page,*args,**kwargs)
    class ExportTypesetting(typesetter):
        def typesetting_document(self,document):
            # Snapshot before typesetting mutates composition/glyph geometry.
            # Large documents remain translatable without retaining a second
            # whole IL in memory; cached paragraph replies support later reflow.
            try:
                size=sum(len(p.unicode or '') for page in document.page for p in page.pdf_paragraph)
                if len(document.page)<=256 and size<=2_000_000:
                    collector.update(document=copy.deepcopy(document),prepared=Path(config.get_working_file_path('input.pdf')).read_bytes(),
                        sources=sources.copy(),references={p.page_number:policy.snapshot(p.page_number) for p in document.page} if policy else {},
                        preserved=list(getattr(config,'twintext_preserved_regions',[])),
                        preserved_ids=set(policy.preserved) if policy else set())
            except Exception as error:
                config.raise_if_cancelled();logging.getLogger(__name__).warning('Optional reflow snapshot unavailable: %s',error)
            return super().typesetting_document(document)
    high_level.ILTranslator=ExportTranslator;high_level.Typesetting=ExportTypesetting
    try:yield
    finally:high_level.ILTranslator=translator;high_level.Typesetting=typesetter

def text_pages(artifact):
    pages=[]
    for page in artifact['document'].page:
        plans=artifact['references'].get(page.page_number,[])
        parents={key for e in plans if e['translated'] for key in e['parents']}
        blocks=[];placed=set()
        def add_entry(e):
            label=e['label'].unicode or '';tail=e.get('tail');suffix=(' '+tail.unicode) if tail and tail.unicode else ''
            blocks.append({'source':(label+' '+e['sourceText']+suffix).strip(),
                'translation':(label+' '+paragraph_text(e['paragraph'])+suffix).strip(),'kind':e['kind']})
            placed.add(e['id'])
        for p in page.pdf_paragraph:
            if p.debug_id in parents:
                for e in plans:
                    if e['translated'] and p.debug_id in e['parents'] and e['id'] not in placed:add_entry(e)
                continue
            if p.debug_id in artifact['preserved_ids']:continue
            translated=paragraph_text(p)
            source=artifact['sources'].get((page.page_number,p.debug_id),translated)
            if not translated:continue
            kind='heading' if any(x in str(p.layout_label).lower() for x in ('title','heading','header')) else 'paragraph'
            blocks.append({'source':source,'translation':translated,'kind':kind,'x':p.box.x,'y':p.box.y2})
        for e in plans:
            if e['translated'] and e['id'] not in placed:add_entry(e)
        pages.append({'index':page.page_number,'blocks':[{k:v for k,v in b.items() if k not in ('x','y')} for b in blocks]})
    return pages

class ArtifactStore:
    def __init__(self):self.values={}
    def put(self,artifact):
        now=time.monotonic()
        self.values={k:v for k,v in self.values.items() if now-v['accessed']<3600}
        while len(self.values)>=2:self.values.pop(min(self.values,key=lambda k:self.values[k]['accessed']))
        key=secrets.token_hex(16);self.values[key]={'artifact':artifact,'accessed':now};return key
    def get(self,key):
        item=self.values.get(key)
        if not item or time.monotonic()-item['accessed']>=3600:raise ValueError('native_artifact_expired')
        item['accessed']=time.monotonic();return item['artifact']

def finalize(source,output,preserved,config,isolation=False,canonical=None):
    from preserved_regions import restore
    import pymupdf
    output=restore(canonical or source,output,preserved,isolation,config)
    from page_geometry import restore_content
    with pymupdf.open(stream=source,filetype='pdf') as original:selected=[i for i in range(original.page_count) if config.should_translate_page(i+1)]
    output=restore_content(output,getattr(config,'twintext_content_rotations',{}),selected,isolation)
    with pymupdf.open(stream=source,filetype='pdf') as original,pymupdf.open(stream=output,filetype='pdf') as translated:
        if translated.page_count!=(1 if isolation else original.page_count):raise ValueError('Native PDF page alignment failed')
        if not isolation and config.pages:
            toc=original.get_toc(simple=False)
            for index in range(original.page_count):
                if config.should_translate_page(index+1):
                    original.delete_page(index);original.insert_pdf(translated,from_page=index,to_page=index,start_at=index)
            if toc:original.set_toc(toc)
            output=original.tobytes(garbage=3,deflate=True)
    return output

def reflow(artifact,folder,raw,cancel):
    from asset_paths import configure
    configure()
    from babeldoc.format.pdf.translation_config import TranslationConfig,WatermarkOutputMode
    from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
    from babeldoc.format.pdf.document_il.backend.pdf_creater import PDFCreater
    from document_options import make_typesetter,options
    from document_preview import QuietProgress
    from reference_layout import render_references
    from babeldoc.format.pdf.high_level import fix_media_box
    import pymupdf
    folder.mkdir(parents=True,exist_ok=True)
    canonical=artifact.get('canonicalSource',artifact['source'])
    source=folder/'source.pdf';source.write_bytes(canonical)
    prepared=folder/'prepared.pdf';prepared.write_bytes(artifact['prepared'])
    config=TranslationConfig(translator=None,input_file=source,lang_in=artifact['langIn'],lang_out=artifact['langOut'],
        doc_layout_model=object(),working_dir=folder/'work',output_dir=folder/'output',pages=artifact['pages'],
        no_dual=True,only_include_translated_page=artifact['isolation'],watermark_output_mode=WatermarkOutputMode.NoWatermark)
    config.progress_monitor=QuietProgress(cancel);config.primary_font_family=options(raw)['fontFamily']
    config.twintext_preserved_regions=artifact['preserved']
    config.twintext_content_rotations=artifact.get('contentRotations',{})
    class ReflowTypesetting(make_typesetter(Typesetting,raw)):
        def render_page(self,page):
            page.pdf_paragraph=[p for p in page.pdf_paragraph if p.debug_id not in artifact['preserved_ids']]
            result=super().render_page(page)
            render_references(page,artifact['references'].get(page.page_number,[]),self)
            return result
    document=copy.deepcopy(artifact['document'])
    ReflowTypesetting(config).typesetting_document(document)
    with pymupdf.open(source) as pdf:boxes=fix_media_box(pdf)
    result=PDFCreater(prepared,document,config,boxes).write(config)
    output=finalize(artifact['source'],Path(result.mono_pdf_path).read_bytes(),artifact['preserved'],config,artifact['isolation'],canonical)
    return {'pdf':base64.b64encode(output).decode(),'pageCount':artifact['pageCount'],'pipeline':'native-pdf-9020','engine':'babeldoc'}

def open_pdf(payload,field):
    import pymupdf
    from service import pdf_input
    data=pdf_input(payload,field)
    return pymupdf.open(data) if isinstance(data,Path) else pymupdf.open(stream=data,filetype='pdf')


def exported(output,payload,pipeline,count):
    if payload.get('outputFile'):
        from native_batches import digest
        destination=Path(payload['outputFile'])
        if any(destination.resolve()==Path(payload[name]).resolve() for name in ('sourceFile','translatedFile') if payload.get(name)):raise ValueError('Cannot overwrite input PDF')
        destination.parent.mkdir(parents=True,exist_ok=True)
        temporary=destination.with_name(destination.name+'.tmp');output.save(temporary,garbage=3,deflate=True);temporary.replace(destination)
        return dict(pdfFile=str(destination),size=destination.stat().st_size,sha256=digest(destination),pageCount=count,pipeline=pipeline)
    return dict(pdf=base64.b64encode(output.tobytes(garbage=3,deflate=True)).decode(),pageCount=count,pipeline=pipeline)


def comparison(payload):
    import pymupdf
    first,last=payload.get('first'),payload.get('last')
    with open_pdf(payload,'pdf') as original,open_pdf(payload,'translatedPDF') as target,pymupdf.open() as output:
        if original.page_count!=target.page_count or any(isinstance(n,bool) or not isinstance(n,int) for n in (first,last)) or not 0<=first<=last<original.page_count:raise ValueError('Invalid comparison range')
        for index in range(first,last+1):
            a,b=original[index],target[index];gap=12
            page=output.new_page(width=a.rect.width+b.rect.width+gap,height=max(a.rect.height,b.rect.height))
            page.show_pdf_page(pymupdf.Rect(0,0,a.rect.width,a.rect.height),original,index)
            page.show_pdf_page(pymupdf.Rect(a.rect.width+gap,0,a.rect.width+gap+b.rect.width,b.rect.height),target,index)
        return exported(output,payload,'native-comparison-9035',last-first+1)


def extract(payload):
    import pymupdf
    first,last=payload.get('first'),payload.get('last')
    with open_pdf(payload,'translatedPDF') as document,pymupdf.open() as output:
        if any(isinstance(n,bool) or not isinstance(n,int) for n in (first,last)) or not 0<=first<=last<document.page_count:raise ValueError('Invalid PDF export range')
        output.insert_pdf(document,from_page=first,to_page=last)
        return exported(output,payload,'native-export-9035',last-first+1)
