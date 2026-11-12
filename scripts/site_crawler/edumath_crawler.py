"""EduMathBench: HTTP acquisition, four-site parsing, validation and export.

Browser acquisition is in browser_crawler.mjs. This module never reads browser
profiles or credentials. Image-only answers remain pending unless a separately
recorded transcription is supplied.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import re
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
from urllib.request import Request, urlopen

from lxml import etree, html

TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[2]
GATES = re.compile(r"抱歉.{0,12}(?:未登录|尚未登录)|游客模式.{0,50}(?:登录|注册)|访问过于频繁|安全验证|请完成验证|仅限.{0,8}(?:会员|VIP)")
SITES = {"tiku": "牛题库", "21cnjy": "二一组卷网", "chujuan": "出卷网", "jyeoo": "菁优网"}
MATH_DELIMITERS = False


def stamp():
    return datetime.now(TZ).isoformat(timespec="seconds")


def has_class(name):
    return f'contains(concat(" ", normalize-space(@class), " "), " {name} ")'


def nodes(root, cls):
    return root.xpath(f'descendant-or-self::*[{has_class(cls)}]')


def first(root, cls):
    found = nodes(root, cls)
    return found[0] if found else None


def clean(value):
    return re.sub(r"[ \t\r\f\v]+", " ", value or "").strip()


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def decode_html(data, content_type=""):
    """lxml's bytes default can misread Chinese pages without legacy meta tags."""
    match = re.search(r"charset\s*=\s*['\"]?([\w-]+)", content_type, re.I)
    encodings = ([match[1]] if match else []) + ["utf-8-sig", "gb18030"]
    for encoding in dict.fromkeys(encodings):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            pass
    raise ValueError("无法无损解码网页，保留原始字节待检查")


def mathml(el):
    """Keep grouping when converting common MathML, rather than flattening it."""
    tag = etree.QName(el).localname.lower() if isinstance(el.tag, str) else ""
    parts = [mathml(c) for c in el if isinstance(c.tag, str)]
    if tag == "semantics":
        return parts[0] if parts else ""
    if tag in ("annotation", "annotation-xml"):
        return ""
    if tag not in {"math", "mfrac", "msqrt", "mroot", "msup", "msub", "msubsup", "mi", "mn", "mo", "mrow", "mstyle", "mtext", "mfenced"}:
        return "[公式待转换:" + digest(etree.tostring(el, encoding="unicode"))[:12] + "]"
    if tag == "mfrac" and len(parts) == 2:
        return rf"\frac{{{parts[0]}}}{{{parts[1]}}}"
    if tag == "msqrt":
        return rf"\sqrt{{{''.join(parts)}}}"
    if tag == "mroot" and len(parts) == 2:
        return rf"\sqrt[{parts[1]}]{{{parts[0]}}}"
    if tag in ("msup", "msub") and len(parts) == 2:
        return "{" + parts[0] + "}" + ("^" if tag == "msup" else "_") + "{" + parts[1] + "}"
    if tag == "msubsup" and len(parts) == 3:
        return "{" + parts[0] + "}_{" + parts[1] + "}^{" + parts[2] + "}"
    if tag == "mfenced":
        return el.get("open", "(") + el.get("separators", ",").join(parts) + el.get("close", ")")
    return (el.text or "") + "".join(mathml(c) + (c.tail or "") for c in el if isinstance(c.tag, str))


def mathjye(el):
    """Handle observed MathJye HTML fractions; retain unknown layouts for review."""
    classes = set((el.get("class") or "").split())
    known = {"MathJye", "mrow", "mo", "math-letter", "math-letter-i", "mnormal", "mfrac", "fracZi", "fracMu", "fracLine"}
    if classes - known or el.tag in ("table", "svg"):
        return "[公式待转换:" + digest(html.tostring(el, encoding="unicode"))[:12] + "]"
    if "mfrac" in classes:
        top, bottom = first(el, "fracZi"), first(el, "fracMu")
        if top is None or bottom is None:
            return "[公式待转换:" + digest(html.tostring(el, encoding="unicode"))[:12] + "]"
        return rf"\frac{{{mathjye(top)}}}{{{mathjye(bottom)}}}"
    return (el.text or "") + "".join(mathjye(c) + (c.tail or "") for c in el if isinstance(c.tag, str))


