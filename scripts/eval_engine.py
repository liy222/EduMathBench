#!/usr/bin/env python3
"""Reproducible, answer-blind evaluation (stdlib core; optional Pillow padding).

run reads inputs and the manifest only. score is a separate command which reads
the answer table. Mock runs are always labelled synthetic software checks.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import copy
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any


PROMPT_VERSION = "emb-choice-v1"
SYSTEM_PROMPT = "请给出简短解答，并以“最终答案：A-D”的格式给出唯一最终答案（A-D表示A、B、C或D）。"
LABELS = ("A", "B", "C", "D")
ATTEMPTED_STATUSES = {"ok", "parse_failure", "refusal", "timeout", "api_error", "transport_error", "invalid_response"}
SKIPPED_STATUSES = {"unsupported_image", "missing_image", "invalid_image"}
UNRUN_STATUSES = {"unrun_budget_limit"}
REQUEST_EXTRA_RESERVED = {"model", "messages", "stream", "headers", "authorization", "api_key", "api-key", "apikey", "api_key_env", "token", "access_token", "base_url", "url", "request_options", "temperature", "max_tokens", "max_completion_tokens"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class EvaluationError(ValueError):
    """A configuration, data-integrity or resume error; no request is warranted."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise EvaluationError(f"Cannot read JSON {path}: {exc}") from exc


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    try:
        with path.open(encoding="utf-8-sig") as stream:
            for number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError as exc:
                    raise EvaluationError(f"Invalid JSON at {path}:{number}") from exc
                if not isinstance(row, dict):
                    raise EvaluationError(f"Expected object at {path}:{number}")
                rows.append(row)
    except OSError as exc:
        raise EvaluationError(f"Cannot read {path}: {exc}") from exc
    return rows


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers/antivirus can briefly hold a destination without
        # delete sharing. Retry the atomic replacement; never truncate the
        # committed file or repeat a remote request because a log is busy.
        for replacement_attempt in range(12):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if replacement_attempt == 11:
                    raise
                time.sleep(min(0.5, 0.02 * (2 ** replacement_attempt)))
    finally:
        with contextlib.suppress(FileNotFoundError, PermissionError):
            os.unlink(temporary)


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, json_bytes(value) + b"\n")


def append_jsonl_atomic(path: Path, row: dict) -> None:
    """Commit a whole journal version; a crash leaves either old or new bytes.

    Raw (potentially large) requests live in per-item files, not this journal.
    One run lock protects the journal from concurrent writers.
    """
    previous = path.read_bytes() if path.exists() else b""
    if previous and not previous.endswith(b"\n"):
        raise EvaluationError(f"Incomplete journal: {path}")
    atomic_write(path, previous + json_bytes(row) + b"\n")


@contextlib.contextmanager
def run_lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / ".run.lock"
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as exc:
        raise EvaluationError(f"Run is locked: {lock}. If a previous process died, verify it has stopped before removing this lock.") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(f"pid={os.getpid()}\nstarted={utc_now()}\n")
        yield
    finally:
        lock.unlink(missing_ok=True)


