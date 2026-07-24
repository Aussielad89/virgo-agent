"""
virgo_media — Multi-modal file analysis for the Virgo pipeline.

Handles file-type detection, metadata extraction, and content analysis
for non-text files: images, PDFs, audio, and binary formats.

Backends (all optional — degrade gracefully):
  - Pillow (PIL)  → image metadata + thumbnail info
  - PyMuPDF (fitz) → PDF text extraction
  - mutagen       → audio metadata
All backends are tried at import time; missing ones are just skipped.

Usage:
    from virgo_media import MediaAnalyzer

    analyzer = MediaAnalyzer()
    result = analyzer.analyze("screenshot.png")
    # => {"type": "image", "format": "png", "width": 1920, …}
"""

from __future__ import annotations

import base64
import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from _console import icon

# ── Optional backends ────────────────────────────────────────────────

HAS_PIL = False
try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    pass

HAS_PYMUPDF = False
try:
    import fitz  # PyMuPDF

    HAS_PYMUPDF = True
except ImportError:
    pass

HAS_MUTAGEN = False
try:
    from mutagen import File as MutagenFile

    HAS_MUTAGEN = True
except ImportError:
    pass


# ── Magic-byte signatures ────────────────────────────────────────────

# (magic_bytes, offset, description, media_type, subtype)
_MAGIC: list[tuple[bytes, int, str, str, str]] = [
    (b"\x89PNG\r\n\x1a\n", 0, "PNG image", "image", "png"),
    (b"\xff\xd8\xff", 0, "JPEG image", "image", "jpeg"),
    (b"GIF87a", 0, "GIF image", "image", "gif"),
    (b"GIF89a", 0, "GIF image (anim)", "image", "gif"),
    (b"BM", 0, "BMP image", "image", "bmp"),
    (b"RIFF", 0, "WebP image / RIFF", "image", "webp"),  # second check below
    (b"%PDF", 0, "PDF document", "document", "pdf"),
    (b"PK\x03\x04", 0, "ZIP archive / Office doc", "archive", "zip"),
    (b"Rar!\x1a\x07", 0, "RAR archive", "archive", "rar"),
    (b"\x1f\x8b\x08", 0, "GZIP archive", "archive", "gz"),
    (b"ID3", 0, "MP3 audio (ID3)", "audio", "mp3"),
    (b"\xff\xfb", 0, "MP3 audio", "audio", "mp3"),
    (b"\xff\xf3", 0, "MP3 audio", "audio", "mp3"),
    (b"fLaC", 0, "FLAC audio", "audio", "flac"),
    (b"OggS", 0, "OGG container", "audio", "ogg"),
    (b"RIFF", 0, "WAV audio", "audio", "wav"),  # needs "WAVE" at offset 8
    (b"\x00\x00\x00\x18ftyp", 0, "MP4 video", "video", "mp4"),
    (b"\x00\x00\x00\x1cftyp", 0, "MP4 video", "video", "mp4"),
    (b"\x1aE\xdf\xa3", 0, "MKV / WebM video", "video", "mkv"),
    (b"\x00\x00\x00\x0cJ\xc4", 0, "AVCHD video", "video", "mts"),
    (b"<?xml", 0, "XML / SVG", "text", "xml"),
    (b"{\"", 0, "JSON text", "text", "json"),
    (b"[{", 0, "JSONL text", "text", "jsonl"),
    (b"#!/usr/bin/", 0, "Script", "text", "script"),
]

# Refinements for ambiguous signatures
_WEBP_MAGIC = b"WEBP"
_WAVE_MAGIC = b"WAVE"