def readable(el, base_url, role, assets):
    if el is None:
        return ""
    if "display:none" in el.get("style", "").replace(" ", "").lower() or el.get("hidden") is not None:
        return ""
    el = copy.deepcopy(el)
    # Never obtain answers from hidden labels, form fields or scripts.
    for item in list(el.iterdescendants()):
        if not isinstance(item.tag, str):
            parent = item.getparent()
            if parent is not None:
                # In lxml, text after a comment belongs to comment.tail. Removing
                # the comment with remove() alone would silently delete the stem.
                previous = item.getprevious()
                if previous is None:
                    parent.text = (parent.text or "") + (item.tail or "")
                else:
                    previous.tail = (previous.tail or "") + (item.tail or "")
                parent.remove(item)
            continue
        style = item.get("style", "").replace(" ", "").lower()
        if item.tag in ("script", "style", "input", "template") or item.get("hidden") is not None or "display:none" in style or item.get("aria-hidden") == "true":
            item.drop_tree()
    for item in list(el.xpath('.//*[local-name()="math"]')):
        replacement = etree.Element("span")
        replacement.text = " " + ("$" if MATH_DELIMITERS else "") + mathml(item) + ("$" if MATH_DELIMITERS else "") + " "
        replacement.tail = item.tail
        item.getparent().replace(item, replacement)
    for item in list(nodes(el, "MathJye")):
        if item is el:
            continue
        replacement = etree.Element("span")
        replacement.text = " " + ("$" if MATH_DELIMITERS else "") + mathjye(item) + ("$" if MATH_DELIMITERS else "") + " "
        replacement.tail = item.tail
        item.getparent().replace(item, replacement)
    for item in list(el.xpath('.//*[local-name()="svg"]')):
        replacement = etree.Element("span")
        replacement.text = "[公式待转换:" + digest(etree.tostring(item, encoding="unicode"))[:12] + "]"
        replacement.tail = item.tail
        item.getparent().replace(item, replacement)
    for image in list(el.xpath('.//img')):
        src = image.get("src") or image.get("_src") or image.get("data-src") or ""
        # The visible formula image URL can itself contain its source MathML.
        # Convert that explicit expression rather than OCRing mathematical text.
        embedded = parse_qs(urlparse(urljoin(base_url, src)).query).get("mml", [])
        if embedded:
            try:
                expression = mathml(etree.fromstring(embedded[0].encode(), parser=etree.XMLParser(resolve_entities=False, no_network=True)))
                if "[公式待转换:" not in expression:
                    image.tail = " $" + expression.strip() + "$ " + (image.tail or "")
                    image.drop_tree()
                    continue
            except (ValueError, etree.XMLSyntaxError):
                pass
        if not src:
            token = "[缺失图片]"
        else:
            absolute = urljoin(base_url, src)
            key = hashlib.sha256(absolute.split("?")[0].encode()).hexdigest()[:16]
            assets.append({"asset_id": key, "role": role, "url": absolute, "local_path": None, "download_status": "pending"})
            alt = clean(image.get("alt"))
            meaningful_alt = alt and alt not in ("菁优网", "图片") and not re.search(r'\.(?:png|jpe?g|gif|webp|svg)$', alt, re.I)
            token = alt if meaningful_alt else f"[图片:{key}]"
        image.tail = token + (image.tail or "")
        image.drop_tree()
    for item in el.xpath('.//sup|.//sub'):
        content="".join(item.itertext())
        # Malformed source markup may leave a numeral <sup> open over prose.
        # Restore only a leading numeric exponent immediately followed by Chinese;
        # preserve every following character as ordinary text, without guessing math.
        spill=re.fullmatch(r'([+−﹣-]?\d+)([\u4e00-\u9fff][\s\S]*)',content) if item.tag=='sup' else None
        if spill:
            content=spill[1];item.tail=spill[2]+(item.tail or '')
        item.text = ("^{" if item.tag == "sup" else "_{") + content + "}"
        if MATH_DELIMITERS:item.text = " ${}" + item.text + "$ "
        for child in list(item):
            item.remove(child)
    for item in el.xpath('.//br'):
        item.tail = "\n" + (item.tail or "")
    for item in el.xpath('.//td|.//th'):
        item.tail = " | " + (item.tail or "")
    for item in el.xpath('.//p|.//tr'):
        item.tail = "\n" + (item.tail or "")
    value = "".join(el.itertext())
    return "\n".join(clean(line) for line in value.splitlines() if clean(line))