def contained_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise EvaluationError("Asset and dataset paths must be nonempty relative POSIX paths")
    candidate = Path(relative)
    # Reject drive-qualified Windows paths even when inspected on another OS.
    if candidate.is_absolute() or re.match(r"^[A-Za-z]:", relative):
        raise EvaluationError(f"Absolute path is not allowed: {relative}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise EvaluationError(f"Path escapes dataset root: {relative}") from exc
    return resolved


def manifest_input_entry(manifest: dict, split: str) -> tuple[str, str]:
    """Accept the documented inputs mapping and common file-list manifests."""
    default_path = f"inputs/{split}_inputs.jsonl"
    entry = manifest.get("inputs", {}).get(split) if isinstance(manifest.get("inputs"), dict) else None
    if isinstance(entry, str):
        entry = {"path": entry}
    if entry is None:
        files = manifest.get("files", {})
        if isinstance(files, dict):
            entry = files.get(default_path) or files.get(f"{split}_inputs.jsonl")
            if isinstance(entry, str):
                entry = {"path": default_path, "sha256": entry}
        elif isinstance(files, list):
            entry = next((x for x in files if isinstance(x, dict) and x.get("path") == default_path), None)
    if entry is None:
        entry = {"path": default_path}
    if not isinstance(entry, dict):
        raise EvaluationError(f"Invalid manifest inputs entry for {split}")
    relative = entry.get("path", default_path)
    hashes = manifest.get("input_sha256", manifest.get("inputs_sha256", {}))
    checksum = entry.get("sha256", entry.get("hash"))
    if checksum is None and isinstance(hashes, dict):
        checksum = hashes.get(split) or hashes.get(relative)
    if not isinstance(checksum, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", checksum):
        raise EvaluationError(f"Manifest must declare a SHA256 for {split} inputs")
    return relative, checksum.lower()


def validate_item(item: dict, selected_split: str) -> None:
    identifier = item.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        raise EvaluationError("Every input needs a nonempty string id")
    # Input files may contain labels, but never gold answers or explanations.
    forbidden = {"answer", "correct_answer", "gold", "gold_answer", "answer_key", "solution", "explanation", "analysis"}
    if forbidden.intersection(item):
        raise EvaluationError(f"Answer/solution field found in input {identifier}")
    if not isinstance(item.get("question"), str) or not item["question"].strip():
        raise EvaluationError(f"Missing question in {identifier}")
    options = item.get("options")
    if not isinstance(options, dict) or set(options) != set(LABELS):
        raise EvaluationError(f"Exactly A/B/C/D options required in {identifier}")
    if any(not isinstance(options[key], str) or not options[key].strip() for key in LABELS):
        raise EvaluationError(f"Nonempty option text required in {identifier}")
    if item.get("kind") not in {"public", "variant"}:
        raise EvaluationError(f"Invalid kind in {identifier}")
    if item["kind"] == "variant" and (not isinstance(item.get("parent_id"), str) or not item["parent_id"] or item["parent_id"] == identifier):
        raise EvaluationError(f"Variant must name a distinct parent_id in {identifier}")
    allowed = {"dev", "debug"} if selected_split == "debug" else {"dev", "test"} if selected_split == "all" else {selected_split}
    if item.get("split") not in allowed:
        raise EvaluationError(f"Input {identifier} split {item.get('split')!r} does not belong in {selected_split}")
    assets = item.get("image_assets", [])
    if not isinstance(assets, list):
        raise EvaluationError(f"image_assets must be an array in {identifier}")
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("path"), str):
            raise EvaluationError(f"Invalid image asset in {identifier}")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", str(asset.get("sha256", ""))):
            raise EvaluationError(f"Image SHA256 required in {identifier}")
        field = asset.get("field")
        if field not in {"question", "options.A", "options.B", "options.C", "options.D"}:
            raise EvaluationError(f"Image field must point to question or options.A-D in {identifier}")
        placeholder = asset.get("placeholder")
        text = item["question"] if field == "question" else options[field[-1]]
        if not isinstance(placeholder, str) or not placeholder or placeholder not in text:
            raise EvaluationError(f"Image placeholder does not occur in its field in {identifier}")


def load_dataset(root: Path, split: str) -> tuple[list[dict], dict]:
    root = root.resolve()
    manifest_path = root / "manifest.json"
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise EvaluationError("Manifest must be an object")
    relative, expected = manifest_input_entry(manifest, split)
    # An inputs entry cannot redirect run into an answer table.
    if not relative.startswith("inputs/") or not relative.endswith("_inputs.jsonl"):
        raise EvaluationError("Manifest input must point to inputs/*_inputs.jsonl")
    input_path = contained_path(root, relative)
    try:
        actual = file_sha256(input_path)
    except OSError as exc:
        raise EvaluationError(f"Cannot read inputs: {exc}") from exc
    if actual != expected:
        raise EvaluationError(f"Input SHA256 mismatch: {relative}")
    items = read_jsonl(input_path)
    seen = set()
    for item in items:
        validate_item(item, split)
        if item["id"] in seen:
            raise EvaluationError(f"Duplicate input id: {item['id']}")
        seen.add(item["id"])
    return items, {
        "dataset_root": str(root), "dataset_version": manifest.get("version", "unknown"),
        "dataset_status": manifest.get("status", "unknown"), "manifest_sha256": file_sha256(manifest_path),
        "input_path": relative, "input_sha256": actual, "input_count": len(items), "split": split,
    }


def parse_answer(content: str, refusal: str | None = None) -> dict:
    """Accept one final choice; never select a favourable letter from a list."""
    if refusal:
        return {"status": "refusal", "answer": None, "reason": "provider_refusal"}
    if not isinstance(content, str) or not content.strip():
        return {"status": "parse_failure", "answer": None, "reason": "empty_response"}
    text = unicodedata.normalize("NFKC", content).strip()
    # Split at every explicit marker, including repeated markers on one line.
    markers = list(re.finditer(r"(?:最终答案|最后答案|最终选择|final\s+answer)[*`_]*\s*[:：=]?\s*", text, re.I))
    if markers:
        choices = []
        for number, marker in enumerate(markers):
            end = markers[number + 1].start() if number + 1 < len(markers) else len(text)
            tail = text[marker.end():end].splitlines()[0] if text[marker.end():end].splitlines() else ""
            # A final field is deliberately conservative: one letter with
            # harmless formatting/punctuation, never alternative answers.
            field = re.sub(r"\\boxed\s*\{", "{", tail)
            field = re.sub(r"[\s*`_$\[\](){}]", "", field)
            match = re.fullmatch(r"(?:为|是)?(?:选项)?([A-D])(?:选项)?[。.！!．;；]*", field, re.I)
            if not match:
                return {"status": "parse_failure", "answer": None, "reason": "invalid_final_answer"}
            choices.append(match.group(1).upper())
        if len(set(choices)) != 1:
            return {"status": "parse_failure", "answer": None, "reason": "conflicting_final_answers"}
        return {"status": "ok", "answer": choices[0], "reason": "explicit_final_answer"}
    if re.search(r"(?:无法|不能|不便|拒绝).{0,12}(?:回答|作答|解答)|(?:cannot|can't|unable to|refuse to)\s+(?:answer|assist|solve)|I\s+(?:must\s+)?decline", text, re.I):
        return {"status": "refusal", "answer": None, "reason": "text_refusal"}
    # Only an otherwise standalone choice is accepted as unmarked output.
    stripped = re.sub(r"\s+", "", text).strip("*`$[](){}。.！!．")
    if re.fullmatch(r"[A-D]", stripped, re.I):
        return {"status": "ok", "answer": stripped.upper(), "reason": "standalone_answer"}
    # A single labelled answer on its own is also unambiguous.
    match = re.fullmatch(r"(?:答案|选择|选项|answer)\s*[:：]?\s*([A-D])\s*[。.！!]?", text, re.I)
    if match:
        return {"status": "ok", "answer": match.group(1).upper(), "reason": "single_labelled_answer"}
    return {"status": "parse_failure", "answer": None, "reason": "missing_unique_final_answer"}


def normalize_config(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise EvaluationError("Config must be an object")
    config = copy.deepcopy(raw)
    if "priority_ids" in config:
        priority_ids = config["priority_ids"]
        if not isinstance(priority_ids, list) or any(not isinstance(identifier, str) or not identifier.strip() for identifier in priority_ids):
            raise EvaluationError("priority_ids must be a list of nonempty strings")
        if len(priority_ids) != len(set(priority_ids)):
            raise EvaluationError("priority_ids must not contain duplicates")
    backend = config.get("backend", {})
    if not isinstance(backend, dict):
        raise EvaluationError("backend must be an object")
    forbidden = {"api_key", "authorization", "headers", "token", "access_token"}
    if forbidden.intersection(k.lower() for k in backend):
        raise EvaluationError("Supply credentials only through api_key_env, never inline config or headers")
    backend.setdefault("type", "mock")
    if backend["type"] not in {"mock", "openai-compatible"}:
        raise EvaluationError("backend.type must be mock or openai-compatible")
    backend.setdefault("model", "synthetic-software-check" if backend["type"] == "mock" else "")
    backend.setdefault("supports_images", False)
    backend.setdefault("temperature", 0)
    backend.setdefault("max_output_tokens", 512)
    backend.setdefault("timeout_seconds", 60)
    backend.setdefault("max_retries", 2)
    backend.setdefault("retry_backoff_seconds", 1)
    backend.setdefault("request_interval_seconds", 0)
    backend.setdefault("request_extra", {})
    backend.setdefault("api_key_env", "OPENAI_API_KEY")
    if not isinstance(backend["supports_images"], bool):
        raise EvaluationError("supports_images must be a boolean")
    if "minimum_image_dimension" in backend:
        minimum_dimension = backend["minimum_image_dimension"]
        if isinstance(minimum_dimension, bool) or not isinstance(minimum_dimension, int) or not 0 <= minimum_dimension <= 1024:
            raise EvaluationError("backend.minimum_image_dimension must be an integer from 0 to 1024")
    for key, lower, upper in (("timeout_seconds", 0.01, 3600), ("retry_backoff_seconds", 0, 60), ("request_interval_seconds", 0, 60)):
        value = backend[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not lower <= value <= upper:
            raise EvaluationError(f"Invalid backend.{key}")
    if backend["temperature"] is not None and (
        isinstance(backend["temperature"], bool)
        or not isinstance(backend["temperature"], (int, float))
        or not 0 <= backend["temperature"] <= 2
    ):
        raise EvaluationError("Invalid backend.temperature")
    output_token_parameter = backend.get("output_token_parameter", "max_tokens")
    if not isinstance(output_token_parameter, str) or output_token_parameter not in {"max_tokens", "max_completion_tokens"}:
        raise EvaluationError("backend.output_token_parameter must be max_tokens or max_completion_tokens")
    extra = backend["request_extra"]
    if not isinstance(extra, dict) or any(not isinstance(key, str) for key in extra):
        raise EvaluationError("backend.request_extra must be a string-keyed object")
    blocked = REQUEST_EXTRA_RESERVED.intersection(key.lower() for key in extra)
    if blocked:
        raise EvaluationError(f"request_extra cannot override protected request fields: {', '.join(sorted(blocked))}")
    for key, lower, upper in (("max_retries", 0, 5), ("max_output_tokens", 1, 131072)):
        value = backend[key]
        if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
            raise EvaluationError(f"Invalid backend.{key}")
    if backend["type"] == "openai-compatible":
        if not isinstance(backend["model"], str) or not backend["model"].strip():
            raise EvaluationError("A real backend needs a model name")
        url = urllib.parse.urlsplit(backend.get("base_url", ""))
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise EvaluationError("base_url must be an HTTP(S) URL without credentials, query or fragment")
        if url.scheme == "http" and url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise EvaluationError("Use HTTPS for remote providers (HTTP is allowed only for loopback)")
        backend["base_url"] = backend["base_url"].rstrip("/")
        if not isinstance(backend["api_key_env"], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", backend["api_key_env"]):
            raise EvaluationError("api_key_env must name an environment variable")
    if backend["type"] == "mock" and not isinstance(backend.get("responses", {}), dict):
        raise EvaluationError("mock responses must be an id-to-response mapping")
    config["backend"] = backend
    config.setdefault("data_root", "data/benchmark_web_v0.3")
    root = Path(config["data_root"])
    # Config data_root is relative to the current project directory, matching
    # the repository template, rather than relative to config/.
    config["data_root"] = str(root.resolve())
    config.setdefault("split", "debug")
    for key in ("max_requests", "max_total_tokens"):
        config.setdefault(key, None)
        value = config[key]
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise EvaluationError(f"{key} must be null or a nonnegative integer")
    if config["split"] not in {"debug", "dev", "test", "all"}:
        raise EvaluationError("split must be debug/dev/test/all")
    # Reject unexpected top-level credentials too.
    if forbidden.intersection(k.lower() for k in config):
        raise EvaluationError("Inline credentials are not permitted")
    json_bytes(config)  # Fail before any request for nonfinite/non-JSON values.
    return config


def prioritize_items(items: list[dict], config: dict) -> list[dict]:
    """Move configured IDs to the front without dropping or duplicating rows."""
    priority_ids = config.get("priority_ids")
    if priority_ids is None:
        return items
    by_id = {row["id"]: row for row in items}
    missing = [identifier for identifier in priority_ids if identifier not in by_id]
    if missing:
        raise EvaluationError(f"priority_ids contain unknown dataset ids: {', '.join(missing)}")
    priority_set = set(priority_ids)
    return [by_id[identifier] for identifier in priority_ids] + [row for row in items if row["id"] not in priority_set]


def image_content(
    item: dict,
    root: Path,
    supports_images: bool,
    *,
    minimum_dimension: int = 0,
    processing_evidence: list | None = None,
) -> tuple[list[dict], str | None, str | None]:
    assets = item.get("image_assets", [])
    blocks = []
    # Validate archived assets even for text models; missing files must not be
    # misreported as a model capability limitation.
    for asset in assets:
        try:
            path = contained_path(root, asset["path"])
        except EvaluationError as exc:
            return [], "invalid_image", str(exc)
        if not path.is_file():
            return [], "missing_image", f"Missing image: {asset['path']}"
        try:
            payload = path.read_bytes()
        except OSError as exc:
            return [], "missing_image", f"Cannot read image: {asset['path']} ({exc.__class__.__name__})"
        if hashlib.sha256(payload).hexdigest() != asset["sha256"].lower():
            return [], "invalid_image", f"Image SHA256 mismatch: {asset['path']}"
        mime = asset.get("mime_type", "")
        signatures = {
            "image/png": payload.startswith(PNG_SIGNATURE),
            "image/jpeg": payload.startswith(b"\xff\xd8\xff"),
            "image/gif": payload.startswith((b"GIF87a", b"GIF89a")),
            "image/webp": payload.startswith(b"RIFF") and payload[8:12] == b"WEBP",
        }
        if not signatures.get(mime, False):
            return [], "invalid_image", f"Unsupported or mismatched image MIME: {asset['path']}"
        if supports_images:
            outgoing_payload = payload
            outgoing_mime = mime
            if minimum_dimension > 0:
                try:
                    from PIL import Image, __version__ as pillow_version
                    from io import BytesIO

                    with Image.open(BytesIO(payload)) as source_image:
                        if getattr(source_image, "n_frames", 1) != 1:
                            return [], "invalid_image", f"Multi-frame images cannot be padded: {asset['path']}"
                        source_width, source_height = source_image.size
                        processed_image = source_image.copy()
                    width, height = source_width, source_height
                    operation = "none"
                    padding = None
                    if min(width, height) < minimum_dimension:
                        canvas_width = max(width, minimum_dimension)
                        canvas_height = max(height, minimum_dimension)
                        left = (canvas_width - width) // 2
                        top = (canvas_height - height) // 2
                        padding = {
                            "left": left, "top": top,
                            "right": canvas_width - width - left,
                            "bottom": canvas_height - height - top,
                        }
                        if processed_image.mode in {"RGBA", "LA"} or "transparency" in processed_image.info:
                            processed_image = processed_image.convert("RGBA")
                            canvas = Image.new("RGBA", (canvas_width, canvas_height), (255, 255, 255, 255))
                        else:
                            processed_image = processed_image.convert("RGB")
                            canvas = Image.new("RGB", (canvas_width, canvas_height), (255, 255, 255))
                        canvas.paste(processed_image, (left, top))
                        stream = BytesIO()
                        canvas.save(stream, format="PNG")
                        outgoing_payload = stream.getvalue()
                        outgoing_mime = "image/png"
                        width, height = canvas_width, canvas_height
                        operation = "white_padding"
                    if processing_evidence is not None:
                        processing_evidence.append({
                            "path": asset["path"],
                            "source_sha256": hashlib.sha256(payload).hexdigest(),
                            "derived_sha256": hashlib.sha256(outgoing_payload).hexdigest(),
                            "source_dimensions": [source_width, source_height],
                            "derived_dimensions": [width, height],
                            "operation": operation,
                            "padding_color": "white" if operation == "white_padding" else None,
                            "padding": padding,
                            "pillow_version": pillow_version,
                        })
                except ImportError:
                    return [], "invalid_image", "Pillow is required when minimum_image_dimension is enabled"
                except Exception as exc:
                    return [], "invalid_image", f"Cannot process image {asset['path']} ({exc.__class__.__name__})"
            blocks.append({"type": "text", "text": f"题图对应字段 {asset['field']}，占位符 {asset['placeholder']}："})
            blocks.append({"type": "image_url", "image_url": {"url": f"data:{outgoing_mime};base64,{base64.b64encode(outgoing_payload).decode('ascii')}"}})
    if assets and not supports_images:
        return [], "unsupported_image", "Backend is configured without image support"
    return blocks, None, None


def build_request(item: dict, backend: dict, image_blocks: list[dict]) -> dict:
    text = item["question"] + "\n\n" + "\n".join(f"{key}. {item['options'][key]}" for key in LABELS)
    content: str | list[dict] = [{"type": "text", "text": text}, *image_blocks] if image_blocks else text
    request = {
        "model": backend["model"],
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}],
    }
    if backend.get("temperature", 0) is not None:
        request["temperature"] = backend.get("temperature", 0)
    request[backend.get("output_token_parameter", "max_tokens")] = backend["max_output_tokens"]
    extra = backend.get("request_extra", {})
    if not isinstance(extra, dict) or REQUEST_EXTRA_RESERVED.intersection(str(key).lower() for key in extra):
        raise EvaluationError("request_extra contains protected request fields")
    request.update(copy.deepcopy(extra))
    return request


def redact(value: Any, secret: str) -> Any:
    if not secret:
        return value
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]")
    if isinstance(value, list):
        return [redact(x, secret) for x in value]
    if isinstance(value, dict):
        return {key: redact(val, secret) for key, val in value.items()}
    return value


def extract_response(response: Any) -> tuple[str, str | None, dict]:
    if not isinstance(response, dict):
        raise EvaluationError("Provider response must be an object")
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise EvaluationError("Provider must return exactly one choice")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise EvaluationError("Provider choice has no message")
    content = message.get("content", "")
    if content is None:
        content = ""
    if isinstance(content, list):
        if not all(isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str) for part in content):
            raise EvaluationError("Provider content must contain text blocks only")
        content = "\n".join(part["text"] for part in content)
    if not isinstance(content, str):
        raise EvaluationError("Provider message content must be text")
    refusal = message.get("refusal")
    if refusal is not None and not isinstance(refusal, str):
        raise EvaluationError("Provider refusal must be text")
    usage = response.get("usage", {})
    return content, refusal, usage if isinstance(usage, dict) else {}