def _detect_type(path: Path) -> dict[str, Any]:
    """Detect file type from magic bytes.

    Returns a dict with:
        detected_type  — broad category (image, document, audio, video, archive, text)
        format         — specific format name (png, pdf, mp3, …)
        mime           — guessed MIME type
        magic_desc     — human-readable description
    """
    result: dict[str, Any] = {
        "detected_type": "unknown",
        "format": path.suffix.lower().lstrip(".") or "bin",
        "mime": "application/octet-stream",
        "magic_desc": "Binary data",
    }

    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
    except OSError:
        return result

    if not head:
        return result

    for magic, offset, desc, media_type, subtype in _MAGIC:
        if head[offset : offset + len(magic)] == magic:
            # Refine ambiguous signatures
            if media_type == "image" and subtype == "webp":
                if head[8:12] != _WEBP_MAGIC:
                    continue  # RIFF but not WebP → probably WAV
            if media_type == "audio" and subtype == "wav":
                if head[8:12] != _WAVE_MAGIC:
                    continue  # RIFF but not WAVE
            result["detected_type"] = media_type
            result["format"] = subtype
            result["magic_desc"] = desc
            result["mime"] = {
                "image": f"image/{subtype}",
                "document": "application/pdf",
                "archive": f"application/{subtype}",
                "audio": f"audio/{subtype}",
                "video": f"video/{subtype}",
                "text": "text/plain",
            }.get(media_type, "application/octet-stream")
            return result

    # No magic matched
    # Try to detect as UTF-8 text
    try:
        head.decode("utf-8")
        result["detected_type"] = "text"
        result["format"] = "txt"
        result["mime"] = "text/plain"
        result["magic_desc"] = "UTF-8 text file"
    except (UnicodeDecodeError, UnicodeError):
        pass

    return result


# ── Image analysis ───────────────────────────────────────────────────


def _analyze_image(path: Path) -> dict[str, Any]:
    """Extract image metadata using Pillow if available."""
    result: dict[str, Any] = {"has_pil": HAS_PIL}

    if HAS_PIL:
        try:
            img = Image.open(path)
            result["width"] = img.width
            result["height"] = img.height
            result["aspect_ratio"] = round(img.width / img.height, 4) if img.height else 0
            result["mode"] = img.mode
            result["format_detail"] = img.format or ""
            result["is_animated"] = getattr(img, "is_animated", False)
            result["frames"] = getattr(img, "n_frames", 1)
            # Palette colors (first 8)
            if img.mode == "P" and hasattr(img, "getpalette"):
                pal = img.getpalette()
                if pal:
                    colors = []
                    for i in range(0, min(24, len(pal)), 3):
                        colors.append(f"rgb({pal[i]},{pal[i+1]},{pal[i+2]})")
                    result["palette"] = colors
            img.close()
        except Exception as exc:
            result["pil_error"] = str(exc)
    else:
        # Fallback: read dimensions from PNG/Jpeg headers
        result["width"] = _guess_image_width(path)
        result["height"] = _guess_image_height(path)

    result["file_size_kb"] = round(path.stat().st_size / 1024, 1)
    return result


def _guess_image_width(path: Path) -> int | None:
    """Guess image width from raw headers (no Pillow)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(30)
        if head[:3] == b"\xff\xd8\xff":
            # JPEG — skip to SOF marker
            pos = 2
            while pos < len(head) - 1:
                if head[pos] == 0xFF and head[pos + 1] in (0xC0, 0xC2):
                    return struct.unpack_from(">H", head, pos + 7)[0]
                pos += 1
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack_from(">I", head, 16)[0]
    except Exception:
        pass
    return None


def _guess_image_height(path: Path) -> int | None:
    """Guess image height from raw headers (no Pillow)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(30)
        if head[:3] == b"\xff\xd8\xff":
            pos = 2
            while pos < len(head) - 1:
                if head[pos] == 0xFF and head[pos + 1] in (0xC0, 0xC2):
                    return struct.unpack_from(">H", head, pos + 9)[0]
                pos += 1
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack_from(">I", head, 20)[0]
    except Exception:
        pass
    return None


# ── PDF text extraction ──────────────────────────────────────────────


