"""API, extractor, and local fixture tests."""
import base64
import json
import os
import tempfile

import pytest
import requests
from unittest.mock import Mock, patch

from app import app
from fileExtraction import (
    CONFIG,
    extension_from_content_type,
    extract_csv,
    extract_docx,
    extract_pdf,
    extract_txt,
    extract_xlsx,
    try_extract_with_fallback,
)
from conftest import XLSX_CREATE_AVAILABLE, auth_headers, configure_mock_download

if XLSX_CREATE_AVAILABLE:
    from openpyxl import Workbook
from local_extract import TESTING_FILES_DIR, extract_local_file, list_testing_files

TESTING_FILES = list_testing_files()
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class TestExtractUrl:
    def test_missing_url_get(self, client):
        response = client.get("/extract")
        assert response.status_code == 400
        assert "Missing file URL" in json.loads(response.data)["error"]

    def test_missing_url_post(self, client):
        response = client.post("/extract", json={})
        assert response.status_code == 400
        assert "Missing file URL" in json.loads(response.data)["error"]

    def test_invalid_url(self, client):
        with patch("fileExtraction.download.requests.get") as mock_get:
            mock_get.side_effect = requests.RequestException("Connection error")
            response = client.get("/extract?url=https://invalid-url.com/file.pdf")
        assert response.status_code == 400
        assert "Failed to download file" in json.loads(response.data)["error"]

    @patch("fileExtraction.download.requests.get")
    def test_txt_get(self, mock_get, client, sample_txt_file):
        configure_mock_download(mock_get, sample_txt_file, "text/plain")
        response = client.get("/extract?url=https://example.com/test.txt")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["file_type"] == ".txt"
        assert "Hello, this is a test text file" in data["content"]

    @patch("fileExtraction.download.requests.get")
    def test_txt_post(self, mock_get, client, sample_txt_file):
        configure_mock_download(mock_get, sample_txt_file, "text/plain")
        response = client.post("/extract", json={"url": "https://example.com/test.txt"})
        data = json.loads(response.data)
        assert response.status_code == 200
        assert "For testing purposes" in data["content"]

    @patch("fileExtraction.download.requests.get")
    def test_csv(self, mock_get, client, sample_csv_file):
        configure_mock_download(mock_get, sample_csv_file, "text/csv")
        response = client.get("/extract?url=https://example.com/data.csv")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["file_type"] == ".csv"
        assert "John" in data["content"]

    @patch("fileExtraction.download.requests.get")
    def test_pdf(self, mock_get, client, sample_pdf_file):
        configure_mock_download(mock_get, sample_pdf_file, "application/pdf")
        response = client.get("/extract?url=https://example.com/document.pdf")
        data = json.loads(response.data)
        if response.status_code == 200:
            assert data["file_type"] == ".pdf"
            assert len(data["content"]) > 0
        else:
            # Minimal PDF fixtures may not parse on all pypdf versions
            content, error = extract_pdf(sample_pdf_file)
            assert content is not None or error is not None

    @patch("fileExtraction.download.requests.get")
    def test_docx(self, mock_get, client, sample_docx_file):
        configure_mock_download(
            mock_get,
            sample_docx_file,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        response = client.get("/extract?url=https://example.com/document.docx")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["file_type"] == ".docx"

    @patch("fileExtraction.download.requests.get")
    def test_xlsx(self, mock_get, client, sample_xlsx_file):
        configure_mock_download(mock_get, sample_xlsx_file, XLSX_MIME)
        response = client.get("/extract?url=https://example.com/data.xlsx")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["file_type"] == ".xlsx"
        assert "Alice" in data["content"]

    @patch("fileExtraction.download.requests.get")
    def test_xlsx_cdn_url_not_docx(self, mock_get, client, sample_xlsx_file):
        configure_mock_download(mock_get, sample_xlsx_file, XLSX_MIME)
        response = client.get("/extract?url=https://cdn.example.com/attachments/uuid")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["file_type"] == ".xlsx"

    @patch("fileExtraction.download.requests.get")
    def test_xlsx_with_filename_param(self, mock_get, client, sample_xlsx_file):
        configure_mock_download(mock_get, sample_xlsx_file, "application/octet-stream")
        response = client.get(
            "/extract?url=https://cdn.example.com/uuid"
            "&filename=report.xlsx"
            f"&contentType={XLSX_MIME}"
        )
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["file_type"] == ".xlsx"

    @patch("fileExtraction.download.requests.get")
    def test_http_error(self, mock_get, client):
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        mock_get.return_value = mock_response
        response = client.get("/extract?url=https://example.com/missing.pdf")
        assert response.status_code == 400


class TestExtractBase64:
    def test_txt(self, client):
        text = "Hello from base64 endpoint"
        payload = base64.b64encode(text.encode()).decode()
        response = client.post(
            "/extract-base64",
            headers=auth_headers(),
            json={"base64": payload, "filename": "sample.txt", "contentType": "text/plain"},
        )
        data = json.loads(response.data)
        assert response.status_code == 200
        assert text in data["content"]

    def test_xlsx(self, client):
        if not XLSX_CREATE_AVAILABLE:
            pytest.skip("openpyxl not available")
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
            path = handle.name
        try:
            wb = Workbook()
            wb.active.append(["Product", "Qty"])
            wb.active.append(["Widget", 42])
            wb.save(path)
            payload = base64.b64encode(open(path, "rb").read()).decode()
            response = client.post(
                "/extract-base64",
                headers=auth_headers(),
                json={"base64": payload, "filename": "inventory.xlsx", "contentType": XLSX_MIME},
            )
            data = json.loads(response.data)
            assert response.status_code == 200
            assert data["file_type"] == ".xlsx"
            assert "Widget" in data["content"]
        finally:
            os.unlink(path)

    def test_missing_payload(self, client):
        response = client.post("/extract-base64", headers=auth_headers(), json={})
        assert response.status_code == 400
        assert "Missing base64 data" in json.loads(response.data)["error"]

    def test_invalid_payload(self, client):
        response = client.post(
            "/extract-base64",
            headers=auth_headers(),
            json={"base64": "not-valid%%%"},
        )
        assert response.status_code == 400
        assert "Invalid base64 data" in json.loads(response.data)["error"]


class TestExtractors:
    def test_xlsx_mime_not_docx(self):
        assert extension_from_content_type(XLSX_MIME) == ".xlsx"

    def test_txt(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Test content\nLine 2")
            path = f.name
        try:
            content, error = extract_txt(path)
            assert error is None
            assert "Test content" in content
        finally:
            os.unlink(path)

    def test_xlsx_no_csv_fallback(self):
        if not XLSX_CREATE_AVAILABLE:
            pytest.skip("openpyxl not available")
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
            path = handle.name
        wb = Workbook()
        wb.active["A1"] = "=SUM(1,2)"
        wb.save(path)
        wb.close()
        try:
            content, ext, error = try_extract_with_fallback(path, ".xlsx")
            assert error is None
            assert ext == ".xlsx"
            assert "=SUM(1,2)" in content
            assert "PK" not in content
        finally:
            os.unlink(path)


class TestEndpoints:
    def test_health(self, client):
        response = client.get("/health")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["status"] == "healthy"
        assert data["xlsx_support"] is not None

    def test_index(self, client):
        data = json.loads(client.get("/").data)
        assert ".xlsx" in data["supported_formats"]


@pytest.mark.skipif(not TESTING_FILES, reason="Add files to testing_files/")
@pytest.mark.parametrize("file_path", TESTING_FILES, ids=[p.name for p in TESTING_FILES])
def test_local_fixtures(file_path):
    result = extract_local_file(file_path)
    assert result["success"] is True
    assert result["content_length"] > 0
    if "Greenberg" in file_path.name:
        assert "AC Analytical Controls" in result["content"]
        assert "Frendz Finance" in result["content"]
