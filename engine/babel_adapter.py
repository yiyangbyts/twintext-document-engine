"""BabelDOC's native PDF parser and typesetter, isolated in a local process."""
from __future__ import annotations
import json
from contextlib import nullcontext
from pathlib import Path
from adapters import rect,region

def value(item,snake,camel):return item.get(snake,item.get(camel))
def il_regions(document):
    result=[]
    for page in document.get('page',[]):
        media=page.get('cropbox',page['mediabox'])['box'];width=media['x2']-media['x'];height=media['y2']-media['y']
        def box(item):
            b=item['box'];return rect([b['x']-media['x'],media['y2']-b['y2'],b['x2']-media['x'],media['y2']-b['y']],width,height)
        for paragraph in value(page,'pdf_paragraph','pdfParagraph') or []:
            result.append(region('body',box(paragraph),paragraph.get('unicode','')))
            for composition in value(paragraph,'pdf_paragraph_composition','pdfParagraphComposition') or []:
                formula=value(composition,'pdf_formula','pdfFormula')
                if formula:
                    chars=value(formula,'pdf_character','pdfCharacter') or []
                    text=''.join(str(value(c,'char_unicode','charUnicode') or '') for c in chars)
                    result.append(region('inline',box(formula),text))
    return result

def run(pdf,folder,payload,bridge=None,progress=None,cancel_event=None,on_preview=None,on_control=None,collector=None):
    if bridge and (isinstance(pdf,Path) or len(pdf)>8*1024*1024):
        from native_batches import run_document
        return run_document(pdf,folder,payload,_run_single,bridge,progress,cancel_event,on_preview,on_control,collector)
    # Even compact books need bounded IL; compressed PDF bytes can be small.
    if bridge:
        import pymupdf
        with pymupdf.open(stream=pdf,filetype='pdf') as document:
            if document.page_count>16:
                from native_batches import run_document
                return run_document(pdf,folder,payload,_run_single,bridge,progress,cancel_event,on_preview,on_control,collector)
    if isinstance(pdf,Path):pdf=pdf.read_bytes()
    return _run_single(pdf,folder,payload,bridge,progress,cancel_event,on_preview,on_control,collector)