def call_mock(item: dict, backend: dict, attempt_number: int) -> dict:
    value = backend.get("responses", {}).get(item["id"], backend.get("default_response", "最终答案：A"))
    if isinstance(value, list):
        if not value:
            raise EvaluationError("Mock response sequence must not be empty")
        value = value[min(attempt_number, len(value) - 1)]
    if isinstance(value, str):
        value = {"response": value}
    if not isinstance(value, dict):
        raise EvaluationError("Mock response must be a string, object or nonempty sequence")
    error = value.get("error")
    if error:
        return {"status": error if error in {"timeout", "api_error", "transport_error"} else "api_error", "error": f"Synthetic {error}", "retryable": bool(value.get("retryable", False)), "raw_response": value}
    response = value.get("raw_response", {"choices": [{"message": {"content": value.get("response", ""), "refusal": value.get("refusal")}}], "usage": value.get("usage", {})})
    return {"status": "received", "raw_response": response, "http_status": 200, "retryable": False}


def call_openai(request: dict, backend: dict, secret: str) -> dict:
    url = backend["base_url"]
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    req = urllib.request.Request(url, data=json_bytes(request), headers=headers, method="POST")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        # Never forward a credential to a redirect destination.
        opener = urllib.request.build_opener(NoRedirect())
        with opener.open(req, timeout=backend["timeout_seconds"]) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = response.status
        try:
            body = json.loads(raw)
        except ValueError:
            return {"status": "invalid_response", "raw_response": raw, "http_status": status, "error": "Provider returned non-JSON content", "retryable": False}
        return {"status": "received", "raw_response": body, "http_status": status, "retryable": False}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(body)
        except ValueError:
            pass
        return {"status": "api_error", "http_status": exc.code, "raw_response": body, "error": f"HTTP {exc.code}", "retryable": exc.code in {408, 409, 425, 429} or 500 <= exc.code <= 599}
    except (TimeoutError, socket.timeout):
        return {"status": "timeout", "error": "Request timed out", "retryable": True}
    except urllib.error.URLError as exc:
        timeout = isinstance(exc.reason, (TimeoutError, socket.timeout))
        return {"status": "timeout" if timeout else "transport_error", "error": str(exc.reason), "retryable": True}
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return {"status": "transport_error", "error": str(exc), "retryable": True}


