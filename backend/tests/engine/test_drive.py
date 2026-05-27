"""Unit tests for drive.py — roster attachment download."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from perdiem.engine.drive import extract_file_id, fetch_rosters
from perdiem.engine.models import Claim, RosterRef


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_claim(roster_links: list[str]) -> Claim:
    return Claim(
        source="POSTING_BASE",
        source_row_ref="test!2",
        timestamp=None,
        email="test@example.com",
        staff_id="1234567",
        name="Test Crew",
        position="CC",
        base="DMK",
        claim_type="PD",
        claim_month="MARCH 2026",
        claimed_days=[1, 2, 3],
        roster_links=roster_links,
    )


def _gcloud_ok(token: str = "test-token") -> MagicMock:
    m = MagicMock()
    m.returncode = 0
    m.stdout = f"{token}\n"
    return m


def _http_response(
    status_code: int = 200,
    content_type: str = "image/jpeg",
    content: bytes = b"\xff\xd8\xff" + b"\x00" * 100,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"content-type": content_type}
    resp.iter_content = lambda chunk_size=65536: [content]
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

class TestExtractFileId:
    def test_open_id_param(self):
        url = "https://drive.google.com/open?id=1BxiMVs0XRA5nFMdKvBdBZjgm"
        assert extract_file_id(url) == "1BxiMVs0XRA5nFMdKvBdBZjgm"

    def test_file_d_path(self):
        url = "https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgm/view"
        assert extract_file_id(url) == "1BxiMVs0XRA5nFMdKvBdBZjgm"

    def test_docs_d_path(self):
        url = "https://docs.google.com/document/d/1BxiMVs0XRA5nFMdKvBdBZjgm/edit"
        assert extract_file_id(url) == "1BxiMVs0XRA5nFMdKvBdBZjgm"

    def test_uc_export_id_param(self):
        url = "https://drive.google.com/uc?export=download&id=1BxiMVs0XRA5nFMdKvBdBZjgm"
        assert extract_file_id(url) == "1BxiMVs0XRA5nFMdKvBdBZjgm"

    def test_non_drive_url_returns_none(self):
        assert extract_file_id("https://example.com/file.jpg") is None

    def test_empty_string_returns_none(self):
        assert extract_file_id("") is None


# ---------------------------------------------------------------------------
# fetch_rosters — happy paths
# ---------------------------------------------------------------------------

class TestFetchRosters:
    def test_empty_links_returns_empty(self, tmp_path):
        refs = fetch_rosters(_make_claim([]), cache_dir=tmp_path, account="a@b.com")
        assert refs == []

    def test_jpeg_downloaded_and_cached(self, tmp_path):
        claim = _make_claim(["https://drive.google.com/file/d/JPEG_ID_1234567890/view"])
        with patch("subprocess.run", return_value=_gcloud_ok()), \
             patch("requests.get", return_value=_http_response("image/jpeg")):
            refs = fetch_rosters(claim, cache_dir=tmp_path, account="a@b.com")

        assert len(refs) == 1
        r = refs[0]
        assert r.status == "OK"
        assert r.content_type == "image/jpeg"
        assert r.local_path is not None and r.local_path.endswith(".jpg")
        assert Path(r.local_path).exists()

    def test_pdf_downloaded(self, tmp_path):
        claim = _make_claim(["https://drive.google.com/open?id=PDF_ID_12345678901"])
        with patch("subprocess.run", return_value=_gcloud_ok()), \
             patch("requests.get", return_value=_http_response(content_type="application/pdf", content=b"%PDF-1.4")):
            refs = fetch_rosters(claim, cache_dir=tmp_path, account="a@b.com")

        assert refs[0].status == "OK"
        assert refs[0].local_path.endswith(".pdf")

    def test_png_downloaded(self, tmp_path):
        claim = _make_claim(["https://drive.google.com/file/d/PNG_ID_1234567890a/view"])
        with patch("subprocess.run", return_value=_gcloud_ok()), \
             patch("requests.get", return_value=_http_response(content_type="image/png", content=b"\x89PNG")):
            refs = fetch_rosters(claim, cache_dir=tmp_path, account="a@b.com")

        assert refs[0].status == "OK"
        assert refs[0].local_path.endswith(".png")

    def test_multiple_links_all_downloaded(self, tmp_path):
        claim = _make_claim([
            "https://drive.google.com/file/d/MULTI_ONE_ID_12345678/view",
            "https://drive.google.com/file/d/MULTI_TWO_ID_12345678/view",
        ])
        with patch("subprocess.run", return_value=_gcloud_ok()), \
             patch("requests.get", return_value=_http_response()):
            refs = fetch_rosters(claim, cache_dir=tmp_path, account="a@b.com")

        assert len(refs) == 2
        assert all(r.status == "OK" for r in refs)


# ---------------------------------------------------------------------------
# fetch_rosters — error scenarios
# ---------------------------------------------------------------------------

    def test_403_marks_unreachable(self, tmp_path):
        claim = _make_claim(["https://drive.google.com/file/d/FORBIDDEN_1234567890/view"])
        with patch("subprocess.run", return_value=_gcloud_ok()), \
             patch("requests.get", return_value=_http_response(403)):
            refs = fetch_rosters(claim, cache_dir=tmp_path, account="a@b.com")

        assert refs[0].status == "UNREACHABLE"
        assert refs[0].local_path is None

    def test_404_marks_unreachable(self, tmp_path):
        claim = _make_claim(["https://drive.google.com/file/d/MISSING_ID_12345678a/view"])
        with patch("subprocess.run", return_value=_gcloud_ok()), \
             patch("requests.get", return_value=_http_response(404)):
            refs = fetch_rosters(claim, cache_dir=tmp_path, account="a@b.com")

        assert refs[0].status == "UNREACHABLE"

    def test_html_mime_marks_unsupported(self, tmp_path):
        claim = _make_claim(["https://drive.google.com/file/d/HTML_ID_1234567890a/view"])
        with patch("subprocess.run", return_value=_gcloud_ok()), \
             patch("requests.get", return_value=_http_response(200, "text/html")):
            refs = fetch_rosters(claim, cache_dir=tmp_path, account="a@b.com")

        assert refs[0].status == "UNSUPPORTED"
        assert refs[0].local_path is None

    def test_non_drive_url_marks_unreachable(self, tmp_path):
        claim = _make_claim(["https://example.com/not-a-drive-link"])
        refs = fetch_rosters(claim, cache_dir=tmp_path, account="a@b.com")

        assert refs[0].status == "UNREACHABLE"
        assert refs[0].file_id is None

    def test_cache_hit_skips_download(self, tmp_path):
        file_id = "CACHED_ID_1234567890a"
        (tmp_path / f"{file_id}.jpg").write_bytes(b"\xff\xd8\xff")

        claim = _make_claim([f"https://drive.google.com/file/d/{file_id}/view"])
        with patch("subprocess.run") as mock_run, patch("requests.get") as mock_get:
            refs = fetch_rosters(claim, cache_dir=tmp_path, account="a@b.com")
            mock_run.assert_not_called()
            mock_get.assert_not_called()

        assert refs[0].status == "OK"
        assert refs[0].local_path == str(tmp_path / f"{file_id}.jpg")

    def test_duplicate_file_id_downloaded_once(self, tmp_path):
        file_id = "SHARED_ID_1234567890a"
        url = f"https://drive.google.com/file/d/{file_id}/view"

        with patch("subprocess.run", return_value=_gcloud_ok()), \
             patch("requests.get", return_value=_http_response()) as mock_get:
            refs1 = fetch_rosters(_make_claim([url]), cache_dir=tmp_path, account="a@b.com")
            assert mock_get.call_count == 1

        # Second claim uses cache — no new download
        with patch("subprocess.run") as mock_run, patch("requests.get") as mock_get2:
            refs2 = fetch_rosters(_make_claim([url]), cache_dir=tmp_path, account="a@b.com")
            mock_run.assert_not_called()
            mock_get2.assert_not_called()

        assert refs1[0].local_path == refs2[0].local_path

    def test_content_type_with_charset_param(self, tmp_path):
        """content-type header params (e.g. '; charset=utf-8') are stripped."""
        claim = _make_claim(["https://drive.google.com/file/d/CHARSET_ID_123456789/view"])
        with patch("subprocess.run", return_value=_gcloud_ok()), \
             patch("requests.get", return_value=_http_response(200, "image/jpeg; charset=utf-8")):
            refs = fetch_rosters(claim, cache_dir=tmp_path, account="a@b.com")

        assert refs[0].status == "OK"
        assert refs[0].content_type == "image/jpeg"