def base_record(site, native_id, url, filters, raw_path):
    return {
        "id": f"EMB-TRIAL-{site.upper()}-{native_id}", "source_question_id": native_id,
        "source_site": SITES[site], "source_platform": site, "source_url": url,
        "source_type": "public", "source_ref": native_id, "source_title": "",
        "question": "", "options": {x: "" for x in "ABCD"}, "answer": "", "solution": "",
        "grade": filters.get("grade", 7), "source_exam_grade": "pending",
        "module": filters.get("module", "数与式"), "knowledge_point": filters.get("knowledge", "有理数的加法"),
        "knowledge_path": filters.get("knowledge_path", ["数与式", "有理数", "有理数的加法"]),
        "difficulty": "pending", "source_difficulty_label": filters.get("difficulty", ""),
        "source_difficulty_value": None, "difficulty_basis": "source_label_not_empirically_calibrated",
        "filters_requested": filters, "source_label_listing": "", "source_label_detail": "",
        "image_assets": [], "input_modality": "text", "answer_format": "missing",
        "solution_format": "missing", "answer_access": "not_observed", "raw_path": str(raw_path),
        "collected_at": stamp(), "status": "needs_review", "risk_flags": ["math_not_reviewed", "reuse_rights_unknown"],
        "format_version": "edumath-site-trial-v1",
    }