def item_filename(identifier: str) -> str:
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest() + ".json"


def summary_record(result: dict) -> dict:
    keys = ("id", "run_id", "synthetic", "status", "answer", "parse_reason", "attempted", "attempt_count", "latency_seconds", "usage", "error", "budget_limit_reason", "finished_at")
    row = {key: result[key] for key in keys if key in result}
    row["detail_path"] = "items/" + item_filename(result["id"])
    return row


def response_total_tokens(response: Any) -> int | None:
    usage = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        return None
    total = usage.get("total_tokens")
    if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
        return total
    parts = [usage.get("prompt_tokens"), usage.get("completion_tokens")]
    if all(isinstance(part, int) and not isinstance(part, bool) and part >= 0 for part in parts):
        return sum(parts)
    return None


def budget_usage(metadata: dict) -> dict:
    reservations = metadata.get("remote_attempts", [])
    known = [row["total_tokens"] for row in reservations if row.get("total_tokens") is not None]
    return {
        "remote_request_count": len(reservations), "observed_total_tokens": sum(known),
        "known_usage_request_count": len(known), "unknown_usage_request_count": len(reservations) - len(known),
        "interrupted_or_inflight_request_count": sum(row.get("state") in {"reserved", "interrupted_unknown"} for row in reservations),
        "token_usage_complete": len(known) == len(reservations),
        "token_limit_kind": "observed_usage_threshold_not_a_hard_token_or_money_cap",
    }


