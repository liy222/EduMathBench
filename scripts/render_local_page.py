"""Export the user's offline question bank, including embedded original images.

The inline widget size limit does not apply to this standalone local deliverable.
Use the existing standalone wrapper without opening a browser or starting a server.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = Path('C:/Users/liyh/.codex/plugins/cache/openai-bundled/visualize/1.0.49/skills/visualize/scripts/render.py')
spec = importlib.util.spec_from_file_location('standalone_wrapper', TOOL)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
source = ROOT / 'data/visualization/local-source.html'
destination = ROOT / '可视化/题库浏览.html'
document = module._render_document(source.read_text(encoding='utf-8'), 'EduMathBench 本地题库')
destination.write_text(document, encoding='utf-8')
print({'local_page': str(destination), 'bytes': destination.stat().st_size})
