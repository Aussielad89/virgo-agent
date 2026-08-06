"""
VibeVoice page — TTS generation from the Virgo Desktop GUI.

Provides text input, speaker selection, model config, and audio playback
for generating speech directly from the desktop app.
"""
from __future__ import annotations

import sys
import os
import threading
from pathlib import Path
from typing import Any

from .base import PageWidget

HERE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(HERE))

try:
    from PyQt6.QtCore import Qt, QUrl, pyqtSignal, pyqtSlot, QTimer
    from PyQt6.QtGui import QFont, QTextCursor
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PyQt6.QtWidgets import (
        QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
        QPlainTextEdit, QProgressBar, QPushButton, QSlider,
        QSpinBox, QVBoxLayout, QGroupBox, QCheckBox,
    )
    _HAS_QT = True
except ImportError:
    _HAS_QT = False

try:
    from virgo_vibevoice import (
        VibeVoiceTTS, TTSConfig, list_speakers, get_voice_path,
    )
    _HAS_VIBEVOICE = True
except ImportError:
    _HAS_VIBEVOICE = False


class VibeVoicePage(PageWidget):
    """VibeVoice TTS page — generate speech from text."""

    # Signals for thread-safe GUI updates
    _generation_done = pyqtSignal(object)
    _generation_error = pyqtSignal(str)
    _progress_update = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__(
            "VibeVoice TTS",
            "Generate expressive multi-speaker speech from text using VibeVoice",
        )

        self._tts: Any = None
        self._audio_player: Any = None
        self._audio_output: Any = None
        self._last_output_path: str = ""

        # ── Status banner ───────────────────────────────────────────
        if not _HAS_VIBEVOICE:
            banner = QLabel("⚠ VibeVoice not installed — run: cd VibeVoice && pip install -e .")
            banner.setStyleSheet("color: #ffc53d; font-weight: bold; padding: 8px; background: #2a2200; border-radius: 4px;")
            self.content.addWidget(banner)

        # ── Model config row ────────────────────────────────────────
        cfg_row = QHBoxLayout()

        cfg_row.addWidget(QLabel("Model:"))
        self._model_combo = QComboBox()
        self._model_combo.addItems(["1.5B", "7B", "0.5B"])
        self._model_combo.setMinimumWidth(80)
        cfg_row.addWidget(self._model_combo)

        cfg_row.addWidget(QLabel("Speaker:"))
        self._speaker_combo = QComboBox()
        if _HAS_VIBEVOICE:
            self._speaker_combo.addItems(list_speakers())
        else:
            self._speaker_combo.addItems(["Alice", "Frank", "Maya", "Carter"])
        self._speaker_combo.setMinimumWidth(120)
        cfg_row.addWidget(self._speaker_combo)

        cfg_row.addWidget(QLabel("Device:"))
        self._device_combo = QComboBox()
        self._device_combo.addItems(["auto", "cpu", "cuda", "mps"])
        self._device_combo.setMinimumWidth(80)
        cfg_row.addWidget(self._device_combo)

        cfg_row.addStretch()

        # Voice cloning toggle
        self._clone_check = QCheckBox("Voice Cloning")
        self._clone_check.setChecked(True)
        cfg_row.addWidget(self._clone_check)

        self.content.addLayout(cfg_row)

        # ── Multi-speaker row ───────────────────────────────────────
        ms_row = QHBoxLayout()
        ms_row.addWidget(QLabel("Speakers (multi):"))
        self._multi_speakers = QLineEdit()
        self._multi_speakers.setPlaceholderText("e.g. Alice Frank — comma-separated, leave empty for single speaker")
        ms_row.addWidget(self._multi_speakers, 1)
        self.content.addLayout(ms_row)

        # ── Text input ──────────────────────────────────────────────
        self._text_input = QPlainTextEdit()
        self._text_input.setPlaceholderText(
            "Enter text to synthesize...\n\n"
            "Multi-speaker format:\n"
            "  Alice: Hello there!\n"
            "  Frank: Hi Alice, how are you?"
        )
        self._text_input.setMinimumHeight(120)
        self._text_input.setMaximumHeight(300)
        self.content.addWidget(self._text_input, 1)

        # ── Action buttons ──────────────────────────────────────────
        btn_row = QHBoxLayout()

        self._load_btn = QPushButton("Load Model")
        self._load_btn.setStyleSheet("background: #252545; color: #e0e0ff; padding: 8px 16px; border-radius: 4px; border: 1px solid #353560;")
        self._load_btn.clicked.connect(self._on_load_model)
        btn_row.addWidget(self._load_btn)

        self._generate_btn = QPushButton("Generate Speech")
        self._generate_btn.setStyleSheet("background: #7c6aff; color: white; padding: 8px 16px; border-radius: 4px; font-weight: bold;")
        self._generate_btn.clicked.connect(self._on_generate)
        btn_row.addWidget(self._generate_btn)

        self._file_btn = QPushButton("Load Text File")
        self._file_btn.setStyleSheet("background: #252545; color: #e0e0ff; padding: 8px 16px; border-radius: 4px; border: 1px solid #353560;")
        self._file_btn.clicked.connect(self._on_load_file)
        btn_row.addWidget(self._file_btn)

        btn_row.addStretch()

        self._play_btn = QPushButton("▶ Play")
        self._play_btn.setStyleSheet("background: #00e5a0; color: #0a0a14; padding: 8px 16px; border-radius: 4px; font-weight: bold;")
        self._play_btn.clicked.connect(self._on_play)
        self._play_btn.setEnabled(False)
        btn_row.addWidget(self._play_btn)

        self._stop_btn = QPushButton("■ Stop")
        self._stop_btn.setStyleSheet("background: #ff5577; color: white; padding: 8px 16px; border-radius: 4px;")
        self._stop_btn.clicked.connect(self._on_stop)
        self._stop_btn.setEnabled(False)
        btn_row.addWidget(self._stop_btn)

        self.content.addLayout(btn_row)

        # ── Progress / status ───────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.setVisible(False)
        self._progress.setMaximumHeight(6)
        self.content.addWidget(self._progress)

        self._status_label = QLabel("Ready — load a model and enter text")
        self._status_label.setStyleSheet("color: #8888bb; font-size: 12px; padding: 4px 0;")
        self.content.addWidget(self._status_label)

        # ── Connect signals ─────────────────────────────────────────
        self._generation_done.connect(self._on_generation_done)
        self._generation_error.connect(self._on_generation_error)

        # ── Initialize audio player ─────────────────────────────────
        self._init_player()

    def _init_player(self) -> None:
        """Initialize Qt multimedia player for audio playback."""
        try:
            self._audio_output = QAudioOutput()
            self._audio_output.setVolume(1.0)
            self._audio_player = QMediaPlayer()
            self._audio_player.setAudioOutput(self._audio_output)
        except Exception:
            self._audio_player = None

    def on_activate(self) -> None:
        pass

    # ── Slots ───────────────────────────────────────────────────────

    def _on_load_model(self) -> None:
        """Load the VibeVoice model in a background thread."""
        if _HAS_VIBEVOICE and self._tts and self._tts.is_loaded:
            self._status_label.setText("Model already loaded")
            return

        self._load_btn.setEnabled(False)
        self._load_btn.setText("Loading...")
        self._progress.setVisible(True)
        self._status_label.setText("Loading model... this may take a minute")

        def _load():
            try:
                config = TTSConfig(
                    model_size=self._model_combo.currentText(),
                    device=self._device_combo.currentText(),
                )
                tts = VibeVoiceTTS(config)
                tts.load()
                self._tts = tts
                QTimer.singleShot(0, self._on_model_loaded)
            except Exception as exc:
                QTimer.singleShot(0, lambda: self._on_generation_error(str(exc)))

        threading.Thread(target=_load, daemon=True).start()

    def _on_model_loaded(self) -> None:
        """Called when model finishes loading."""
        self._load_btn.setEnabled(True)
        self._load_btn.setText("Load Model")
        self._progress.setVisible(False)
        self._status_label.setText(
            f"Model loaded: {self._model_combo.currentText()} on {self._device_combo.currentText()}"
        )

    def _on_generate(self) -> None:
        """Generate speech from the text input."""
        text = self._text_input.toPlainText().strip()
        if not text:
            self._status_label.setText("⚠ No text to synthesize")
            return

        if not _HAS_VIBEVOICE:
            self._status_label.setText("⚠ VibeVoice not installed")
            return

        if not self._tts or not self._tts.is_loaded:
            self._on_load_model()
            # Queue generation after model loads
            QTimer.singleShot(500, self._on_generate)
            return

        self._generate_btn.setEnabled(False)
        self._generate_btn.setText("Generating...")
        self._progress.setVisible(True)
        self._status_label.setText("Generating speech...")

        speaker = self._speaker_combo.currentText()
        multi = self._multi_speakers.text().strip()
        speakers = [s.strip() for s in multi.split(",") if s.strip()] if multi else None

        def _generate():
            try:
                output = self._tts.speak(
                    text,
                    speaker=speaker,
                    speakers=speakers,
                )
                path = self._tts.save(output)
                self._last_output_path = path
                QTimer.singleShot(0, lambda: self._on_generation_done(output))
            except Exception as exc:
                QTimer.singleShot(0, lambda: self._on_generation_error(str(exc)))

        threading.Thread(target=_generate, daemon=True).start()

    def _on_generation_done(self, output: Any) -> None:
        """Called when generation completes."""
        self._generate_btn.setEnabled(True)
        self._generate_btn.setText("Generate Speech")
        self._progress.setVisible(False)
        self._play_btn.setEnabled(True)
        self._stop_btn.setEnabled(True)
        self._status_label.setText(
            f"Generated: {output.duration:.1f}s audio in {output.generation_time:.1f}s | "
            f"Speaker: {output.speaker}"
        )

    def _on_generation_error(self, error: str) -> None:
        """Called when generation fails."""
        self._generate_btn.setEnabled(True)
        self._generate_btn.setText("Generate Speech")
        self._load_btn.setEnabled(True)
        self._load_btn.setText("Load Model")
        self._progress.setVisible(False)
        self._status_label.setText(f"❌ Error: {error[:120]}")

    def _on_load_file(self) -> None:
        """Load a text file into the input."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Text File", "",
            "Text Files (*.txt);;All Files (*)",
        )
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._text_input.setPlainText(f.read())
                self._status_label.setText(f"Loaded: {os.path.basename(path)}")
            except Exception as exc:
                self._status_label.setText(f"Failed to load: {exc}")

    def _on_play(self) -> None:
        """Play the generated audio."""
        if not self._last_output_path or not self._audio_player:
            return
        self._audio_player.setSource(QUrl.fromLocalFile(self._last_output_path))
        self._audio_player.play()

    def _on_stop(self) -> None:
        """Stop audio playback."""
        if self._audio_player:
            self._audio_player.stop()