def budget_limit_reason(config: dict, metadata: dict) -> str | None:
    if config["backend"]["type"] == "mock":
        return None
    usage = budget_usage(metadata)
    if config["max_requests"] is not None and usage["remote_request_count"] >= config["max_requests"]:
        return "max_requests"
    if config["max_total_tokens"] is not None and usage["observed_total_tokens"] >= config["max_total_tokens"]:
        return "max_total_tokens_observed"
    return None


def reconcile_remote_attempts(metadata: dict, output: Path, items: list[dict]) -> None:
    """Recover usage committed to an item before its budget metadata commit."""
    by_reservation = {row["reservation_id"]: row for row in metadata.setdefault("remote_attempts", [])}
    for item in items:
        path = output / "items" / item_filename(item["id"])
        if not path.exists():
            continue
        detail = read_json(path)
        if detail.get("id") != item["id"] or detail.get("run_id") != metadata["run_id"]:
            raise EvaluationError("Foreign item encountered while reconciling request accounting")
        for attempt in detail.get("attempts", []):
            reservation_id = attempt.get("budget_reservation_id")
            if reservation_id not in by_reservation:
                raise EvaluationError("Remote attempt has no prior budget reservation")
            row = by_reservation[reservation_id]
            if row["item_id"] != item["id"]:
                raise EvaluationError("Budget reservation/item mismatch")
            row.update(state="completed", total_tokens=response_total_tokens(attempt.get("raw_response")))
    # This function runs under a newly acquired model lock before any new
    # request. Unmatched reservations belong to the interrupted process; their
    # provider-side outcome is unknown and their allowance remains consumed.
    for reservation in metadata.get("remote_attempts", []):
        if reservation.get("state") == "reserved":
            reservation["state"] = "interrupted_unknown"
    metadata["budget_usage"] = budget_usage(metadata)


def reserve_remote_attempt(metadata: dict, metadata_path: Path, item_id: str, attempt: int, interval: float) -> str:
    previous = metadata.get("last_remote_request_started_epoch")
    if previous is not None:
        remaining = min(60, max(0, interval - (time.time() - previous)))
        if remaining:
            time.sleep(remaining)
    reservation_id = str(uuid.uuid4())
    metadata.setdefault("remote_attempts", []).append({
        "reservation_id": reservation_id, "item_id": item_id, "attempt": attempt,
        "started_at": utc_now(), "state": "reserved", "total_tokens": None,
    })
    metadata["last_remote_request_started_epoch"] = time.time()
    metadata["budget_usage"] = budget_usage(metadata)
    # Reserve before sending: even an interrupted call consumes the request
    # allowance on resume. Unknown provider usage is explicitly retained.
    write_json(metadata_path, metadata)
    return reservation_id