def parse_question(site, markup, url, filters=None, raw_path="", listing=None):
    filters = filters or {}
    tree = html.fromstring(markup)
    native = ""
    if site == "tiku":
        card = first(tree, "q-detail")
        if card is None:
            raise ValueError("未找到牛题库题目节点")
        native = next((x.get("id")[1:] for x in card.xpath('.//*[@id]') if re.fullmatch(r"p\d+", x.get("id", ""))), "")
        r = base_record(site, native, url, filters, raw_path)
        r["question"] = readable(first(card, "card-text"), url, "question", r["image_assets"])
        for letter, option in zip("ABCD", nodes(card, "col-xl-6")):
            r["options"][letter] = re.sub(r"^[A-D][、．.\s]+", "", readable(option, url, "option_" + letter, r["image_assets"]))
        footer = readable(first(card, "card-footer"), url, "metadata", [])
        match = re.search(r"答案\s*[:：]\s*([A-D])", footer)
        r["answer"] = match[1] if match else ""
        match = re.search(r"难度\s*[:：]\s*([0-9.]+)", footer)
        r["source_difficulty_value"] = float(match[1]) if match else None
        r["solution"] = readable(first(card, "q-analysis"), url, "solution", r["image_assets"])
        r["source_title"] = "牛题库有理数的加法筛选结果"
        r["source_exam_grade"] = "unreported"
        r["risk_flags"].append("original_exam_source_unreported")
    elif site in ("21cnjy", "chujuan"):
        title = first(tree, "q-tit")
        if title is None:
            raise ValueError("未找到题干节点")
        match = re.search(r"detail[/-](\d+)", url)
        native = title.get("data-qid") or (match[1] if match else "")
        r = base_record(site, native, url, filters, raw_path)
        origin = first(title, "ques-origin")
        r["source_label_detail"] = clean("".join(origin.itertext())) if origin is not None else ""
        title_copy = copy.deepcopy(title)
        for item in nodes(title_copy, "ques-origin"):
            item.drop_tree()
        r["question"] = re.sub(r"^\s*\d+\s*[.．、]\s*", "", readable(title_copy, url, "question", r["image_assets"]))
        options = nodes(tree, "op-item-meat")
        for letter, option in zip("ABCD", options):
            r["options"][letter] = readable(option, url, "option_" + letter, r["image_assets"])
        for role, cls, field in [("answer", "J_ana_ans", "answer"), ("solution", "J_ana_exp", "solution")]:
            box = first(tree, cls)
            content = first(box, "q-analyize-mc") if box is not None else None
            r[field] = readable(content, url, role, r["image_assets"])
        diff = readable(first(tree, "q-attribute"), url, "metadata", [])
        match = re.search(r"(容易|普通|困难)(?:\(([\d.]+)\))?", diff)
        if match:
            r["source_difficulty_label"] = match[1]
            r["source_difficulty_value"] = float(match[2]) if match[2] else None
        r["source_title"] = r["source_label_detail"]
        knows = nodes(tree, "knowledge_link")
        if knows:
            r["source_knowledge_points"] = [clean("".join(x.itertext())) for x in knows]
    elif site == "jyeoo":
        fieldsets = tree.xpath('descendant-or-self::fieldset[@id]')
        if not fieldsets:
            raise ValueError("未找到菁优题目节点")
        fieldset = fieldsets[0]
        native = fieldset.get("id")
        r = base_record(site, native, url, filters, raw_path)
        origin = first(fieldset, "ques-source")
        r["source_label_detail"] = fieldset.get("data-label") or (clean("".join(origin.itertext())) if origin is not None else "")
        title = first(fieldset, "pt1")
        if title is None:
            raise ValueError("未找到菁优题干")
        title = copy.deepcopy(title)
        for cls in ("qseq", "ques-source"):
            for item in nodes(title, cls):
                item.drop_tree()
        r["question"] = readable(title, url, "question", r["image_assets"])
        for cell in nodes(fieldset, "selectoption"):
            text = readable(cell, url, "option", r["image_assets"])
            match = re.match(r"([A-D])[．.、]\s*(.*)", text, re.S)
            if match:
                r["options"][match[1]] = match[2].strip()
        # Only explicitly labelled sections qualify; highlight CSS never does.
        for section in fieldset:
            if not isinstance(section.tag, str):
                continue
            labels = section.xpath('./em[1]/text()')
            if not labels or not re.match(r"^【(?:答案|分析|解答|点评)】", clean(labels[0])):
                continue
            text = readable(section, url, "solution", r["image_assets"])
            if re.match(r"^【答案】", text):
                r["answer"] = re.sub(r"^【答案】\s*", "", text)
            elif re.match(r"^【(?:分析|解答|点评)】", text):
                r["solution"] += text + "\n"
        match = re.search(r"故选\s*[:：]?\s*([A-D])|(?:答案|解答)[】\]：:\s]*([A-D])(?:[．.\s]|$)", r["solution"])
        if match and not r["answer"]:
            r["answer"] = next(x for x in match.groups() if x)
        r["source_title"] = r["source_label_detail"]
        metadata = readable(first(tree, "fieldtip-left"), url, "metadata", [])
        if not metadata:
            metadata = " ".join(tree.xpath('//*[contains(@class,"fieldtip")]//text()'))
        match = re.search(r"难度[：:]\s*(中档|较易|较难|易|难)", metadata)
        if match:
            r["source_difficulty_label"] = match[1]
    else:
        raise ValueError(f"未知站点：{site}")
    if not native:
        raise ValueError("缺少可追溯来源题号")
    if listing:
        r["source_label_listing"] = listing.get("origin", "")
        r["listing_url"] = listing.get("url", "")
        r["listing_raw_path"] = listing.get("raw_path", "")
        if not r["source_difficulty_label"]:
            match = re.search(r"难度[：:]\s*(易|较易|中档|较难|难)", listing.get("text", ""))
            if match:
                r["source_difficulty_label"] = match[1]
    grade_match = re.search(r"([六七八九])(?:上|下|年级)", r["source_label_detail"] or r["source_label_listing"])
    if grade_match:
        r["source_exam_grade"] = {"六": 6, "七": 7, "八": 8, "九": 9}[grade_match[1]]
    return validate(r)


