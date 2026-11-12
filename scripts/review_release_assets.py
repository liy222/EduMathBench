"""Export original, field-bound input images for the reviewed release.

This module never reads review screenshots, answer images, or text from images.
Only ``canonical['image_assets']`` (or an explicit replacement asset list) is a
source.  A placeholder identifies image content; its final field determines the
binding, including when choices have been reordered.
"""
from __future__ import annotations

import hashlib
import io
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "data/benchmark_web_v0.2"

try:
    from PIL import Image
except ImportError:
    sys.path.insert(0, str(ROOT / ".runtime_deps"))
    from PIL import Image


class AssetValidationError(ValueError):
    """An input image cannot be safely bound to the released question."""


PLACEHOLDER_RE = re.compile(r"\[图片:[^\[\]\r\n]+\]")
FIGURE_REFERENCE_RE = re.compile(r"如图|图中|图所示|下图|上图|左图|右图|图\s*[0-9一二三四五六七八九十]")
FIELDS = ("question", "option_a", "option_b", "option_c", "option_d")
_FORMATS = {
    "PNG": (".png", "image/png"),
    "JPEG": (".jpg", "image/jpeg"),
    "GIF": (".gif", "image/gif"),
    "WEBP": (".webp", "image/webp"),
    "BMP": (".bmp", "image/bmp"),
    "TIFF": (".tif", "image/tiff"),
}


def _label(question: Mapping[str, Any]) -> str:
    return str(question.get("id", "<question>"))


def input_fields(question: Mapping[str, Any]) -> dict[str, str]:
    """Return just the stem and four choices, with canonical field names."""
    result = {"question": question.get("question", "")}
    choices = question.get("options")
    for letter in "ABCD":
        field = "option_" + letter.lower()
        if isinstance(choices, Mapping):
            value = choices.get(letter, choices.get(letter.lower(), ""))
        else:
            value = question.get(field, "")
        result[field] = value
    for field, value in result.items():
        if not isinstance(value, str):
            raise AssetValidationError(f"{_label(question)}: {field} must be text")
    return result


def _normal_field(asset: Mapping[str, Any]) -> str:
    value = asset.get("field", asset.get("source_placeholder_field"))
    role = str(asset.get("role", ""))
    if value is None and role in {"stem", "question"}:
        value = "question"
    if value is None and role.lower().startswith("option_"):
        value = role.lower()
    if value == "stem":
        value = "question"
    if isinstance(value, str):
        value = value.lower()
        if value.startswith("options."):
            value = "option_" + value.rsplit(".", 1)[-1]
    if value not in FIELDS:
        raise AssetValidationError(f"Input image has invalid or missing field: {value!r}")
    return value


