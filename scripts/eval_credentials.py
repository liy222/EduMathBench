"""Load six local API credentials as data, without executing shell code."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import MutableMapping


ROOT = Path(__file__).resolve().parents[1]
KEY_NAMES = (
    "DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "ZHIPU_API_KEY",
    "MOONSHOT_API_KEY", "MINIMAX_API_KEY", "ARK_API_KEY",
)


class CredentialFileError(ValueError):
    """A local file-format error; messages never contain credential values."""


def load_project_env(root: Path = ROOT, environ: MutableMapping[str, str] | None = None) -> dict:
    """Fill missing process variables from .env.local; existing values take priority.

    All lines are validated before making changes. Blank entries do not create
    fake credentials. Values are literal; expansion, execution, and arbitrary
    environment-variable assignment are intentionally unsupported.
    """
    target = os.environ if environ is None else environ
    path = root / ".env.local"
    values: dict[str, str] = {}
    if path.exists():
        try:
            if path.stat().st_size > 65536:
                raise CredentialFileError(".env.local exceeds the file-size limit")
            content = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise CredentialFileError("Cannot read the local credential file") from exc
        for number, original in enumerate(content.splitlines(), 1):
            line = original.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise CredentialFileError(f"Invalid credential-file syntax on line {number}")
            name, value = line.split("=", 1)
            name, value = name.strip(), value.strip()
            if name not in KEY_NAMES or name in values:
                raise CredentialFileError(f"Unknown or repeated variable on line {number}")
            if value[:1] in {"'", '"'}:
                if len(value) < 2 or value[-1] != value[0]:
                    raise CredentialFileError(f"Unclosed quotes on line {number}")
                value = value[1:-1]
            if any(ord(char) < 32 or char.isspace() for char in value):
                raise CredentialFileError(f"Whitespace or control character on line {number}")
            values[name] = value
        for name, value in values.items():
            if value and not target.get(name):
                target[name] = value
    return {
        "credential_file": str(path),
        "credential_file_exists": path.is_file(),
        "variables": {name: bool(target.get(name)) for name in KEY_NAMES},
    }


if __name__ == "__main__":
    try:
        print(json.dumps(load_project_env(), ensure_ascii=False, indent=2))
    except CredentialFileError as exc:
        raise SystemExit(str(exc)) from None
