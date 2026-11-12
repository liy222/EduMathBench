"""Use the canonical DOCX rasterizer with a native Word PDF on Windows.

The runtime does not bundle LibreOffice on this host. The PDF was exported from
the actual read-only DOCX by Word; no HTML surrogate or system LibreOffice is used.
"""
import importlib.util, os, sys
from pathlib import Path
skill=Path('C:/Users/liyh/.codex/plugins/cache/openai-primary-runtime/documents/26.1013.11914/skills/documents')
spec=importlib.util.spec_from_file_location('canonical_render_docx',skill/'render_docx.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
root=Path(__file__).resolve().parents[1]
target=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'汇报材料/EduMathBench_阶段工作汇总_2026-10-15.docx'
out=Path(sys.argv[2]).resolve() if len(sys.argv)>2 else root/'data/reports/stage_report_qa_20261015'
pdf=out/'word_render.pdf'
assert pdf.exists() and pdf.stat().st_size>0
poppler=Path('C:/Users/liyh/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin')
os.environ['PATH']=str(poppler)+os.pathsep+os.environ.get('PATH','')
module.convert_to_pdf=lambda doc_path,user_profile,convert_tmp_dir,stem,verbose=False:(str(pdf),'Native Microsoft Word read-only PDF export; bundled Poppler rasterization.')
sys.argv=['render_docx.py',str(target),'--output_dir',str(out),'--dpi','150']
module.main()