def validate(r):
    flags = r["risk_flags"]
    # A signed image URL is evidence of an image, not a decoded answer letter.
    if "[图片:" in r["answer"]:
        r["answer"] = ""
    r["answer"] = re.sub(r"^[【\[]?答案[】\]：:]*\s*", "", r["answer"]).strip().rstrip("．.。").strip()
    if re.fullmatch("[A-D]", r["answer"]):
        r["answer_format"] = "text"
        r["answer_access"] = "source_image_visually_transcribed" if r.get("answer_transcription") else "visible_source_answer"
        flags = [x for x in flags if x not in ("answer_image_requires_transcription", "source_answer_missing")]
    elif any(a["role"] == "answer" for a in r["image_assets"]):
        r["answer_format"] = "image"
        r["answer_access"] = "visible_answer_image"
        flags.append("answer_image_requires_transcription")
    else:
        r["answer_format"] = "missing"
        flags.append("source_answer_missing")
    r["source_answer_format"] = "image" if any(a["role"] == "answer" for a in r["image_assets"]) else r["answer_format"]
    if any(a["role"] == "solution" for a in r["image_assets"]):
        r["solution_format"] = "image" if not re.sub(r"\[图片:[^]]+\]", "", r["solution"]).strip() else "mixed"
        if r["solution_format"] == "image":
            r["solution"] = ""
    elif r["solution"].strip():
        r["solution_format"] = "text"
    if any(a["role"] == "question" or a["role"].startswith("option") for a in r["image_assets"]):
        r["input_modality"] = "text_image"
        flags.append("input_image_requires_preservation")
    if not r["question"]:
        flags.append("question_missing")
    complete_options = set(r["options"]) == set("ABCD") and all(r["options"].values())
    if not complete_options:
        flags.append("four_options_incomplete")
    unsupported_math = any("[公式待转换:" in value for value in [r["question"], *r["options"].values()])
    if unsupported_math:
        flags.append("unsupported_math_markup")
    mapping = {"易": "基础", "较易": "基础", "容易": "基础", "中": "中等", "中档": "中等", "普通": "中等", "难": "困难", "较难": "困难", "困难": "困难"}
    r["difficulty"] = mapping.get(r["source_difficulty_label"], "pending")
    r["risk_flags"] = sorted(set(flags))
    r["status"] = "collected" if r["answer_format"] == "text" and r["input_modality"] == "text" and r["question"] and complete_options and not unsupported_math else "needs_review"
    r["content_sha256"] = digest(r["question"] + json.dumps(r["options"], ensure_ascii=False, sort_keys=True))
    return r


def canonical(value):
    value = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", "", value).replace("−", "-").replace("﹣", "-")


def deduplicate(records):
    kept, duplicates, seen, source_ids = [], [], {}, set()
    for r in records:
        source_key = (r["source_platform"], r["source_question_id"])
        key = digest(canonical(r["question"]) + json.dumps(sorted(canonical(x) for x in r["options"].values()), ensure_ascii=False))
        if source_key in source_ids or key in seen:
            owner = seen.get(key)
            item = {"id": r["id"], "same_as": owner["id"] if owner else None, "reason": "same_source_id" if source_key in source_ids else "same_question_and_options_ignoring_order"}
            if owner and r["answer"] in r["options"] and owner["answer"] in owner["options"]:
                item["answer_content_agrees"] = canonical(r["options"][r["answer"]]) == canonical(owner["options"][owner["answer"]])
            duplicates.append(item)
        else:
            kept.append(r)
            seen[key] = r
        source_ids.add(source_key)
    return kept, duplicates