def execute_run(raw_config: dict, output: Path, resume: bool = False, allow_test: bool = False) -> dict:
    config = normalize_config(raw_config)
    split = config["split"]
    if split in {"test", "all"} and not allow_test:
        raise EvaluationError("Test/all execution requires --allow-test; development checks should use debug/dev")
    backend = config["backend"]
    synthetic = backend["type"] == "mock"
    items, data_info = load_dataset(Path(config["data_root"]), split)
    items = prioritize_items(items, config)
    secret = ""
    if not synthetic:
        secret = os.environ.get(backend["api_key_env"], "")
        if not secret:
            raise EvaluationError(f"Environment variable {backend['api_key_env']} is empty; no request was sent")
    hashes = {
        "config_sha256": digest(config), "prompt_sha256": digest({"version": PROMPT_VERSION, "system_prompt": SYSTEM_PROMPT}),
        "input_sha256": data_info["input_sha256"], "manifest_sha256": data_info["manifest_sha256"], "split": split,
    }
    output = output.resolve()
    with run_lock(output):
        metadata_path = output / "run.json"
        if metadata_path.exists():
            if not resume:
                raise EvaluationError("Run already exists; use --resume or a fresh output directory")
            metadata = read_json(metadata_path)
            if metadata.get("identity") != hashes:
                raise EvaluationError("Resume refused: dataset, manifest, prompt or configuration hash changed")
            current_implementation = file_sha256(Path(__file__).resolve())
            if metadata.get("engine_sha256") != current_implementation:
                history = metadata.setdefault("resume_implementations", [])
                if not any(entry.get("engine_sha256") == current_implementation for entry in history):
                    history.append({"engine_sha256": current_implementation, "recorded_at": utc_now(),
                                    "requests_already_reserved": len(metadata.get("remote_attempts", []))})
        else:
            if resume:
                raise EvaluationError("Cannot resume without run.json")
            # A fresh directory may contain only the lock created above.
            if any(path.name != ".run.lock" for path in output.iterdir()):
                raise EvaluationError("Output directory is not empty and has no run.json")
            metadata = {
                "schema_version": 1, "run_id": str(uuid.uuid4()), "created_at": utc_now(),
                "synthetic": synthetic, "result_kind": "synthetic_software_check" if synthetic else "model_evaluation",
                "config": config, "identity": hashes, "dataset": data_info,
                "prompt_version": PROMPT_VERSION, "system_prompt": SYSTEM_PROMPT,
                "engine_sha256": file_sha256(Path(__file__).resolve()),
                "state": "running", "resume_guarantee": "Committed item results are never requested again. An interrupted in-flight remote request may have reached the provider before local commit.",
                "remote_attempts": [], "budget_usage": budget_usage({}),
            }
            write_json(metadata_path, metadata)
        if not synthetic:
            reconcile_remote_attempts(metadata, output, items)
            write_json(metadata_path, metadata)
        records_path = output / "predictions.jsonl"
        records = read_jsonl(records_path) if records_path.exists() else []
        known_ids = {item["id"] for item in items}
        by_id = {}
        for record in records:
            identifier = record.get("id")
            if identifier not in known_ids or identifier in by_id or record.get("run_id") != metadata["run_id"]:
                raise EvaluationError("Journal contains unknown, duplicate or foreign-run items")
            by_id[identifier] = record
        processed = 0
        recovered = 0
        for item in items:
            identifier = item["id"]
            detail_path = output / "items" / item_filename(identifier)
            if identifier in by_id:
                if not detail_path.exists():
                    raise EvaluationError(f"Committed journal item has no detail: {identifier}")
                committed = read_json(detail_path)
                if not committed.get("complete") or summary_record(committed) != by_id[identifier]:
                    raise EvaluationError(f"Journal/detail mismatch: {identifier}")
                continue
            pending = None
            if detail_path.exists():
                pending = read_json(detail_path)
                if pending.get("id") != identifier or pending.get("run_id") != metadata["run_id"]:
                    raise EvaluationError(f"Foreign item detail: {identifier}")
                if pending.get("complete"):
                    record = summary_record(pending)
                    append_jsonl_atomic(records_path, record)
                    by_id[identifier] = record
                    recovered += 1
                    continue
            minimum_dimension = backend.get("minimum_image_dimension", 0)
            processing_evidence = [] if minimum_dimension > 0 else None
            blocks, skip, error = image_content(
                item,
                Path(config["data_root"]),
                backend["supports_images"],
                minimum_dimension=minimum_dimension,
                processing_evidence=processing_evidence,
            )
            result = pending or {
                "id": identifier, "run_id": metadata["run_id"], "synthetic": synthetic,
                "created_at": utc_now(), "attempts": [], "complete": False,
            }
            if processing_evidence:
                result["image_processing"] = processing_evidence
            if skip:
                result.update(status=skip, answer=None, attempted=False, error=error, usage={}, latency_seconds=0)
            else:
                request = build_request(item, backend, blocks)
                result["raw_request"] = request
                attempts = result["attempts"]
                # Recover a response already atomically written before a crash.
                last = attempts[-1] if attempts else None
                stopped_by_budget = None
                while last is None or (last.get("retryable") and len(attempts) <= backend["max_retries"]):
                    stopped_by_budget = budget_limit_reason(config, metadata)
                    if stopped_by_budget:
                        break
                    if last is not None:
                        time.sleep(min(60, backend["retry_backoff_seconds"] * (2 ** (len(attempts) - 1))))
                    reservation_id = None if synthetic else reserve_remote_attempt(metadata, metadata_path, identifier, len(attempts) + 1, backend["request_interval_seconds"])
                    started = time.monotonic()
                    started_at = utc_now()
                    received = call_mock(item, backend, len(attempts)) if synthetic else call_openai(request, backend, secret)
                    last = {"attempt": len(attempts) + 1, "started_at": started_at, "latency_seconds": round(time.monotonic() - started, 6), **redact(received, secret)}
                    if reservation_id is not None:
                        last["budget_reservation_id"] = reservation_id
                    attempts.append(last)
                    write_json(detail_path, redact(result, secret))
                    if reservation_id is not None:
                        metadata["remote_attempts"][-1].update(state="completed", total_tokens=response_total_tokens(last.get("raw_response")))
                        metadata["budget_usage"] = budget_usage(metadata)
                        write_json(metadata_path, metadata)
                    if not last.get("retryable"):
                        break
                if stopped_by_budget:
                    result["budget_limit_reason"] = stopped_by_budget
                result.update(attempted=bool(attempts), status=last["status"] if last is not None else "unrun_budget_limit", answer=None, usage={}, latency_seconds=round(sum(a["latency_seconds"] for a in attempts), 6))
                if last is not None and last["status"] == "received":
                    try:
                        content, refusal, usage = extract_response(last["raw_response"])
                        parsed = parse_answer(content, refusal)
                        result.update(status=parsed["status"], answer=parsed["answer"], parse_reason=parsed["reason"], response_text=content, usage=usage)
                    except EvaluationError as exc:
                        result.update(status="invalid_response", error=str(exc))
                elif last is not None and "error" in last:
                    result["error"] = last["error"]
            result.update(complete=True, attempt_count=len(result["attempts"]), finished_at=utc_now())
            result = redact(result, secret)
            write_json(detail_path, result)
            record = summary_record(result)
            append_jsonl_atomic(records_path, record)
            by_id[identifier] = record
            processed += 1
        budget_unrun = sum(row["status"] == "unrun_budget_limit" for row in by_id.values())
        metadata.update(state="budget_exhausted" if budget_unrun else "complete", finished_at=utc_now(), completed_count=len(by_id), budget_usage=budget_usage(metadata))
        write_json(metadata_path, metadata)
        summary = {
            "run_id": metadata["run_id"], "synthetic": synthetic, "result_kind": metadata["result_kind"],
            "input_count": len(items), "completed_count": len(by_id), "newly_processed": processed, "recovered_commits": recovered,
            "status_counts": counts([record["status"] for record in by_id.values()]), "output": str(output),
            "budget_usage": metadata["budget_usage"], "budget_unrun_count": budget_unrun,
        }
        write_json(output / "run_summary.json", summary)
        return summary