def _run_single(pdf,folder,payload,bridge=None,progress=None,cancel_event=None,on_preview=None,on_control=None,collector=None):
    from asset_paths import configure
    configure()
    from babeldoc.translator.translator import BaseTranslator
    from babeldoc.format.pdf.translation_config import TranslationConfig,WatermarkOutputMode
    from babeldoc.format.pdf.high_level import do_translate,get_translation_stage
    from babeldoc.progress_monitor import ProgressMonitor
    from babel_runtime import monitor_type
    ProgressMonitor=monitor_type(ProgressMonitor)
    from babel_runtime import layout_model
    from babel_compat import install_graphics_copy,input_documents
    install_graphics_copy()
    translation_failures=[]
    class Translator(BaseTranslator):
        name='twintext-bridge'
        model='configured-provider'
        lang_map={'zh':'zh-CN','zh-cn':'zh-CN','zh-tw':'zh-TW'}
        def get_formular_placeholder(self,index):return f'<b{index}>',rf'<\s*b\s*{index}\s*>'
        def get_rich_text_left_placeholder(self,index):return f'<b{index}>',rf'<\s*b\s*{index}\s*>'
        def get_rich_text_right_placeholder(self,index):return f'</b{index}>',rf'<\s*/\s*b\s*{index}\s*>'
        def do_translate(self,text,rate_limit_params=None):
            if translation_failures:raise translation_failures[0]
            try:
                result=bridge(text) if bridge else text
                if not isinstance(result,str):raise ValueError('Translation provider must return text')
                return result
            except Exception as error:
                error.twintext_translation_failure=True
                if not translation_failures:translation_failures.append(error)
                raise
        def do_llm_translate(self,text,rate_limit_params=None):raise NotImplementedError("Use plain translation with BabelDOC formula placeholders")
    folder.mkdir(parents=True,exist_ok=True)
    source=folder/'source.pdf';source.write_bytes(pdf)
    translator=Translator(payload.get('sourceLanguage','en'),payload.get('targetLanguage','zh'),ignore_cache=True)
    config=TranslationConfig(translator=translator,input_file=source,lang_in=translator.lang_in,lang_out=translator.lang_out,
        doc_layout_model=layout_model(),pages=str(payload.get('pageIndex',0)+1) if not bridge else payload.get('pages'),
        output_dir=folder/'output',working_dir=folder/'work',debug=bridge is None,no_dual=True,auto_extract_glossary=False,
        disable_rich_text_translate=False,skip_translation=bridge is None,min_text_length=2,qps=max(2,min(16,int(payload.get('concurrency',3))*2)),pool_max_workers=max(2,min(16,int(payload.get("concurrency",3))*2)),
        formular_char_pattern=r'[⟨⟩⟪⟫⟮⟯⌈⌉⌊⌋]',
        auto_enable_ocr_workaround=True,watermark_output_mode=WatermarkOutputMode.NoWatermark,
        only_include_translated_page=bridge is None or payload.get('pageIsolation') is True)
    from page_geometry import normalize
    canonical,rotations=normalize(pdf,config)
    source.write_bytes(canonical)
    config.twintext_original_rotations=rotations
    config.twintext_structure_state=payload.get('_structureState',{})
    # Keep unselected pages so source/translation retain identical page indexes.
    # BabelDOC calls finish_callback from on_finish when a cancel event exists,
    # including successful synchronous completion. Exceptions still propagate
    # from do_translate; the callback itself must be present and non-throwing.
    from reference_layout import reference_layout
    from document_options import document_options
    with ProgressMonitor(get_translation_stage(config),progress_change_callback=progress,
                         finish_callback=lambda **event:None,cancel_event=cancel_event) as monitor:
        config.progress_monitor=monitor
        references=reference_layout(config,on_preview) if bridge else nullcontext()
        with document_options(config,payload.get('documentOptions')), references as policy:
            if on_preview and payload.get('documentExport'):
                from document_preview import paragraph_previews
                context=paragraph_previews(config,on_preview,int(payload.get('currentPage',0)))
            else:context=nullcontext()
            from native_artifacts import capture
            with capture(config,policy,collector) if collector is not None else nullcontext():
                with context as stream:
                    if on_control and stream:on_control(stream)
                    with input_documents():result=do_translate(monitor,config)
                    # Upstream catches paragraph translator exceptions. A failed
                    # provider must not be reported as a completed source PDF.
                    if translation_failures:raise translation_failures[0]
    paths=list((folder/'work').rglob('styles_and_formulas.json'))
    if bridge is None and not paths:raise RuntimeError('BabelDOC did not produce formula structure')
    document=json.loads(paths[0].read_text()) if bridge is None else {}
    output=Path(result.mono_pdf_path).read_bytes() if bridge else None
    if output:
        from preserved_regions import restore
        output=restore(canonical,output,getattr(config,'twintext_preserved_regions',[]),payload.get('pageIsolation') is True,config)
        import pymupdf
        with pymupdf.open(stream=pdf,filetype='pdf') as original,pymupdf.open(stream=output,filetype='pdf') as translated:
            if (1 if payload.get('pageIsolation') else original.page_count)!=translated.page_count:raise RuntimeError('Native PDF page alignment failed')
            if bridge and not payload.get('pageIsolation') and config.pages:
                # Upstream PDF cleanup can touch font resources on unselected
                # pages. Start from the source and import only selected output
                # pages, preserving the source page count and bookmark indexes.
                toc=original.get_toc(simple=False)
                for index in range(original.page_count):
                    if config.should_translate_page(index+1):
                        original.delete_page(index)
                        original.insert_pdf(translated,from_page=index,to_page=index,start_at=index)
                if toc:original.set_toc(toc)
                output=original.tobytes()
            if progress:progress(type='validated',page_count=translated.page_count)
    if output:
        from output_safety import validate
        import pymupdf
        with pymupdf.open(stream=canonical, filetype='pdf') as original:
            selected=[index for index in range(original.page_count) if config.should_translate_page(index+1)]
        validate(canonical,output,selected,payload.get('pageIsolation') is True)
    if collector and output:
        import pymupdf
        with pymupdf.open(stream=output,filetype='pdf') as doc:count=doc.page_count
        collector.update(source=pdf,langIn=config.lang_in,langOut=config.lang_out,pages=payload.get('pages'),
            pageCount=count,isolation=payload.get('pageIsolation') is True,canonicalSource=canonical)
    return il_regions(document),output
