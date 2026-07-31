"""Security helpers shared by every module.

Three concerns live here:

1. **Filename sanitisation** - user supplied names are never trusted.
2. **Path containment** - resolved paths must stay inside an allowed directory.
3. **Prompt-injection defence** - text taken from uploaded files is treated as
   untrusted *data*, never as instructions for the model.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from pathlib import Path

from app.core.exceptions import UnsafePathError

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_REPEATED_DOTS = re.compile(r"\.{2,}")
_MAX_STEM_LENGTH = 80

# Phrases commonly used to hijack an LLM through uploaded content.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+instructions"),
    re.compile(r"(?i)disregard\s+(all\s+)?(previous|prior|above)\s+(instructions|rules)"),
    re.compile(r"(?i)forget\s+(everything|all\s+previous)"),
    re.compile(r"(?i)you\s+are\s+now\s+(a|an)\s+"),
    re.compile(r"(?i)\bsystem\s*prompt\b"),
    re.compile(r"(?i)\bdeveloper\s+mode\b"),
    re.compile(r"(?i)reveal\s+(your\s+)?(system\s+)?(prompt|instructions)"),
    re.compile(r"(?i)print\s+(your\s+)?(api[_\s-]?key|secret|token)"),
    re.compile(r"(?i)<\s*/?\s*(system|assistant|human)\s*>"),
)

_INJECTION_PLACEHOLDER = "[filtered]"


def sanitize_filename(filename: str, *, default_stem: str = "upload") -> str:
    """Return a safe filename derived from an untrusted one.

    Strips directory components, unicode tricks, control characters and
    ``..`` sequences. The extension is preserved (lowercased) because the
    upload validator needs it.

    >>> sanitize_filename("../../etc/passwd.csv")
    'passwd.csv'
    """
    raw = unicodedata.normalize("NFKD", filename or "")
    raw = raw.encode("ascii", "ignore").decode("ascii")
    raw = raw.replace("\\", "/")
    # Drop any directory component supplied by the client.
    raw = raw.split("/")[-1]
    raw = raw.strip().strip(".")

    path = Path(raw)
    suffix = path.suffix.lower()
    stem = path.stem if path.stem else default_stem

    stem = _REPEATED_DOTS.sub("_", stem)
    stem = _UNSAFE_CHARS.sub("_", stem).strip("._-")
    if not stem:
        stem = default_stem
    stem = stem[:_MAX_STEM_LENGTH]

    suffix = _UNSAFE_CHARS.sub("", suffix)
    if suffix and not suffix.startswith("."):
        suffix = f".{suffix}"
    return f"{stem}{suffix}"


def build_stored_filename(original_filename: str) -> str:
    """Create a collision free storage name: ``<uuid4>__<sanitised name>``."""
    safe = sanitize_filename(original_filename)
    return f"{uuid.uuid4().hex}__{safe}"


def resolve_safe_path(base_dir: Path, candidate_name: str) -> Path:
    """Join ``candidate_name`` onto ``base_dir`` and guarantee containment.

    Raises:
        UnsafePathError: if the resolved path escapes ``base_dir``.
    """
    base = Path(base_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    target = (base / sanitize_filename(candidate_name)).resolve()
    if base != target and base not in target.parents:
        raise UnsafePathError(
            "The requested file path is not allowed.",
            details={"filename": sanitize_filename(candidate_name)},
        )
    return target


def sha256_of_bytes(payload: bytes) -> str:
    """Return the hex SHA-256 digest of ``payload`` (used to detect re-uploads)."""
    return hashlib.sha256(payload).hexdigest()


def neutralize_prompt_injection(text: str, *, max_length: int = 4000) -> str:
    """Neutralise instruction-like phrases found in untrusted document text.

    Uploaded documents are *data*. This function removes the common hijack
    phrases and truncates the payload before it is embedded in a prompt. It is
    one layer of defence: the prompt templates additionally wrap all untrusted
    content in explicit data delimiters and tell the model to treat it as data.
    """
    if not text:
        return ""
    cleaned = str(text).replace("\x00", "")
    for pattern in _INJECTION_PATTERNS:
        cleaned = pattern.sub(_INJECTION_PLACEHOLDER, cleaned)
    # Collapse very long whitespace runs used to push instructions out of view.
    cleaned = re.sub(r"\s{4,}", "   ", cleaned)
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length] + " …[truncated]"
    return cleaned.strip()


def contains_injection_markers(text: str) -> bool:
    """Return ``True`` if ``text`` looks like it contains prompt-injection bait."""
    if not text:
        return False
    return any(pattern.search(str(text)) for pattern in _INJECTION_PATTERNS)
