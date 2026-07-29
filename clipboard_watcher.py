"""Monitor Windows clipboard for content changes."""

import threading
from typing import Callable


_WATCHER: "ClipboardWatcher | None" = None


class ClipboardWatcher:
    def __init__(self) -> None:
        self._running = False
        self._thread: threading.Thread | None = None
        self._last = ""
        self._callback: Callable[[str], None] | None = None

    def start(self, callback: Callable[[str], None]) -> None:
        self._running = True
        self._callback = callback
        self._thread = threading.Thread(target=self._runner, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _runner(self) -> None:
        import time as _time
        while self._running:
            data = self._read()
            if data is not None and data != self._last:
                self._last = data
                if self._callback:
                    self._callback(data)
            _time.sleep(0.5)

    def _read(self) -> str | None:
        try:
            import win32clipboard  # type: ignore
            win32clipboard.OpenClipboard()
            try:
                data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT) or ""
            finally:
                win32clipboard.CloseClipboard()
            return data
        except Exception:
            pass
        try:
            import tkinter as tk  # type: ignore
            root = tk.Tk()
            root.withdraw()
            data = root.clipboard_get()
            root.destroy()
            return data
        except Exception:
            pass
        try:
            import ctypes  # type: ignore
            ctypes.windll.user32.OpenClipboard(0)  # type: ignore
            try:
                data = ctypes.windll.user32.GetClipboardText()  # type: ignore
                return data or ""
            finally:
                ctypes.windll.user32.CloseClipboard()  # type: ignore
        except Exception:
            pass
        return None


def start_watch(callback: Callable[[str], None]) -> None:
    global _WATCHER
    if _WATCHER is None:
        _WATCHER = ClipboardWatcher()
    _WATCHER.start(callback)


def stop_watch() -> None:
    global _WATCHER
    if _WATCHER:
        _WATCHER.stop()
        _WATCHER = None
