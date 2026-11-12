"""Local, small OCR engine for single-choice source answer images. No LLM API."""
from __future__ import annotations
import hashlib, re, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if (ROOT/'.runtime_deps').exists():sys.path.insert(0,str(ROOT/'.runtime_deps'))
from PIL import Image, ImageChops, ImageOps
import numpy as np

ENGINE=None
def engine():
    global ENGINE
    if ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        ENGINE=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1)
    return ENGINE

def preprocess(image, binary=False):
    image=image.convert('RGBA')
    white=Image.new('RGBA',image.size,'white');white.alpha_composite(image)
    gray=ImageOps.grayscale(white.convert('RGB'))
    # Ignore the faint wide watermark when locating the actual answer glyph.
    ink=ImageChops.difference(gray,Image.new('L',gray.size,255)).point(lambda x:255 if x>100 else 0)
    box=ink.getbbox()
    if box is None:raise ValueError('空白答案图')
    gray=gray.crop(box)
    if gray.height>150 or gray.width>max(160,gray.height*8):raise ValueError('不是受支持的短答案区域')
    scale=max(3,64//max(1,gray.height))
    gray=gray.resize((gray.width*scale,gray.height*scale),Image.Resampling.LANCZOS)
    if binary:gray=gray.point(lambda x:0 if x<150 else 255)
    return ImageOps.expand(gray,border=16,fill=255).convert('RGB')

def recognize(path, threshold=0.90):
    path=Path(path);image=Image.open(path)
    attempts=[]
    for mode in ('gray','binary'):
        img=preprocess(image,mode=='binary')
        result,timing=engine()(np.array(img),use_det=False,use_cls=False,use_rec=True)
        text=result[0][0].strip() if result and len(result)==1 else ''
        score=float(result[0][1]) if result and len(result)==1 else 0
        # Do not search inside arbitrary OCR prose for an A/B/C/D letter.
        text=re.sub(r'^[\s【\[（(]*答案[】\]）):：\s]*','',text)
        text=text.strip(' .。．:：()（）[]【】')
        attempts.append({'preprocess':mode,'text':text,'confidence':round(score,6)})
    agreed=attempts[0]['text']==attempts[1]['text'] and bool(re.fullmatch('[A-D]',attempts[0]['text']))
    accepted=agreed and all(x['confidence']>=threshold for x in attempts)
    models=ROOT/'.runtime_deps/rapidocr_onnxruntime/models'
    return {'method':'local_rapidocr_dual_preprocessing','engine_version':'rapidocr-onnxruntime==1.4.4','preprocess_version':'answer-crop-v2',
            'threshold':threshold,'image_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'attempts':attempts,'accepted':accepted,'answer':attempts[0]['text'] if accepted else '',
            'recognition_model_sha256':hashlib.sha256((models/'ch_PP-OCRv4_rec_infer.onnx').read_bytes()).hexdigest() if models.exists() else None,
            'meaning':'两种预处理结果一致不等于独立双引擎复核，置信度不是正确率；后续人工抽查。'}
