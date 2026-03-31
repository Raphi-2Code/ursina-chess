"""
engine_manager.py – Stockfish download, discovery, and UCI engine wrapper.

Responsibilities
 • Detect whether Stockfish is already present (engine_manifest.json).
 • Download & extract Stockfish from a predefined URL if missing.
 • Allow the user to manually specify the engine path.
 • Provide an async-friendly interface for requesting engine moves/evaluations.
"""

from __future__ import annotations
import os
import sys
import json
import stat
import platform
import tarfile
import zipfile
import shutil
import threading
from typing import Optional, Callable, Tuple

import chess
import chess.engine

from settings import (
    ENGINES_DIR, MANIFEST_PATH, STOCKFISH_URL, STOCKFISH_VERSION,
    PLATFORM_KEY, DEFAULT_ENGINE_DEPTH, DEFAULT_ENGINE_TIME,
    DEFAULT_SKILL_LEVEL,
)


# ─── Manifest helpers ─────────────────────────────────────────────────────────

def _load_manifest() -> dict:
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r") as f:
            return json.load(f)
    return {}


def _save_manifest(data: dict):
    os.makedirs(ENGINES_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(data, f, indent=2)


def find_engine_path() -> Optional[str]:
    """Return the local Stockfish binary path if present and valid."""
    manifest = _load_manifest()
    path = manifest.get("local_path")
    if path and os.path.isfile(path):
        return path
    # Fallback: scan the engines directory for any executable
    for root, _dirs, files in os.walk(ENGINES_DIR):
        for fname in files:
            if "stockfish" in fname.lower():
                full = os.path.join(root, fname)
                if os.access(full, os.X_OK) or platform.system() == "Windows":
                    _save_manifest({
                        "local_path": full,
                        "version": manifest.get("version", "unknown"),
                        "download_status": "found",
                        "platform": PLATFORM_KEY,
                    })
                    return full
    return None


def set_engine_path(path: str) -> bool:
    """Manually set the engine binary path.  Returns True if the file exists."""
    if not os.path.isfile(path):
        return False
    _save_manifest({
        "local_path": path,
        "version": "manual",
        "download_status": "manual",
        "platform": PLATFORM_KEY,
    })
    return True


# ─── Download & extract ───────────────────────────────────────────────────────

def download_stockfish(
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str]:
    """
    Download and extract Stockfish.
    Returns (success: bool, message: str).
    """
    import requests   # deferred import – only needed for download

    os.makedirs(ENGINES_DIR, exist_ok=True)
    url = STOCKFISH_URL

    if progress_callback:
        progress_callback(f"Downloading Stockfish {STOCKFISH_VERSION}…")

    try:
        resp = requests.get(url, stream=True, timeout=120)
        resp.raise_for_status()
    except Exception as e:
        return False, f"Download failed: {e}"

    # Determine file extension from URL
    if url.endswith(".tar"):
        archive_path = os.path.join(ENGINES_DIR, "stockfish.tar")
    elif url.endswith(".zip"):
        archive_path = os.path.join(ENGINES_DIR, "stockfish.zip")
    else:
        archive_path = os.path.join(ENGINES_DIR, "stockfish.tar")

    # Stream to disk
    total = int(resp.headers.get("content-length", 0))
    downloaded = 0
    with open(archive_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            f.write(chunk)
            downloaded += len(chunk)
            if progress_callback and total:
                pct = int(downloaded / total * 100)
                progress_callback(f"Downloading… {pct}%")

    if progress_callback:
        progress_callback("Extracting…")

    # Extract
    try:
        if tarfile.is_tarfile(archive_path):
            with tarfile.open(archive_path) as tf:
                tf.extractall(ENGINES_DIR)
        elif zipfile.is_zipfile(archive_path):
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(ENGINES_DIR)
        else:
            return False, "Unknown archive format."
    except Exception as e:
        return False, f"Extraction failed: {e}"
    finally:
        # Clean up archive
        if os.path.exists(archive_path):
            os.remove(archive_path)

    # Locate the binary inside the extracted tree
    binary_path = _find_extracted_binary()
    if binary_path is None:
        return False, "Could not find Stockfish binary after extraction."

    # Set executable permission on Unix
    if platform.system() != "Windows":
        st = os.stat(binary_path)
        os.chmod(binary_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    _save_manifest({
        "local_path": binary_path,
        "version": STOCKFISH_VERSION,
        "download_status": "ok",
        "platform": PLATFORM_KEY,
    })

    if progress_callback:
        progress_callback("Stockfish ready!")

    return True, binary_path


def _find_extracted_binary() -> Optional[str]:
    """Walk ENGINES_DIR to find a Stockfish executable."""
    for root, _dirs, files in os.walk(ENGINES_DIR):
        for fname in files:
            lower = fname.lower()
            # Skip NNUE and source files
            if lower.endswith(".nnue") or lower.endswith(".py"):
                continue
            if "stockfish" in lower:
                full = os.path.join(root, fname)
                # On Windows, look for .exe
                if platform.system() == "Windows":
                    if lower.endswith(".exe"):
                        return full
                else:
                    # Any file named stockfish without a common non-binary extension
                    if not any(lower.endswith(ext) for ext in (".txt", ".md", ".h", ".cpp", ".c")):
                        return full
    return None


# ─── UCI Engine wrapper ───────────────────────────────────────────────────────

class EngineManager:
    """Manages a python-chess SimpleEngine process for UCI communication."""

    def __init__(self):
        self.engine: Optional[chess.engine.SimpleEngine] = None
        self.skill_level: int = DEFAULT_SKILL_LEVEL
        self.depth: int = DEFAULT_ENGINE_DEPTH
        self.move_time: float = DEFAULT_ENGINE_TIME
        self._thinking = False

    # ── lifecycle ──────────────────────────────────────────────────────────
    def start(self, path: Optional[str] = None) -> bool:
        """Open the UCI engine.  Returns True on success."""
        if self.engine:
            self.quit()
        if path is None:
            path = find_engine_path()
        if path is None:
            return False
        try:
            self.engine = chess.engine.SimpleEngine.popen_uci(path)
            self._apply_options()
            return True
        except Exception as e:
            print(f"[EngineManager] Failed to start engine: {e}")
            self.engine = None
            return False

    def quit(self):
        if self.engine:
            try:
                self.engine.quit()
            except Exception:
                pass
            self.engine = None

    @property
    def is_running(self) -> bool:
        return self.engine is not None

    @property
    def is_thinking(self) -> bool:
        return self._thinking

    # ── configuration ─────────────────────────────────────────────────────
    def set_skill_level(self, level: int):
        self.skill_level = max(0, min(20, level))
        self._apply_options()

    def set_depth(self, depth: int):
        self.depth = max(1, min(30, depth))

    def set_move_time(self, seconds: float):
        self.move_time = max(0.1, seconds)

    def _apply_options(self):
        if self.engine:
            try:
                self.engine.configure({"Skill Level": self.skill_level})
            except Exception:
                pass   # not all engines support Skill Level

    # ── analysis / best move ──────────────────────────────────────────────
    def get_best_move(self, board: chess.Board,
                      callback: Optional[Callable[[chess.Move, Optional[chess.engine.PovScore]], None]] = None):
        """
        Request the best move in a background thread.
        *callback(move, score)* is called when the engine finishes.
        """
        if not self.engine:
            return
        self._thinking = True

        def _run():
            try:
                limit = chess.engine.Limit(
                    depth=self.depth,
                    time=self.move_time,
                )
                result = self.engine.play(board, limit, info=chess.engine.INFO_SCORE)
                move = result.move
                score = result.info.get("score")
                if callback:
                    callback(move, score)
            except Exception as e:
                print(f"[EngineManager] Engine error: {e}")
                if callback:
                    callback(None, None)
            finally:
                self._thinking = False

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def evaluate(self, board: chess.Board,
                 callback: Optional[Callable[[Optional[chess.engine.PovScore], Optional[str]], None]] = None):
        """
        Get a quick evaluation + best-move string in background.
        callback(score, best_move_uci)
        """
        if not self.engine:
            return

        def _run():
            try:
                info = self.engine.analyse(board, chess.engine.Limit(depth=self.depth))
                score = info.get("score")
                pv = info.get("pv")
                best_uci = pv[0].uci() if pv else None
                if callback:
                    callback(score, best_uci)
            except Exception as e:
                print(f"[EngineManager] Evaluation error: {e}")
                if callback:
                    callback(None, None)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
