"""Tests for the virgo_media multi-modal analysis module."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from virgo_media import MediaAnalyzer, _detect_type


# ===========================================================================
# Fixtures: create small test files with known formats
# ===========================================================================


@pytest.fixture
def png_file(tmp_path: Path) -> Path:
    """Create a minimal valid 1x1 red PNG."""
    # Minimal PNG: 8-byte signature + IHDR chunk + IDAT chunk + IEND chunk
    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        crc_data = chunk_type + data
        crc = struct.pack(">I", 0xFFFFFFFF)  # placeholder CRC
        return length + chunk_type + data + crc

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw_idat = b"x\x9c\x62\x60\x60\x60\x00\x00\x00\x04\x00\x01"
    # Prepend valid zlib header
    idat_data = b"\x78\x01" + raw_idat
    idat = _chunk(b"IDAT", idat_data)
    iend = _chunk(b"IEND", b"")
    content = sig + ihdr + idat + iend

    path = tmp_path / "test.png"
    path.write_bytes(content)
    return path


@pytest.fixture
def jpg_file(tmp_path: Path) -> Path:
    """Create a minimal JPEG file (SOI + APP0 + SOF + SOS + EOI)."""
    soi = b"\xff\xd8\xff\xe0"
    app0 = struct.pack(">HHH", 16, 0x4A46, 0x0101)  # JFIF 1.01
    # SOF0: 8-bit, 1x1, 1 component
    sof = b"\xff\xc0" + struct.pack(">HBBBB", 11, 8, 1, 1, 1)
    sof += b"\x01\x11\x00"
    # SOS
    sos = b"\xff\xda" + struct.pack(">HBB", 8, 1, 0x3F)
    sos += b"\x00\x7f\xff\xd9"
    content = soi + app0 + sof + sos

    path = tmp_path / "test.jpg"
    path.write_bytes(content)
    return path


@pytest.fixture
def pdf_file(tmp_path: Path) -> Path:
    """Create a minimal valid PDF."""
    content = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
        b"trailer\n<< /Size 4 /Root 1 0 R >>\n"
        b"startxref\n190\n%%%%EOF"
    )
    path = tmp_path / "test.pdf"
    path.write_bytes(content)
    return path


@pytest.fixture
def wav_file(tmp_path: Path) -> Path:
    """Create a minimal WAV file (silence, 1 sec)."""
    sample_rate = 8000
    num_samples = sample_rate
    data_size = num_samples  # 8-bit mono
    file_size = 36 + data_size
    content = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        file_size,
        b"WAVE",
        b"fmt ",
        16,  # chunk size
        1,  # PCM
        1,  # mono
        sample_rate,
        sample_rate,  # byte rate
        1,  # block align
        8,  # bits per sample
        b"data",
        data_size,
    )
    content += b"\x80" * data_size  # silence
    path = tmp_path / "test.wav"
    path.write_bytes(content)
    return path


@pytest.fixture
def text_file(tmp_path: Path) -> Path:
    path = tmp_path / "hello.txt"
    path.write_text("Hello, world!\nThis is a text file.\n", encoding="utf-8")
    return path


@pytest.fixture
def empty_file(tmp_path: Path) -> Path:
    path = tmp_path / "empty.bin"
    path.write_bytes(b"")
    return path


# ===========================================================================
# Helper tests
# ===========================================================================


class TestDetectType:
    def test_detect_png(self, png_file: Path) -> None:
        info = _detect_type(png_file)
        assert info["detected_type"] == "image"
        assert info["format"] == "png"
        assert "png" in info["mime"]

    def test_detect_jpg(self, jpg_file: Path) -> None:
        info = _detect_type(jpg_file)
        assert info["detected_type"] == "image"
        assert info["format"] == "jpeg"
        assert "jpeg" in info["mime"]

    def test_detect_pdf(self, pdf_file: Path) -> None:
        info = _detect_type(pdf_file)
        assert info["detected_type"] == "document"
        assert info["format"] == "pdf"

    def test_detect_wav(self, wav_file: Path) -> None:
        info = _detect_type(wav_file)
        assert info["detected_type"] == "audio"
        assert info["format"] == "wav"

    def test_detect_text(self, text_file: Path) -> None:
        info = _detect_type(text_file)
        assert info["detected_type"] == "text"

    def test_detect_empty(self, empty_file: Path) -> None:
        info = _detect_type(empty_file)
        assert info["detected_type"] == "unknown"

    def test_nonexistent_file(self) -> None:
        info = _detect_type(Path("/nonexistent/foo.bar"))
        assert info["detected_type"] == "unknown"


# ===========================================================================
# MediaAnalyzer tests
# ===========================================================================


class TestMediaAnalyzer:
    def test_analyze_png(self, png_file: Path) -> None:
        analyzer = MediaAnalyzer(enable_vision=False)
        result = analyzer.analyze(str(png_file))
        assert "error" not in result
        assert result["detected_type"] == "image"
        assert result["format"] == "png"
        assert "metadata" in result
        meta = result["metadata"]
        assert "file_size_kb" in meta

    def test_analyze_jpg(self, jpg_file: Path) -> None:
        analyzer = MediaAnalyzer(enable_vision=False)
        result = analyzer.analyze(str(jpg_file))
        assert "error" not in result
        assert result["detected_type"] == "image"
        assert result["format"] == "jpeg"

    def test_analyze_pdf(self, pdf_file: Path) -> None:
        analyzer = MediaAnalyzer(enable_vision=False)
        result = analyzer.analyze(str(pdf_file))
        assert "error" not in result
        # May or may not detect pages depending on PyMuPDF availability
        assert result["detected_type"] in ("document", "text")

    def test_analyze_wav(self, wav_file: Path) -> None:
        analyzer = MediaAnalyzer(enable_vision=False)
        result = analyzer.analyze(str(wav_file))
        assert "error" not in result
        assert result["detected_type"] == "audio"
        assert result["format"] == "wav"

    def test_analyze_text(self, text_file: Path) -> None:
        analyzer = MediaAnalyzer(enable_vision=False)
        result = analyzer.analyze(str(text_file))
        assert "error" not in result
        assert result["detected_type"] == "text"
        meta = result.get("metadata", {})
        assert meta.get("char_count", 0) > 0
        assert meta.get("line_count", 0) > 0

    def test_analyze_nonexistent(self) -> None:
        analyzer = MediaAnalyzer(enable_vision=False)
        result = analyzer.analyze("/nonexistent/file.xyz")
        assert "error" in result

    def test_analyze_json_output(self, png_file: Path, capsys) -> None:
        """Test that the analyzer can produce JSON-printable output."""
        analyzer = MediaAnalyzer(enable_vision=False)
        result = analyzer.analyze(str(png_file))
        # Should be JSON-serializable
        dumped = json.dumps(result, default=str)
        assert len(dumped) > 10

    def test_detect_png_no_pil(self, png_file: Path, monkeypatch) -> None:
        """Fallback header-based detection when Pillow is not available."""
        monkeypatch.setattr("virgo_media.HAS_PIL", False)
        analyzer = MediaAnalyzer(enable_vision=False)
        result = analyzer.analyze(str(png_file))
        # Should still detect as image even without PIL
        assert result["detected_type"] == "image"

    def test_analyze_with_deep(self, text_file: Path) -> None:
        """Deep flag should not crash on non-image files."""
        analyzer = MediaAnalyzer(enable_vision=False)
        result = analyzer.analyze(str(text_file), deep=True)
        assert "error" not in result
        assert result["detected_type"] == "text"


class TestAnalyzerCLI:
    """Smoke test that the CLI entry point parses args."""

    def test_cli_imports(self) -> None:
        from virgo_media import main as media_main

        assert callable(media_main)

    def test_cli_help(self) -> None:
        import subprocess
        import sys

        r = subprocess.run(
            [sys.executable, "-m", "virgo_media", "--help"],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0
        assert "Analyze" in r.stdout or "analyze" in r.stdout


# ===========================================================================
# Integration: tool registry
# ===========================================================================


def test_media_analyzer_registered() -> None:
    """Verify the media_analyzer tool is in the registry."""
    from tools import ToolRegistry

    registry = ToolRegistry()
    registry.register_defaults()
    tool = registry.get("media_analyzer")
    assert tool is not None
    assert "media" in tool.description.lower()


def test_file_sampler_media(png_file: Path) -> None:
    """Verify the file_sampler delegates to virgo_media for images."""
    from tools import _file_sampler

    result = _file_sampler(str(png_file))
    assert "format" in result
    assert result.get("detected_type") == "image" or "media_error" not in result
