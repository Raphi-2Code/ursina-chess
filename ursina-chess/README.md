# Ursina Chess

A fully-featured desktop chess application built with the **Ursina** game engine, **python-chess** for rules enforcement, and optional **Stockfish** integration.

## Features

- **Three game modes**: Local 2-player, Play vs Stockfish, Online Multiplayer
- **Full chess rules** via `python-chess`: castling, en passant, promotion, check, checkmate, stalemate, threefold repetition, 50-move rule
- **Click-based interaction** with legal-move highlighting, last-move highlighting, and check highlighting
- **Pawn promotion dialog** with piece selection
- **Board flip** support
- **Time controls**: No limit, 10+0, 5+3, 3+2, 1+0
- **Engine integration** (Stockfish via UCI): adjustable skill level, depth, and time per move
- **Auto-download Stockfish** on first launch (detects OS/architecture)
- **Multiplayer** via `ursina.networking` (RPCPeer) — host-authoritative model
- **PGN export** and **FEN copy** to clipboard
- **Resign** and **draw offer** support
- **Move list** and **engine evaluation** display

## Quick Start

### Prerequisites

- Python 3.11 or newer
- pip

### Installation

```bash
cd ursina-chess
pip install -r requirements.txt
```

### Running

```bash
python main.py
```

On first launch in "Play vs Engine" mode, if Stockfish is not found you will be prompted to download it automatically. The binary is stored under `./engines/stockfish/`.

## Project Structure

```
ursina-chess/
├── main.py              # Application entry point and controller
├── game_state.py        # Chess logic wrapper (python-chess)
├── board_view.py        # Ursina board rendering and click handling
├── engine_manager.py    # Stockfish download, UCI engine wrapper
├── network_manager.py   # Multiplayer via ursina.networking RPCPeer
├── ui_menus.py          # All UI panels, dialogs, HUD
├── settings.py          # Global constants and configuration
├── requirements.txt     # Python dependencies
├── README.md            # This file
├── engines/
│   └── stockfish/       # Auto-downloaded Stockfish binary + manifest
└── saved_games/         # PGN files saved here
```

## Game Modes

### Local Game
Two players share the same computer. Click pieces to select, click target squares to move.

### Play vs Engine
Choose White or Black. Stockfish responds automatically after your move. Adjust difficulty in Settings (skill level 0–20, search depth 1–24, time per move 0.5–10s).

### Multiplayer

**Host:**
1. Click "Host Multiplayer"
2. Enter a port (default 25565) and your name
3. Share your IP with the other player

**Join:**
1. Click "Join Multiplayer"
2. Enter the host's IP, port, and your name
3. Click "Join"

The host always plays White. The connection uses TCP via `ursina.networking.RPCPeer`. The host validates all moves server-side.

## Engine Download

On first launch, if Stockfish is not found:
- A dialog offers to download the latest Stockfish release (17.1)
- The correct binary for your OS/CPU is selected automatically
- Stored in `./engines/stockfish/` with an `engine_manifest.json`
- If the download fails, you can manually browse for a Stockfish binary

### Supported platforms
| OS      | Architecture        | Binary variant       |
|---------|--------------------|-----------------------|
| Windows | x86-64             | avx2                  |
| macOS   | Apple Silicon (M1+)| m1-apple-silicon      |
| macOS   | Intel              | x86-64-avx2           |
| Linux   | x86-64             | ubuntu-x86-64-avx2   |

If you have an older CPU without AVX2 support, change `PLATFORM_KEY` in `settings.py` to a compatible variant (e.g., `ubuntu-x86-64-sse41-popcnt`).

## Controls

| Action         | How                              |
|----------------|----------------------------------|
| Select piece   | Click on it                      |
| Move piece     | Click target square              |
| Deselect       | Click selected piece again       |
| Promote pawn   | Dialog appears automatically     |
| Undo move      | Click "Undo" in toolbar          |
| Flip board     | Click "Flip" in toolbar          |
| Copy FEN       | Click "FEN" in toolbar           |
| Save PGN       | Click "PGN" in toolbar           |
| Resign         | Click "Resign" in toolbar        |
| Offer draw     | Click "Draw" in toolbar          |

## Settings

Accessible from the main menu. Configures:
- **Skill Level** (0–20): Stockfish playing strength
- **Search Depth** (1–24): How many half-moves deep the engine searches
- **Move Time** (0.5–10s): Maximum time per engine move

## Networking Protocol (RPC Messages)

| RPC              | Direction       | Payload                                    |
|------------------|-----------------|--------------------------------------------|
| `hello`          | Client → Host   | player name (str)                          |
| `assign_color`   | Host → Client   | color (int), host name (str)               |
| `sync_state`     | Host → Client   | FEN, last move UCI, clocks, status, moves  |
| `request_move`   | Client → Host   | UCI move (str)                             |
| `move_accepted`  | Host → Client   | UCI move (str), SAN (str)                  |
| `move_rejected`  | Host → Client   | reason (str)                               |
| `offer_draw`     | Either → Other  | (no payload)                               |
| `draw_response`  | Either → Other  | accepted (bool)                            |
| `resign_msg`     | Either → Other  | color (int)                                |
| `ping`           | Client → Host   | (keep-alive)                               |

## Known Limitations / TODO

- **Sound effects**: Placeholder paths are defined in `settings.py` but no `.wav` files are bundled. Drop `move.wav`, `capture.wav`, `check.wav`, and `mate.wav` into the project root to enable sounds.
- **File dialog**: The manual engine browse path uses console input. A native file picker (e.g., via `tkinter.filedialog`) could be integrated.
- **Reconnection**: If a multiplayer client disconnects, there is no automatic reconnect — the client must rejoin and the host resends state.
- **Custom time controls**: The UI currently offers preset time controls only. A text-input based custom control could be added.
- **Piece graphics**: Pieces are rendered as Unicode text glyphs. Sprite-based piece images would improve visual quality.
- **Clock sync in multiplayer**: Clocks are synced via `sync_state` but not with sub-second precision. For competitive play, a dedicated clock-sync protocol would be needed.
- **Multiple simultaneous clients**: The host currently tracks one client connection. Spectator mode or multi-client support would require additional connection management.
- **Threefold repetition / 50-move rule**: Detected via `python-chess` `can_claim_*` methods — they auto-draw rather than offering the player a choice to claim.

## License

This project is provided as-is for educational and personal use.
Stockfish is licensed under the GNU General Public License v3.
