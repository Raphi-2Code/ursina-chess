"""
settings.py – Global constants and configuration for the Ursina Chess application.
"""

import os
import platform

# ─── Paths ────────────────────────────────────────────────────────────────────
APP_DIR         = os.path.dirname(os.path.abspath(__file__))
ENGINES_DIR     = os.path.join(APP_DIR, "engines", "stockfish")
MANIFEST_PATH   = os.path.join(ENGINES_DIR, "engine_manifest.json")
PGN_DIR         = os.path.join(APP_DIR, "saved_games")

# ─── Window ───────────────────────────────────────────────────────────────────
WINDOW_TITLE    = "Ursina Chess"
WINDOW_SIZE     = (1920, 1080)
WINDOW_FULLSCREEN = False
WINDOW_BORDERLESS = False

# ─── Render quality ───────────────────────────────────────────────────────────
ANISOTROPIC_DEGREE  = 16
TEXTURE_FILTERING   = "mipmap"
ENABLE_FXAA         = False
ENABLE_VSYNC        = True

# ─── Board rendering ─────────────────────────────────────────────────────────
BOARD_SIZE      = 8
SQUARE_SIZE     = 0.062                       # UI-space size per square
BOARD_ORIGIN_X  = -0.35                       # left edge of the board in UI coords
BOARD_ORIGIN_Y  =  0.28                       # top edge (row 7) of the board

LIGHT_COLOR     = (0.94, 0.85, 0.71, 1.0)    # light squares
DARK_COLOR      = (0.71, 0.53, 0.39, 1.0)    # dark squares
HIGHLIGHT_COLOR = (0.90, 0.90, 0.40, 0.70)   # selected square
LEGAL_COLOR     = (0.50, 0.80, 0.50, 0.55)   # legal-move dots
LAST_MOVE_COLOR = (0.80, 0.80, 0.30, 0.35)   # last move highlight
CHECK_COLOR     = (0.95, 0.30, 0.30, 0.55)   # king in check highlight
PREMOVE_COLOR   = (0.30, 0.70, 0.95, 0.42)   # queued premove highlight

# ─── Unicode piece glyphs  ────────────────────────────────────────────────────
PIECE_UNICODE = {
    # Use the filled chess glyph shapes for both sides and distinguish colour
    # via the rendered text colour in the UI.
    "K": "\u265A", "Q": "\u265B", "R": "\u265C", "B": "\u265D", "N": "\u265E", "P": "\u265F",
    "k": "\u265A", "q": "\u265B", "r": "\u265C", "b": "\u265D", "n": "\u265E", "p": "\u265F",
}

# ─── Engine defaults ──────────────────────────────────────────────────────────
DEFAULT_ENGINE_DEPTH    = 12
DEFAULT_ENGINE_TIME     = 1.0      # seconds per move
DEFAULT_SKILL_LEVEL     = 20       # 0-20

# ─── Stockfish download URLs (Stockfish 17.1 – GitHub releases) ───────────────
STOCKFISH_VERSION = "17.1"
_GH_BASE = "https://github.com/official-stockfish/Stockfish/releases/download/sf_17.1"

def _detect_platform_key():
    """Return the Stockfish asset name fragment for this OS + arch."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows":
        return "windows-x86-64-avx2"
    elif system == "darwin":
        if "arm" in machine or "aarch64" in machine:
            return "macos-m1-apple-silicon"
        return "macos-x86-64-avx2"
    else:   # linux / other
        return "ubuntu-x86-64-avx2"

PLATFORM_KEY = _detect_platform_key()

# Tar archive URL (official releases for 17.1 ship .tar files)
STOCKFISH_URL = f"{_GH_BASE}/stockfish-{PLATFORM_KEY}.tar"

# ─── Networking ───────────────────────────────────────────────────────────────
DEFAULT_HOST    = "0.0.0.0"
DEFAULT_PORT    = 25565

# ─── Time controls  (label → (base_seconds, increment_seconds)) ──────────────
TIME_CONTROLS = {
    "No limit":  (0, 0),
    "10+0":      (600, 0),
    "5+3":       (300, 3),
    "3+2":       (180, 2),
    "1+0":       (60, 0),
}

# ─── Sound (placeholder paths – sounds are optional) ─────────────────────────
SOUND_MOVE      = "move.wav"
SOUND_CAPTURE   = "capture.wav"
SOUND_CHECK     = "check.wav"
SOUND_MATE      = "mate.wav"