def _analyze_pdf(path: Path) -> dict[str, Any]:
    """Extract PDF metadata and text using PyMuPDF if available."""
    result: dict[str, Any] = {"has_pymupdf": HAS_PYMUPDF, "pages": 0, "text_length": 0}

    if HAS_PYMUPDF:
        try:
            doc = fitz.open(str(path))
            result["pages"] = len(doc)
            result["title"] = doc.metadata.get("title", "") or ""
            result["author"] = doc.metadata.get("author", "") or ""
            result["subject"] = doc.metadata.get("subject", "") or ""
            result["producer"] = doc.metadata.get("producer", "") or ""
            # Extract text from first N pages
            text_parts: list[str] = []
            for i, page in enumerate(doc):
                if i >= 10:  # limit to first 10 pages
                    break
                text_parts.append(page.get_text())
            full_text = "\n".join(text_parts)
            result["text_length"] = len(full_text)
            result["preview"] = full_text[:2000]
            doc.close()
        except Exception as exc:
            result["error"] = str(exc)
    else:
        # Fallback: try pdftotext if available
        try:
            proc = subprocess.run(
                ["pdftotext", str(path), "-", "-l", "3"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode == 0:
                result["text_length"] = len(proc.stdout)
                result["preview"] = proc.stdout[:2000]
                result["pdftotext"] = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # Count pages approximately from PDF header
            try:
                with open(path, "rb") as fh:
                    raw = fh.read(65536)
                result["pages"] = raw.count(b"/Type /Page") + raw.count(b"/Type/Page")
            except Exception:
                pass

    result["file_size_kb"] = round(path.stat().st_size / 1024, 1)
    return result


# ── Audio metadata ───────────────────────────────────────────────────


def _analyze_audio(path: Path) -> dict[str, Any]:
    """Extract audio metadata using mutagen if available."""
    result: dict[str, Any] = {"has_mutagen": HAS_MUTAGEN}

    if HAS_MUTAGEN:
        try:
            af = MutagenFile(str(path))
            if af is not None:
                result["duration_sec"] = af.info.length if hasattr(af.info, "length") else None
                result["bitrate"] = af.info.bitrate if hasattr(af.info, "bitrate") else None
                result["sample_rate"] = af.info.sample_rate if hasattr(af.info, "sample_rate") else None
                result["channels"] = af.info.channels if hasattr(af.info, "channels") else None
                # Tags
                if af.tags:
                    for tag in ("title", "artist", "album", "date", "genre"):
                        val = af.tags.get(tag)
                        if val:
                            result[tag] = str(val[0]) if isinstance(val, list) else str(val)
        except Exception as exc:
            result["error"] = str(exc)
    else:
        # Basic WAV info from header
        try:
            with open(path, "rb") as fh:
                head = fh.read(44)
            if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
                channels = struct.unpack_from("<H", head, 22)[0]
                sample_rate = struct.unpack_from("<I", head, 24)[0]
                byte_rate = struct.unpack_from("<I", head, 28)[0]
                bits = struct.unpack_from("<H", head, 34)[0]
                data_size = struct.unpack_from("<I", head, 40)[0]
                result["channels"] = channels
                result["sample_rate"] = sample_rate
                result["bits_per_sample"] = bits
                result["duration_sec"] = round(data_size / byte_rate, 2) if byte_rate else None
        except Exception:
            pass

    result["file_size_kb"] = round(path.stat().st_size / 1024, 1)
    return result


# ── LLM-based vision (uses OmniRoute / Ollama) ───────────────────────


def _describe_image_via_llm(
    path: Path,
    prompt: str = "Describe this image in detail. What do you see?",
    base_url: str | None = None,
) -> dict[str, Any]:
    """Send an image to a vision-capable LLM for description.

    Uses the OmniRoute/Ollama-compatible /v1/chat/completions endpoint.
    The image is base64-encoded and sent as a data URL.

    Returns the model's text response, or an error dict on failure.
    """
    url = (base_url or os.environ.get("LLM_BASE_URL", "http://localhost:20128/v1")).rstrip("/") + "/chat/completions"

    # Read and encode image
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        encoded = base64.b64encode(raw).decode("ascii")
        ext = path.suffix.lower().lstrip(".") or "png"
        # Map extension to MIME
        mime_map = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "webp": "image/webp",
            "bmp": "image/bmp",
        }
        mime = mime_map.get(ext, "image/png")
        data_url = f"data:{mime};base64,{encoded}"
    except Exception as exc:
        return {"error": f"Failed to read image: {exc}"}

    payload = json.dumps(
        {
            "model": os.environ.get("MODEL_VISION", "qwen2.5-coder:7b"),
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "max_tokens": 1024,
            "temperature": 0.3,
        }
    ).encode("utf-8")

    import urllib.request as req
    import urllib.error as uerr

    try:
        r = req.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {os.environ.get('LLM_API_KEY', 'no-key')}",
            },
        )
        with req.urlopen(r, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"description": content, "model": body.get("model", ""), "tokens": body.get("usage", {})}
    except uerr.HTTPError as exc:
        return {"error": f"HTTP {exc.code}: {exc.reason}"}
    except Exception as exc:
        return {"error": f"Vision request failed: {exc}"}


