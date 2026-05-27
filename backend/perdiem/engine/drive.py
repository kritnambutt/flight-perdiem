"""Roster attachment download from Google Drive."""
from __future__ import annotations

import logging
import re
import subprocess
import time
from pathlib import Path

import requests

from perdiem.engine.models import Claim, RosterRef

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BACKOFF = 1.0  # seconds, doubled each attempt

_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "application/pdf": "pdf",
}

_DRIVE_PATTERNS = [
    re.compile(r"drive\.google\.com/(?:open\?id=|file/d/)([a-zA-Z0-9_-]{10,})"),
    re.compile(r"docs\.google\.com/.*?/d/([a-zA-Z0-9_-]{10,})"),
    re.compile(r"[?&]id=([a-zA-Z0-9_-]{10,})"),
]

_DRIVE_DOWNLOAD_URL = "https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"


def extract_file_id(url: str) -> str | None:
    """Return the Google Drive file id from a URL, or None if not parseable."""
    for pattern in _DRIVE_PATTERNS:
        m = pattern.search(url)
        if m:
            return m.group(1)
    return None


def _get_access_token(account: str) -> str:
    result = subprocess.run(
        ["gcloud", "auth", "print-access-token", f"--account={account}"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gcloud auth failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _download_file(file_id: str, dest: Path, account: str) -> str:
    """
    Download a Drive file to dest. Returns the content-type on success.
    Retries on transient errors; raises immediately on 403/404.
    """
    token = _get_access_token(account)
    url = _DRIVE_DOWNLOAD_URL.format(file_id=file_id)
    headers = {"Authorization": f"Bearer {token}"}

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, headers=headers, timeout=60, stream=True)
            if resp.status_code == 403:
                raise PermissionError(f"403 Forbidden for file {file_id}")
            if resp.status_code == 404:
                raise FileNotFoundError(f"404 Not Found for file {file_id}")
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "").split(";")[0].strip()
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=65536):
                    fh.write(chunk)
            return content_type
        except (PermissionError, FileNotFoundError):
            raise
        except Exception as exc:
            last_exc = exc
            wait = _RETRY_BACKOFF * (2**attempt)
            logger.warning(
                "Drive download attempt %d/%d failed (%s); retrying in %.1fs",
                attempt + 1, _MAX_RETRIES, exc, wait,
            )
            time.sleep(wait)

    raise RuntimeError(f"Download failed after {_MAX_RETRIES} attempts") from last_exc


def _resolve_ref(url: str, cache_dir: Path, account: str) -> RosterRef:
    """Download one Drive URL and return a RosterRef (using the cache)."""
    file_id = extract_file_id(url)
    if file_id is None:
        logger.warning("Could not parse Drive file ID from URL: %s", url)
        return RosterRef(
            source_url=url, file_id=None, local_path=None,
            content_type=None, status="UNREACHABLE",
        )

    # Cache hit: any file matching <file_id>.*
    for cached in cache_dir.glob(f"{file_id}.*"):
        if cached.suffix == ".tmp":
            continue
        ext = cached.suffix.lstrip(".")
        mime = next((k for k, v in _MIME_TO_EXT.items() if v == ext), None)
        logger.debug("Cache hit: %s", cached)
        return RosterRef(
            source_url=url, file_id=file_id, local_path=str(cached),
            content_type=mime, status="OK",
        )

    tmp = cache_dir / f"{file_id}.tmp"
    try:
        content_type = _download_file(file_id, tmp, account)
        ext = _MIME_TO_EXT.get(content_type)
        if ext is None:
            tmp.unlink(missing_ok=True)
            logger.warning("Unsupported MIME '%s' for file %s", content_type, file_id)
            return RosterRef(
                source_url=url, file_id=file_id, local_path=None,
                content_type=content_type, status="UNSUPPORTED",
            )
        final = cache_dir / f"{file_id}.{ext}"
        tmp.rename(final)
        return RosterRef(
            source_url=url, file_id=file_id, local_path=str(final),
            content_type=content_type, status="OK",
        )
    except (PermissionError, FileNotFoundError) as exc:
        tmp.unlink(missing_ok=True)
        logger.warning("Drive file unreachable: %s — %s", url, exc)
        return RosterRef(
            source_url=url, file_id=file_id, local_path=None,
            content_type=None, status="UNREACHABLE",
        )
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        logger.error("Unexpected error downloading %s: %s", url, exc)
        return RosterRef(
            source_url=url, file_id=file_id, local_path=None,
            content_type=None, status="UNREACHABLE",
        )


def fetch_rosters(
    claim: Claim,
    cache_dir: Path | None = None,
    account: str | None = None,
) -> list[RosterRef]:
    """Download all roster attachments for a claim, using the on-disk cache."""
    from perdiem.config import settings

    resolved_cache = Path(cache_dir) if cache_dir is not None else Path(settings.roster_cache_dir)
    resolved_account = account or settings.drive_account
    resolved_cache.mkdir(parents=True, exist_ok=True)

    return [_resolve_ref(url, resolved_cache, resolved_account) for url in claim.roster_links]