class HttpCollector:
    def __init__(self, out, delay=1.5, timeout=15):
        self.out, self.delay, self.timeout = Path(out), delay, timeout
        self.requests = []
        self.last_request = 0.0

    def fetch(self, url, destination):
        if urlparse(url).scheme not in ("http", "https"):
            raise ValueError("仅允许HTTP(S)来源")
        pause = self.delay - (time.monotonic() - self.last_request)
        if pause > 0:
            time.sleep(pause)
        started = time.monotonic()
        log = {"url": url, "requested_at": stamp()}
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 EduMathBenchResearchCollector/1.0", "Accept": "text/html,image/*;q=0.8"})
            with urlopen(req, timeout=self.timeout) as response:
                data = response.read(12 * 1024 * 1024 + 1)
                if len(data) > 12 * 1024 * 1024:
                    raise ValueError("响应超过12MB上限")
                log.update(status=response.status, final_url=response.url, content_type=response.headers.get("Content-Type", ""))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            log.update(raw_path=str(destination), sha256=hashlib.sha256(data).hexdigest(), byte_count=len(data))
            return data
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            log.update(status=getattr(exc, "code", "error"), error=str(exc))
            raise
        finally:
            self.last_request = time.monotonic()
            log["elapsed_seconds"] = round(self.last_request - started, 3)
            self.requests.append(log)


def download_assets(records, collector, out):
    cache = {}
    for r in records:
        for asset in r["image_assets"]:
            key = asset["asset_id"]
            if key not in cache:
                target = out / "assets" / (key + (Path(urlparse(asset["url"]).path).suffix or ".bin"))
                try:
                    data = target.read_bytes() if target.is_file() else collector.fetch(asset["url"], target)
                    cache[key] = {"local_path": str(target), "download_status": "saved", "sha256": hashlib.sha256(data).hexdigest()}
                except Exception as exc:
                    cache[key] = {"download_status": "failed", "error": str(exc)}
            asset.update(cache[key])


def restore_cached_assets(records, out, source_cache=None):
    for r in records:
        for asset in r["image_assets"]:
            target = out / "assets" / (asset["asset_id"] + (Path(urlparse(asset["url"]).path).suffix or ".bin"))
            if not target.is_file() and source_cache is not None:
                original = source_cache / target.name
                if original.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(original.read_bytes())
            if target.is_file():
                asset.update(local_path=str(target), download_status="saved", sha256=hashlib.sha256(target.read_bytes()).hexdigest())


def apply_transcriptions(records, filename):
    """A separate evidence ledger keeps human reading out of automatic results."""
    entries = json.loads(filename.read_text(encoding="utf-8"))
    index = {(r["source_platform"], r["source_question_id"]): r for r in records}
    for item in entries:
        key = (item["site"], str(item["source_question_id"]))
        if key not in index:
            raise ValueError(f"转录记录没有对应题目：{key}")
        r = index[key]
        images = [a for a in r["image_assets"] if a["role"] == "answer"]
        if not any(a.get("sha256") == item["image_sha256"] for a in images):
            raise ValueError(f"答案图片摘要不匹配：{key}")
        if item["answer"] not in "ABCD" or len(item["answer"]) != 1:
            raise ValueError(f"转录答案必须为A/B/C/D：{key}")
        if r["answer"] and r["answer"] != item["answer"]:
            raise ValueError(f"转录与已有来源答案冲突：{key}")
        r["answer"] = item["answer"]
        r["answer_transcription"] = item
        r["risk_flags"].append("answer_visually_transcribed_from_source_image")
        validate(r)


def automatic_rejection_reasons(r):
    """Deterministic acceptance gate. No OCR, human ledger or model completion."""
    reasons = []
    if r.get("answer_transcription") or r.get("answer_access") == "source_image_visually_transcribed":
        reasons.append("nonautomatic_answer")
    if r.get("source_answer_format") != "text" or not re.fullmatch("[A-D]", r.get("answer", "")):
        reasons.append("source_text_answer_required")
    if r.get("status") != "collected":
        reasons.append("structure_incomplete")
    if r.get("input_modality") != "text":
        reasons.append("input_image_deferred")
    if "[缺失图片]" in " ".join([r.get("question", ""), *r.get("options", {}).values()]):
        reasons.append("missing_input_image")
    return reasons


def answer_only(record):
    """Keep source answers, discard solution fields/assets without model use."""
    record = copy.deepcopy(record)
    record["solution"] = ""
    record["solution_format"] = "not_requested"
    record["image_assets"] = [a for a in record["image_assets"] if a["role"] != "solution"]
    return record


def export(records, out, events=None, automatic_only=False):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if automatic_only:
        records = [answer_only(r) for r in records]
    deferred, eligible = [], []
    for record in records:
        reasons = automatic_rejection_reasons(record) if automatic_only else []
        if reasons:
            deferred.append({**record, "automatic_rejection_reasons": reasons})
        else:
            eligible.append(record)
    kept, duplicates = deduplicate(eligible)
    def jsonl(name, rows):
        (out / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    jsonl("candidates.jsonl", records)
    jsonl("questions.jsonl", kept)
    jsonl("duplicates.jsonl", duplicates)
    jsonl("deferred.jsonl", deferred)
    jsonl("events.jsonl", events or [])
    columns = ["id", "source_site", "source_question_id", "question", "option_a", "option_b", "option_c", "option_d", "answer", "solution", "difficulty", "source_difficulty_label", "source_difficulty_value", "status", "answer_format", "source_answer_format", "solution_format", "input_modality", "source_url", "source_label_listing", "source_label_detail", "raw_path", "collection_method", "image_assets", "filters_requested", "risk_flags", "answer_transcription"]
    with (out / "questions.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for r in kept:
            row = {k: r.get(k, "") for k in columns}
            row.update({"option_" + k.lower(): v for k, v in r["options"].items()})
            for key in ("image_assets", "filters_requested", "risk_flags", "answer_transcription"):
                if isinstance(row[key], (list, dict)):
                    row[key] = json.dumps(row[key], ensure_ascii=False)
            writer.writerow(row)
    report = {"generated_at": stamp(), "candidate_count": len(records), "unique_count": len(kept), "duplicate_count": len(duplicates), "collected_count": sum(r["status"] == "collected" for r in kept), "needs_review_count": sum(r["status"] == "needs_review" for r in kept), "source_text_answer_count": sum(r["answer_format"] == "text" and not r.get("answer_transcription") for r in kept), "visually_transcribed_answer_count": sum(bool(r.get("answer_transcription")) for r in kept), "assets_saved": sum(a.get("download_status") == "saved" for r in kept for a in r["image_assets"]), "assets_failed": sum(a.get("download_status") == "failed" for r in kept for a in r["image_assets"]), "by_site": {}, "meaning": "collected仅表示四选项、来源答案和文本结构齐全，不代表数学复核通过；未并入原1800题。"}
    for site in SITES:
        subset = [r for r in kept if r["source_platform"] == site]
        report["by_site"][site] = {"unique": len(subset), "collected": sum(r["status"] == "collected" for r in subset), "source_answer_image": sum(r.get("source_answer_format") == "image" for r in subset), "missing_answer": sum(r["answer_format"] == "missing" for r in subset), "solution_text": sum(r["solution_format"] == "text" for r in subset), "solution_image": sum(r["solution_format"] in ("image", "mixed") for r in subset)}
    report.update(automatic_only=automatic_only, deferred_count=len(deferred), model_calls=0,
                  answer_policy="visible_source_text_only" if automatic_only else "source_text_or_explicit_transcription",
                  solution_requested=not automatic_only,
                  solution_missing_count=sum(r["solution_format"] == "missing" for r in kept))
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    net = sub.add_parser("http", help="按已验证筛选地址采集公开HTTP页面")
    net.add_argument("--config", type=Path, required=True)
    net.add_argument("--site", choices=list(SITES), default="tiku")
    net.add_argument("--limit", type=int, default=5)
    net.add_argument("--pages", type=int, default=1)
    net.add_argument("--out", type=Path, required=True)
    net.add_argument("--download-assets", action="store_true")
    net.add_argument("--automatic-only", action="store_true", help="仅导出原站文本答案且结构完整的题；其他保留到deferred.jsonl")
    imp = sub.add_parser("import", help="解析浏览器爬虫生成的manifest.json")
    imp.add_argument("manifest", type=Path)
    imp.add_argument("--out", type=Path, required=True)
    imp.add_argument("--download-assets", action="store_true")
    imp.add_argument("--transcriptions", type=Path, help="按原图摘要核验后合并的独立目视转录记录")
    imp.add_argument("--automatic-only", action="store_true")
    args = parser.parse_args()
    if args.command == "import" and args.automatic_only and args.transcriptions:
        parser.error("全自动模式不允许使用目视转录台账")
    if args.command == "http" and not (1 <= args.limit <= 5000 and 1 <= args.pages <= 100):
        parser.error("limit须为1–5000，pages须为1–100；limit是候选题上限")
    args.out.mkdir(parents=True, exist_ok=True)
    collector = HttpCollector(args.out)
    records, events, manifest_items = [], [], []
    if args.command == "http":
        task = next(t for t in json.loads(args.config.read_text(encoding="utf-8"))["tasks"] if t["site"] == args.site)
        pending, visited = [task["url"]], set()
        while pending and len(visited) < args.pages and len(records) < args.limit:
            url = pending.pop(0)
            if url in visited:
                continue
            visited.add(url)
            path = args.out / "raw" / f"{args.site}_page_{len(visited)}.html"
            try:
                data = collector.fetch(url, path)
                tree = html.fromstring(decode_html(data, collector.requests[-1].get("content_type", "")))
                page_text = clean("".join(tree.itertext()))
                if GATES.search(page_text) or "loginform" in urlparse(collector.requests[-1].get("final_url", "")).path:
                    events.append({"site": args.site, "status": "login_or_access_required", "url": url})
                    break
                roots = nodes(tree, {"tiku": "q-detail", "21cnjy": "QuestionView", "chujuan": "QuestionView", "jyeoo": "QUES_LI"}[args.site])
                for root in roots:
                    if len(records) >= args.limit:
                        break
                    markup = html.tostring(root, encoding="unicode")
                    try:
                        record = parse_question(args.site, markup, url, task["filters"], path)
                        record["collection_method"] = "http_crawler"
                        record["acquisition_automation"] = "programmatic_http"
                        record["listing_url"] = url
                        record["raw_sha256"] = collector.requests[-1]["sha256"]
                        fragment = args.out / "raw" / f'{args.site}_question_{record["source_question_id"]}.html'
                        fragment.write_text(markup, encoding="utf-8")
                        record["raw_path"] = str(fragment)
                        record["listing_raw_path"] = str(path)
                        manifest_items.append({"site": args.site, "url": url,
                                               "raw_path": fragment.relative_to(args.out).as_posix(),
                                               "filters": task["filters"], "collection_method": "http_crawler",
                                               "acquisition_automation": "programmatic_http",
                                               "listing": {"url": url, "raw_path": str(path)}})
                        records.append(record)
                    except Exception as exc:
                        events.append({"site": args.site, "status": "question_parse_error", "error": str(exc), "url": url})
                # Follow actual public pagination links, never enumerate guessed endpoints.
                links = tree.xpath('.//a[contains(normalize-space(.),"下一页") or normalize-space(.)=">"]/@href')
                for href in links[:1]:
                    candidate = urljoin(url, href)
                    if urlparse(candidate).scheme in ("http", "https") and urlparse(candidate).netloc == urlparse(url).netloc:
                        pending.append(candidate)
                if not roots:
                    events.append({"site": args.site, "status": "dynamic_or_changed_layout", "url": url})
            except Exception as exc:
                events.append({"site": args.site, "status": "fetch_or_parse_error", "error": str(exc), "url": url})
    else:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        for item in manifest["items"]:
            raw = Path(item["raw_path"])
            if not raw.is_absolute():
                raw = args.manifest.parent / raw
            try:
                record = parse_question(item["site"], raw.read_text(encoding="utf-8"), item["url"], item.get("filters", {}), raw, item.get("listing"))
                record["collection_method"] = item.get("collection_method", "browser_html_import")
                if item.get("acquisition_automation"):
                    record["acquisition_automation"] = item["acquisition_automation"]
                records.append(record)
            except Exception as exc:
                events.append({"site": item["site"], "status": "parse_error", "raw_path": str(raw), "error": str(exc)})
        events.extend(manifest.get("events", []))
    if args.automatic_only:
        records = [answer_only(r) for r in records]
    restore_cached_assets(records, args.out, args.manifest.parent / "normalized/assets" if args.command == "import" else None)
    if args.download_assets:
        download_assets(records, collector, args.out)
    if args.command == "import" and args.transcriptions:
        apply_transcriptions(records, args.transcriptions)
    events.extend(collector.requests)
    if args.command == "http":
        (args.out / "manifest.json").write_text(json.dumps({"format": "edumath-http-acquisition-v1", "items": manifest_items, "events": events}, ensure_ascii=False, indent=2), encoding="utf-8")
    report = export(records, args.out, events, automatic_only=args.automatic_only)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not records:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