def counts(values: list) -> dict:
    result = {}
    for value in values:
        result[str(value)] = result.get(str(value), 0) + 1
    return dict(sorted(result.items()))


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def load_answers(root: Path, split: str, expected: set[str]) -> tuple[dict, list[dict]]:
    # debug answers can be their own subset; never substitute test answers.
    manifest = read_json(root / "manifest.json")
    answer_mapping = manifest.get("answers", {})
    if not isinstance(answer_mapping, dict):
        raise EvaluationError("Manifest answers must be a mapping")
    splits = ["dev", "test"] if split == "all" and "all" not in answer_mapping and not (root / "answers" / "all_answers.jsonl").exists() else [split]
    answers = {}
    provenance = []
    for name in splits:
        if name == "debug" and "debug" not in answer_mapping and not (root / "answers" / "debug_answers.jsonl").exists():
            name = "dev"
        default_path = f"answers/{name}_answers.jsonl"
        entry = answer_mapping.get(name)
        if isinstance(entry, str):
            entry = {"path": entry}
        if entry is None:
            files = manifest.get("files", {})
            if isinstance(files, dict):
                entry = files.get(default_path)
                if isinstance(entry, str):
                    entry = {"path": default_path, "sha256": entry}
            elif isinstance(files, list):
                entry = next((row for row in files if isinstance(row, dict) and row.get("path") == default_path), None)
        entry = entry or {"path": default_path}
        if not isinstance(entry, dict):
            raise EvaluationError(f"Invalid manifest answer entry for {name}")
        relative = entry.get("path", default_path)
        hashes = manifest.get("answer_sha256", manifest.get("answers_sha256", {}))
        checksum = entry.get("sha256", entry.get("hash"))
        if checksum is None and isinstance(hashes, dict):
            checksum = hashes.get(name) or hashes.get(relative)
        if not isinstance(checksum, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", checksum):
            raise EvaluationError(f"Manifest must declare a SHA256 for {name} answers")
        if not isinstance(relative, str) or not relative.startswith("answers/") or not relative.endswith("_answers.jsonl"):
            raise EvaluationError("Manifest answer must point to answers/*_answers.jsonl")
        path = contained_path(root, relative)
        try:
            actual = file_sha256(path)
        except OSError as exc:
            raise EvaluationError(f"Cannot read answers: {exc}") from exc
        if actual != checksum.lower():
            raise EvaluationError(f"Answer SHA256 mismatch: {relative}")
        for row in read_jsonl(path):
            identifier, answer = row.get("id"), row.get("answer")
            if not isinstance(identifier, str) or answer not in LABELS:
                raise EvaluationError(f"Invalid answer row in {path}")
            if identifier in answers:
                raise EvaluationError(f"Duplicate answer id: {identifier}")
            answers[identifier] = answer
        provenance.append({"path": relative, "sha256": actual, "manifest_verified": True})
    missing = sorted(expected - answers.keys())
    if missing:
        raise EvaluationError(f"Answer table is missing {len(missing)} expected ids: {missing[:5]}")
    return {key: answers[key] for key in expected}, provenance


def group_metrics(items: list[dict], predictions: dict, answers: dict) -> dict:
    records = [predictions[item["id"]] for item in items if item["id"] in predictions]
    attempted = [row for row in records if row.get("attempted")]
    parsed = [row for row in attempted if row["status"] == "ok" and row.get("answer") in LABELS]
    correct = sum(row["answer"] == answers[row["id"]] for row in parsed)
    return {
        "total": len(items), "recorded": len(records), "unrun": len(items) - len(records) + sum(row["status"] in UNRUN_STATUSES for row in records),
        "unrun_budget_limit": sum(row["status"] == "unrun_budget_limit" for row in records),
        "attempted": len(attempted), "parsed": len(parsed), "correct": correct,
        "skipped": sum(row["status"] in SKIPPED_STATUSES for row in records),
        "request_coverage": ratio(len(attempted), len(items)), "answer_coverage": ratio(len(parsed), len(items)),
        "accuracy": ratio(correct, len(attempted)), "accuracy_among_parsed": ratio(correct, len(parsed)),
        "status_counts": counts([row["status"] for row in records]),
    }


def pair_metrics(items: list[dict], predictions: dict, answers: dict) -> dict:
    by_id = {item["id"]: item for item in items}
    variants = [item for item in items if item["kind"] == "variant"]
    structural = []
    exclusions = {"missing_parent": 0, "cross_split": 0, "invalid_parent": 0, "family_mismatch": 0, "not_both_attempted": 0}
    for variant in variants:
        parent = by_id.get(variant["parent_id"])
        if parent is None:
            exclusions["missing_parent"] += 1
        elif parent["split"] != variant["split"]:
            exclusions["cross_split"] += 1
        elif parent["kind"] != "public":
            exclusions["invalid_parent"] += 1
        elif parent.get("family_id") and variant.get("family_id") and parent["family_id"] != variant["family_id"]:
            exclusions["family_mismatch"] += 1
        else:
            structural.append((parent, variant))
    pairs = []
    for parent, variant in structural:
        p, v = predictions.get(parent["id"]), predictions.get(variant["id"])
        if p is None or v is None or not p.get("attempted") or not v.get("attempted"):
            exclusions["not_both_attempted"] += 1
        else:
            pairs.append((parent, variant, p, v))
    joint = parent_correct = variant_given_parent = same = parsed_pairs = gold_changed = predicted_changed = 0
    for parent, variant, p, v in pairs:
        pc = p["status"] == "ok" and p.get("answer") == answers[parent["id"]]
        vc = v["status"] == "ok" and v.get("answer") == answers[variant["id"]]
        parent_correct += pc
        joint += pc and vc
        variant_given_parent += pc and vc
        gold_changed += answers[parent["id"]] != answers[variant["id"]]
        if p["status"] == v["status"] == "ok":
            parsed_pairs += 1
            same += p["answer"] == v["answer"]
            predicted_changed += p["answer"] != v["answer"]
    return {
        "variant_count": len(variants), "structurally_complete_pairs": len(structural), "actual_complete_pairs": len(pairs),
        "pair_request_coverage": ratio(len(pairs), len(structural)), "joint_correct": joint,
        "joint_accuracy": ratio(joint, len(pairs)), "parent_correct_pairs": parent_correct,
        "conditional_variant_accuracy_given_parent_correct": ratio(variant_given_parent, parent_correct),
        "both_parsed_pairs": parsed_pairs, "same_answer_count": same, "same_answer_rate_among_parsed_pairs": ratio(same, parsed_pairs),
        "gold_answer_changed_pairs": gold_changed, "predicted_answer_changed_parsed_pairs": predicted_changed,
        "excluded": exclusions,
    }


def score_run(output: Path, report_path: Path | None = None) -> dict:
    output = output.resolve()
    metadata = read_json(output / "run.json")
    config = normalize_config(metadata["config"])
    expected_prompt = digest({"version": PROMPT_VERSION, "system_prompt": SYSTEM_PROMPT})
    if digest(config) != metadata["identity"]["config_sha256"] or expected_prompt != metadata["identity"]["prompt_sha256"]:
        raise EvaluationError("Recorded configuration or prompt hash is inconsistent")
    items, data_info = load_dataset(Path(config["data_root"]), config["split"])
    if data_info["input_sha256"] != metadata["identity"]["input_sha256"] or data_info["manifest_sha256"] != metadata["identity"]["manifest_sha256"]:
        raise EvaluationError("Dataset changed after the run; score refused")
    records = read_jsonl(output / "predictions.jsonl") if (output / "predictions.jsonl").exists() else []
    expected = {item["id"] for item in items}
    predictions = {}
    for record in records:
        identifier = record.get("id")
        if identifier not in expected or identifier in predictions or record.get("run_id") != metadata["run_id"]:
            raise EvaluationError("Predictions contain unknown, duplicate or foreign-run ids")
        if record.get("status") not in ATTEMPTED_STATUSES | SKIPPED_STATUSES | UNRUN_STATUSES:
            raise EvaluationError(f"Unknown prediction status: {record.get('status')}")
        if record.get("attempted") != (record["status"] in ATTEMPTED_STATUSES):
            raise EvaluationError("Prediction status/attempted mismatch")
        if record.get("synthetic") is not metadata["synthetic"]:
            raise EvaluationError("Synthetic/model result label mismatch")
        if record["status"] == "ok" and record.get("answer") not in LABELS:
            raise EvaluationError("Successful prediction has no unique A-D answer")
        detail_path = output / "items" / item_filename(identifier)
        detail = read_json(detail_path)
        if not detail.get("complete") or summary_record(detail) != record:
            raise EvaluationError(f"Prediction/detail mismatch: {identifier}")
        predictions[identifier] = record
    answers, provenance = load_answers(Path(config["data_root"]), config["split"], expected)
    groups = {}
    for field in ("split", "grade", "module", "difficulty", "kind"):
        values = sorted({str(item.get(field, "unknown")) for item in items})
        groups[field] = {value: group_metrics([item for item in items if str(item.get(field, "unknown")) == value], predictions, answers) for value in values}
    report = {
        "schema_version": 1, "run_id": metadata["run_id"], "synthetic": metadata["synthetic"],
        "result_kind": metadata["result_kind"], "scored_at": utc_now(), "identity": metadata["identity"],
        "run_state": metadata["state"], "budget_usage": budget_usage(metadata),
        "budget_limits": {"max_requests": config["max_requests"], "max_total_tokens": config["max_total_tokens"]},
        "answer_tables": provenance, "overall": group_metrics(items, predictions, answers), "groups": groups,
        "pairs": pair_metrics(items, predictions, answers),
        "pairs_by_split": {name: pair_metrics([item for item in items if item["split"] == name], predictions, answers) for name in sorted({item["split"] for item in items})},
        "metric_definitions": {
            "accuracy": "correct / attempted; refusal, parse failure, timeout and API/transport errors count as unsuccessful attempts. Skipped and unrun items are excluded and reported through coverage.",
            "answer_coverage": "uniquely parsed answers / all input items",
            "budget_limits": "max_requests counts all reserved remote attempts including retries and interrupted calls across resume. max_total_tokens stops future calls after observed usage reaches the threshold; a response may exceed it and missing usage is unknown. This is not a hard token or money cap. Mock calls do not consume remote budgets.",
            "joint_accuracy": "both correct / structurally valid parent-variant pairs with both items actually requested; never cross dev/test",
            "conditional_variant_accuracy_given_parent_correct": "both correct / actual complete pairs whose parent was correct; null when the denominator is zero",
            "synthetic": "Mock outputs validate software only and are not model performance results.",
        },
    }
    write_json(report_path or output / "score.json", report)
    return report


def self_test() -> dict:
    """Exercise synthetic debug data only; no benchmark answers or network."""
    with tempfile.TemporaryDirectory(prefix="emb-eval-self-test-") as temp:
        root = Path(temp) / "synthetic"
        (root / "inputs").mkdir(parents=True)
        (root / "answers").mkdir()
        image = PNG_SIGNATURE + b"synthetic-signature-fixture"
        (root / "fixture.png").write_bytes(image)
        items = []
        replies = {}
        cases = [("a", "最终答案：A", "A"), ("b", "**最终答案：Ｂ**", "B"), ("c", "计算时可排除 A、B。\n最终答案：C", "C"), ("d", " D ", "D"), ("ambiguous", "最终答案：A 或 B", "A"), ("refusal", "我无法回答这道题", "A"), ("timeout", {"error": "timeout"}, "A")]
        for identifier, response, answer in cases:
            items.append({"id": identifier, "review_no": identifier, "kind": "public", "grade": 7, "module": "synthetic", "difficulty": "synthetic", "parent_id": None, "family_id": identifier, "question": "仅用于软件检查：请选择。", "options": {key: key for key in LABELS}, "image_assets": [], "split": "dev"})
            replies[identifier] = response
        variant = copy.deepcopy(items[0])
        variant.update(id="variant", kind="variant", parent_id="a", family_id="a")
        items.append(variant)
        replies["variant"] = "最终答案：B"
        for identifier, path in (("missing", "missing.png"), ("unsupported", "fixture.png")):
            item = copy.deepcopy(items[0])
            item.update(id=identifier, question="题图[图1]", family_id=identifier, image_assets=[{"path": path, "sha256": hashlib.sha256(image).hexdigest(), "mime_type": "image/png", "field": "question", "placeholder": "[图1]"}])
            items.append(item)
        input_path = root / "inputs" / "debug_inputs.jsonl"
        atomic_write(input_path, b"".join(json_bytes(item) + b"\n" for item in items))
        write_json(root / "manifest.json", {"version": "synthetic-self-test", "status": "synthetic", "inputs": {"debug": {"path": "inputs/debug_inputs.jsonl", "sha256": file_sha256(input_path)}}})
        gold = {identifier: answer for identifier, _, answer in cases}
        gold["variant"] = "B"
        gold.update(missing="A", unsupported="A")
        atomic_write(root / "answers" / "debug_answers.jsonl", b"".join(json_bytes({"id": item["id"], "answer": gold[item["id"]]}) + b"\n" for item in items))
        manifest = read_json(root / "manifest.json")
        manifest["answers"] = {"debug": {"path": "answers/debug_answers.jsonl", "sha256": file_sha256(root / "answers" / "debug_answers.jsonl")}}
        write_json(root / "manifest.json", manifest)
        config = {"data_root": str(root), "split": "debug", "backend": {"type": "mock", "responses": replies, "retry_backoff_seconds": 0}}
        output = Path(temp) / "run"
        first = execute_run(config, output)
        resumed = execute_run(config, output, resume=True)
        report = score_run(output)
        expected_counts = {"ok": 5, "parse_failure": 1, "refusal": 1, "timeout": 1, "missing_image": 1, "unsupported_image": 1}
        if first["status_counts"] != expected_counts or resumed["newly_processed"] != 0:
            raise EvaluationError("Self-test status or resume check failed")
        if report["overall"]["correct"] != 5 or report["pairs"]["joint_accuracy"] != 1:
            raise EvaluationError("Self-test score or pair check failed")
        return {"status": "passed", "synthetic": True, "result_kind": "synthetic_software_check", "items_checked": len(items), "checks": ["A/B/C/D", "format_noise", "ambiguity", "refusal", "timeout", "missing_image", "unsupported_image", "resume_without_duplicates", "paired_metrics"], "note": "Only generated debug fixtures were used; these are not model performance results."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run answer-blind inputs; mock is synthetic")
    run.add_argument("--config", type=Path, default=Path("config/evaluation_template.json"))
    run.add_argument("--split", choices=["debug", "dev", "test", "all"])
    run.add_argument("--data-root", type=Path)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--resume", action="store_true")
    run.add_argument("--allow-test", action="store_true", help="Explicitly authorize test/all execution")
    score = sub.add_parser("score", help="Read separate gold answers and score a run")
    score.add_argument("--run", type=Path, required=True)
    score.add_argument("--output", type=Path)
    sub.add_parser("self-test", help="Synthetic debug fixtures only; no network or benchmark gold")
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            config = read_json(args.config)
            if args.split:
                config["split"] = args.split
            if args.data_root:
                config["data_root"] = str(args.data_root)
            result = execute_run(config, args.output, args.resume, args.allow_test)
        elif args.command == "score":
            report = score_run(args.run, args.output)
            result = {"run_id": report["run_id"], "synthetic": report["synthetic"], "result_kind": report["result_kind"], "overall": report["overall"], "report": str((args.output or args.run / "score.json").resolve())}
        else:
            result = self_test()
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (EvaluationError, OSError, ValueError, KeyError) as exc:
        print(f"Evaluation error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
