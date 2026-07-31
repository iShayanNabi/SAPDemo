"""Safe storage for uploads and generated exports.

Every write and read goes through :func:`app.core.security.resolve_safe_path`,
so a crafted filename such as ``../../app/main.py`` cannot escape the upload or
export directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.core.security import build_stored_filename, resolve_safe_path
from app.services.files.validation import ValidatedUpload

logger = get_logger(__name__)


@dataclass(frozen=True)
class StoredFile:
    """A file that was written into a managed directory."""

    stored_filename: str
    path: Path
    size_bytes: int


def store_upload(upload: ValidatedUpload) -> StoredFile:
    """Persist a validated upload under a collision free name."""
    stored_filename = build_stored_filename(upload.original_filename)
    target = resolve_safe_path(settings.upload_dir, stored_filename)
    target.write_bytes(upload.content)
    logger.info(
        "Stored upload %s (%s bytes) as %s", upload.safe_filename, upload.size_bytes, stored_filename
    )
    return StoredFile(stored_filename=stored_filename, path=target, size_bytes=upload.size_bytes)


def read_upload(stored_filename: str) -> bytes:
    """Read a previously stored upload."""
    path = resolve_safe_path(settings.upload_dir, stored_filename)
    if not path.is_file():
        raise NotFoundError(
            "The uploaded file is no longer available. Please upload it again.",
            details={"stored_filename": stored_filename},
        )
    return path.read_bytes()


def store_export(filename: str, content: bytes) -> StoredFile:
    """Persist generated export bytes into the export directory."""
    target = resolve_safe_path(settings.export_dir, filename)
    target.write_bytes(content)
    logger.info("Stored export %s (%s bytes)", target.name, len(content))
    return StoredFile(stored_filename=target.name, path=target, size_bytes=len(content))


def delete_upload(stored_filename: str) -> bool:
    """Delete a stored upload. Returns ``True`` when a file was removed."""
    path = resolve_safe_path(settings.upload_dir, stored_filename)
    if path.is_file():
        path.unlink()
        return True
    return False