def _input_assets(assets: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(assets, Sequence) or isinstance(assets, (str, bytes)):
        raise AssetValidationError("image_assets must be a list of asset objects")
    result = []
    for original in assets:
        if not isinstance(original, Mapping):
            raise AssetValidationError("Every image asset must be an object")
        role = str(original.get("role", "")).lower()
        # A matching placeholder must never make an answer/solution eligible.
        if role in {"answer", "solution", "analysis", "explanation"} or original.get("contains_answer_or_solution"):
            continue
        if role not in {"stem", "question", "option", "option_a", "option_b", "option_c", "option_d"}:
            raise AssetValidationError(f"Unsupported input image role: {role!r}")
        if "screenshot" in str(original.get("asset_type", "")).lower():
            raise AssetValidationError("Full-question screenshots are not input assets")
        asset = dict(original)
        asset["field"] = _normal_field(asset)
        asset["role"] = "stem" if asset["field"] == "question" else "option"
        placeholder = asset.get("placeholder", "")
        if placeholder is None:
            placeholder = ""
        if not isinstance(placeholder, str) or (placeholder and not PLACEHOLDER_RE.fullmatch(placeholder)):
            raise AssetValidationError(f"Invalid image placeholder: {placeholder!r}")
        asset["placeholder"] = placeholder
        result.append(asset)
    return result


def _source_path(asset: Mapping[str, Any], source_root: Path) -> Path:
    value = asset.get("path", asset.get("local_path"))
    if not isinstance(value, (str, Path)) or not str(value):
        raise AssetValidationError("Input image has no local source path")
    root = source_root.resolve()
    source = (root / value).resolve()
    if not source.is_relative_to(root):
        raise AssetValidationError(f"Image source is outside source_root: {value}")
    if not source.is_file():
        raise AssetValidationError(f"Input image source is missing: {source}")
    return source


def _inspect_source(asset: Mapping[str, Any], source_root: Path,
                    cache: dict[Path, tuple[bytes, str, str, str]]) -> tuple[bytes, str, str, str]:
    source = _source_path(asset, source_root)
    expected = asset.get("sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise AssetValidationError(f"Input image is missing a valid SHA-256: {source}")
    if source not in cache:
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        try:
            with Image.open(io.BytesIO(data)) as image:
                image_format = image.format
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                if image.width <= 0 or image.height <= 0:
                    raise ValueError("empty image")
            if image_format not in _FORMATS:
                raise ValueError(f"unsupported image format {image_format!r}")
        except Exception as exc:
            raise AssetValidationError(f"Input image cannot be opened: {source}: {exc}") from exc
        suffix, mime_type = _FORMATS[image_format]
        cache[source] = (data, digest, suffix, mime_type)
    inspected = cache[source]
    if inspected[1] != expected.lower():
        raise AssetValidationError(
            f"Input image SHA-256 mismatch: {source}; expected {expected}, got {inspected[1]}"
        )
    return inspected


def _placeholder_index(assets: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    index: dict[str, list[Mapping[str, Any]]] = {}
    for asset in assets:
        if asset["placeholder"]:
            index.setdefault(asset["placeholder"], []).append(asset)
    for placeholder, matches in index.items():
        hashes = {str(asset.get("sha256", "")).lower() for asset in matches}
        if len(hashes) != 1:
            raise AssetValidationError(f"Placeholder maps to different image hashes: {placeholder}")
    return index


def _check_references(question: Mapping[str, Any], fields: Mapping[str, str],
                      index: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    for field, value in fields.items():
        if "[图片:" in PLACEHOLDER_RE.sub("", value):
            raise AssetValidationError(f"{_label(question)}: {field} contains a malformed image placeholder")
        for placeholder in dict.fromkeys(PLACEHOLDER_RE.findall(value)):
            if placeholder not in index:
                raise AssetValidationError(
                    f"{_label(question)}: {field} placeholder has no eligible source image: {placeholder}"
                )


def assert_source_assets(canonical: Mapping[str, Any], source_root: str | Path | None = None) -> None:
    """Verify source hashes, readable images, and original field bindings.

    Repeated placeholders and one image used in several choices are valid. A
    placeholder used for different bytes, or registered under the wrong original
    field, is an error. Answer/solution assets are excluded from eligible sources.
    """
    root = Path(source_root) if source_root is not None else SOURCE_ROOT
    fields = input_fields(canonical)
    assets = _input_assets(canonical.get("image_assets", []))
    index = _placeholder_index(assets)
    _check_references(canonical, fields, index)
    cache: dict[Path, tuple[bytes, str, str, str]] = {}
    for asset in assets:
        if asset["placeholder"] and asset["placeholder"] not in PLACEHOLDER_RE.findall(fields[asset["field"]]):
            raise AssetValidationError(
                f"{_label(canonical)}: source asset placeholder is absent from {asset['field']}: {asset['placeholder']}"
            )
        _inspect_source(asset, root, cache)


def export_assets(question: Mapping[str, Any], canonical: Mapping[str, Any],
                  output_root: str | Path, overrides: Mapping[str, Any] | None = None) -> list[dict[str, str]]:
    """Copy only the original images still required by the released input.

    ``question`` supplies the final question/options. ``canonical`` supplies the
    original image manifest. ``overrides`` accepts:

    * ``source_root``: root for all source paths (default: benchmark_web_v0.2).
    * ``assets``: a complete replacement source list; ``[]`` explicitly removes
      obsolete figures after a text-only rewrite. New figures need source hashes.
    * ``drop_unreferenced``: explicitly omit figures with no placeholder.

    Original figures without placeholders remain when their field is unchanged
    or still refers to a figure. If a rewrite removes that figure reference, an
    explicit replacement/removal is required instead of guessing whether the
    figure became unnecessary. Assets whose placeholder disappeared are omitted.
    No OCR, rendering, or mutation of either question object is performed.
    The result has one binding per field/placeholder/content, so the same image
    can be used by several choices without duplicating its copied file.
    """
    options = dict(overrides or {})
    unknown = set(options) - {"source_root", "assets", "drop_unreferenced"}
    if unknown:
        raise AssetValidationError(f"Unknown asset override settings: {sorted(unknown)}")
    root = Path(options.get("source_root", SOURCE_ROOT))
    output = Path(output_root).resolve()
    fields = input_fields(question)
    original_fields = input_fields(canonical)
    assets = _input_assets(options.get("assets", canonical.get("image_assets", [])))
    index = _placeholder_index(assets)
    _check_references(question, fields, index)

    selected: list[tuple[str, str, Mapping[str, Any]]] = []
    for field, value in fields.items():
        for placeholder in dict.fromkeys(PLACEHOLDER_RE.findall(value)):
            candidates = index[placeholder]
            # Prefer the original occurrence in this field. Moving an otherwise
            # unambiguous placeholder between choices preserves its image bytes.
            asset = next((a for a in candidates if a["field"] == field), candidates[0])
            selected.append((field, placeholder, asset))
        if not options.get("drop_unreferenced", False):
            for asset in assets:
                if asset["field"] == field and not asset["placeholder"]:
                    if "assets" in options or value == original_fields[field] or FIGURE_REFERENCE_RE.search(value):
                        selected.append((field, "", asset))
                    else:
                        raise AssetValidationError(
                            f"{_label(question)}: {field} was rewritten without a figure reference; "
                            "explicitly replace or remove its original unplaced image with overrides.assets "
                            "or overrides.drop_unreferenced"
                        )

    cache: dict[Path, tuple[bytes, str, str, str]] = {}
    prepared = []
    seen = set()
    for field, placeholder, asset in selected:
        data, digest, suffix, mime_type = _inspect_source(asset, root, cache)
        key = (field, placeholder, digest)
        if key in seen:
            continue
        seen.add(key)
        relative = Path("assets/input") / (digest + suffix)
        prepared.append((relative, data, {
            "path": relative.as_posix(), "sha256": digest, "mime_type": mime_type,
            "field": field, "placeholder": placeholder,
            "role": "stem" if field == "question" else "option",
        }))

    # Validate every selected source before writing anything. Existing content
    # addressed files must match too; an inconsistent destination is never reused.
    for relative, data, record in prepared:
        destination = output / relative
        if destination.exists() and (not destination.is_file() or hashlib.sha256(destination.read_bytes()).hexdigest() != record["sha256"]):
            raise AssetValidationError(f"Output image conflicts with its content hash: {destination}")
    for relative, data, _record in prepared:
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            destination.write_bytes(data)
    return [record for _relative, _data, record in prepared]