# ── Main analyzer ────────────────────────────────────────────────────


class MediaAnalyzer:
    """Analyzes media files and returns structured metadata.

    Usage::

        analyzer = MediaAnalyzer()
        result = analyzer.analyze("screenshot.png")
        # => {"path": ..., "type": "image", "format": "png", "metadata": {...}}
    """

    def __init__(self, enable_vision: bool = True) -> None:
        self.enable_vision = enable_vision

    def analyze(
        self,
        file_path: str,
        *,
        vision_prompt: str | None = None,
        deep: bool = False,
    ) -> dict[str, Any]:
        """Analyze a file and return structured results.

        Parameters
        ----------
        file_path:
            Path to the file to analyze.
        vision_prompt:
            Optional prompt for LLM-based image description.  If omitted,
            images are not sent to the LLM.
        deep:
            If True, attempt heavier analysis (LLM vision for images,
            full OCR for PDFs).  Default False.

        Returns a dict with:
            path, filename, size, type, format, mime, metadata
        """
        path = Path(file_path).resolve()
        if not path.exists():
            return {"error": f"File not found: {file_path}"}

        result: dict[str, Any] = {
            "path": str(path),
            "filename": path.name,
            "size": path.stat().st_size,
            "size_kb": round(path.stat().st_size / 1024, 1),
        }

        # Detect type
        type_info = _detect_type(path)
        result.update(type_info)

        # Specialized analysis
        media_type = type_info.get("detected_type", "unknown")
        fmt = type_info.get("format", "")

        if media_type == "image" and fmt in ("png", "jpeg", "jpg", "gif", "webp", "bmp"):
            result["metadata"] = _analyze_image(path)
            if deep and vision_prompt and self.enable_vision and fmt in ("png", "jpeg", "jpg"):
                result["vision"] = _describe_image_via_llm(path, vision_prompt)

        elif media_type == "document" and fmt == "pdf":
            result["metadata"] = _analyze_pdf(path)

        elif media_type == "audio" and fmt in ("mp3", "flac", "ogg", "wav", "m4a"):
            result["metadata"] = _analyze_audio(path)

        elif media_type == "text":
            # Quick sample for text files
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                result["metadata"] = {
                    "char_count": len(content),
                    "line_count": len(content.splitlines()),
                    "preview": content[:1000],
                }
            except Exception as exc:
                result["metadata"] = {"error": f"Cannot read as text: {exc}"}

        else:
            result["metadata"] = {
                "note": f"No specialized analyzer for {media_type}/{fmt}",
            }

        return result


# ── CLI entry point ──────────────────────────────────────────────────


def main() -> None:
    """CLI entry: ``python virgo_media.py <file> [--vision \"prompt\"] [--deep]``"""
    import argparse

    parser = argparse.ArgumentParser(description="Analyze a media file")
    parser.add_argument("file", help="Path to the file to analyze")
    parser.add_argument("--vision", "-v", help="Prompt for LLM-based image description")
    parser.add_argument("--deep", "-d", action="store_true", help="Enable deep analysis")
    args = parser.parse_args()

    analyzer = MediaAnalyzer()
    result = analyzer.analyze(args.file, vision_prompt=args.vision, deep=args.deep)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
