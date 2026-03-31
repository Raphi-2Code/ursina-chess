"""
game_state.py – Wraps python-chess to manage board state, move validation,
game result detection, PGN export, and clock management.
"""

from __future__ import annotations
import chess
import chess.pgn
import time
import io
import os
from pathlib import Path
from typing import Optional, List, Tuple
from settings import TIME_CONTROLS, PGN_DIR

# ─── Game mode enum ───────────────────────────────────────────────────────────
class GameMode:
    LOCAL       = "local"
    VS_ENGINE   = "vs_engine"
    MULTIPLAYER = "multiplayer"


class GameState:
    """
    Central chess game state backed by python-chess.
    Handles board logic, clocks, and PGN.
    """

    def __init__(self):
        self.board: chess.Board = chess.Board()
        self.starting_fen: str = chess.STARTING_FEN
        self.mode: str = GameMode.LOCAL
        self.player_color: chess.Color = chess.WHITE     # human colour in engine mode
        self.flipped: bool = False                       # is the board flipped?

        # Move history for highlighting / PGN
        self.last_move: Optional[chess.Move] = None
        self.move_list: List[str] = []                   # SAN strings
        self._state_history: List[dict] = []
        self._redo_stack: List[chess.Move] = []
        self.premove_move: Optional[chess.Move] = None
        self.premove_color: Optional[chess.Color] = None

        # Clock
        self.time_control_label: str = "No limit"
        self.base_time: float = 0.0
        self.increment: float = 0.0
        self.white_clock: float = 0.0
        self.black_clock: float = 0.0
        self.clock_running: bool = False
        self._last_tick: float = 0.0

        # Metadata
        self.white_name: str = "White"
        self.black_name: str = "Black"
        self.result: Optional[str] = None               # "1-0", "0-1", "1/2-1/2"
        self.resigned_color: Optional[chess.Color] = None

    # ── Setup / reset ─────────────────────────────────────────────────────────
    def new_game(self, mode: str = GameMode.LOCAL,
                 player_color: chess.Color = chess.WHITE,
                 time_control: str = "No limit",
                 fen: Optional[str] = None):
        """Reset to a fresh game."""
        self.board = chess.Board(fen) if fen else chess.Board()
        self.starting_fen = fen or chess.STARTING_FEN
        self.mode = mode
        self.player_color = player_color
        self.flipped = False
        self.last_move = None
        self.move_list = []
        self._state_history = []
        self._redo_stack = []
        self.premove_move = None
        self.premove_color = None
        self.result = None
        self.resigned_color = None
        self.white_name = "White"
        self.black_name = "Black"

        self.time_control_label = time_control
        base, inc = TIME_CONTROLS.get(time_control, (0, 0))
        self.base_time = float(base)
        self.increment = float(inc)
        self.white_clock = self.base_time
        self.black_clock = self.base_time
        self.clock_running = False
        self._last_tick = 0.0
        self._check_result()

    # ── FEN helpers ───────────────────────────────────────────────────────────
    @property
    def fen(self) -> str:
        return self.board.fen()

    def set_fen(self, fen: str, *, clear_premove: bool = True):
        self.board.set_fen(fen)
        self.starting_fen = fen
        self.last_move = None
        self.move_list = []
        self._state_history = []
        self._redo_stack = []
        if clear_premove:
            self.clear_premove()
        self.result = None
        self.resigned_color = None
        self.clock_running = False
        self._last_tick = 0.0
        self._check_result()

    def load_pgn(self, pgn_text: str, mode: str = GameMode.LOCAL,
                 player_color: chess.Color = chess.WHITE,
                 time_control: str = "No limit"):
        """Load the first game from PGN text into the current state."""
        text = pgn_text.strip()
        if not text:
            raise ValueError("Please paste a PGN first.")

        game = chess.pgn.read_game(io.StringIO(text))
        if game is None:
            raise ValueError("No PGN game found.")

        setup_fen = game.headers.get("FEN", "").strip()
        starting_fen = setup_fen or chess.STARTING_FEN

        try:
            chess.Board(starting_fen)
        except ValueError as exc:
            raise ValueError(f"Invalid FEN inside PGN: {exc}") from exc

        moves = list(game.mainline_moves())
        self.new_game(
            mode=mode,
            player_color=player_color,
            time_control=time_control,
            fen=starting_fen if starting_fen != chess.STARTING_FEN else None,
        )

        self.white_name = game.headers.get("White", "").strip() or "White"
        self.black_name = game.headers.get("Black", "").strip() or "Black"

        for move in moves:
            if not self._apply_move(move, clear_redo=True):
                raise ValueError(f"Illegal move in PGN: {move.uci()}")

        header_result = game.headers.get("Result", "").strip()
        if not self.result and header_result in {"1-0", "0-1", "1/2-1/2"}:
            self.result = header_result

        self.clock_running = False
        self._last_tick = 0.0

    @staticmethod
    def list_saved_pgns() -> List[Path]:
        """Return saved PGN files sorted by newest first."""
        saved_dir = Path(PGN_DIR)
        if not saved_dir.exists():
            return []
        return sorted(
            (path for path in saved_dir.glob("*.pgn") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

    # ── Turn helpers ──────────────────────────────────────────────────────────
    @property
    def turn(self) -> chess.Color:
        return self.board.turn

    @property
    def turn_name(self) -> str:
        return "White" if self.board.turn == chess.WHITE else "Black"

    def is_human_turn(self) -> bool:
        """In engine mode, return True only on the human's turn."""
        if self.mode == GameMode.VS_ENGINE:
            return self.board.turn == self.player_color
        return True

    # ── Move interface ────────────────────────────────────────────────────────
    def controlled_colors(self) -> Tuple[chess.Color, ...]:
        """Return the colours the local user may act for."""
        if self.mode == GameMode.LOCAL:
            return (chess.WHITE, chess.BLACK)
        return (self.player_color,)

    def can_control_color(self, color: chess.Color) -> bool:
        return color in self.controlled_colors()

    def can_premove_color(self, color: chess.Color) -> bool:
        return (
            not self.is_game_over()
            and color != self.board.turn
            and self.can_control_color(color)
        )

    def _board_for_move_color(self, color: chess.Color) -> chess.Board | None:
        if not self.can_control_color(color):
            return None
        if color == self.board.turn:
            return self.board
        if not self.can_premove_color(color):
            return None

        board = self.board.copy(stack=False)
        board.turn = color
        return board

    def can_select_square(self, square: chess.Square) -> bool:
        piece = self.board.piece_at(square)
        if piece is None:
            return False
        return self._board_for_move_color(piece.color) is not None

    def legal_moves_for_square(self, square: chess.Square) -> List[chess.Move]:
        """
        Return user-available moves originating from *square*.

        When the selected piece belongs to a controlled colour that is not
        currently on move, this returns premove candidates based on the current
        position with the turn temporarily switched to that colour.
        """
        piece = self.board.piece_at(square)
        if piece is None:
            return []

        board = self._board_for_move_color(piece.color)
        if board is None:
            return []

        return [m for m in board.legal_moves if m.from_square == square]

    def set_premove(self, move: chess.Move, color: chess.Color):
        self.premove_move = move
        self.premove_color = color

    def clear_premove(self):
        self.premove_move = None
        self.premove_color = None

    def try_move(self, move: chess.Move) -> bool:
        """
        Attempt to make *move*.  Returns True on success.
        Handles promotion: if the move is a pawn reaching the last rank and
        no promotion piece is set, it will NOT be applied — the caller should
        ask for the promotion choice first and pass `move` with `.promotion`.
        """
        return self._apply_move(move, clear_redo=True)

    def _apply_move(self, move: chess.Move, *, clear_redo: bool) -> bool:
        """Apply *move* and record state for undo/redo."""
        if move not in self.board.legal_moves:
            return False

        san = self.board.san(move)
        if clear_redo:
            self._redo_stack.clear()
        self._state_history.append({
            "white_clock": self.white_clock,
            "black_clock": self.black_clock,
            "clock_running": self.clock_running,
            "result": self.result,
            "resigned_color": self.resigned_color,
        })
        self.board.push(move)
        self.last_move = move
        self.move_list.append(san)
        self.resigned_color = None

        # Clock: add increment for the side that just moved
        if self.base_time > 0:
            if self.board.turn == chess.BLACK:
                # White just moved
                self.white_clock += self.increment
            else:
                self.black_clock += self.increment
            if not self.clock_running:
                self.clock_running = True
                self._last_tick = time.time()

        self._check_result()
        return True

    def can_undo(self) -> bool:
        return bool(self.board.move_stack) and bool(self._state_history)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def undo_move(self) -> bool:
        """Undo the last half-move and restore clocks/result state."""
        if not self.can_undo():
            return False

        self.clear_premove()
        move = self.board.pop()
        state = self._state_history.pop()
        self._redo_stack.append(move)

        if self.move_list:
            self.move_list.pop()

        self.last_move = self.board.peek() if self.board.move_stack else None
        self.white_clock = state["white_clock"]
        self.black_clock = state["black_clock"]
        self.clock_running = state["clock_running"]
        self.result = state["result"]
        self.resigned_color = state.get("resigned_color")
        self._last_tick = time.time() if self.clock_running else 0.0
        return True

    def redo_move(self) -> bool:
        """Re-apply the most recently undone half-move."""
        if not self.can_redo():
            return False

        self.clear_premove()
        move = self._redo_stack.pop()
        return self._apply_move(move, clear_redo=False)

    def needs_promotion(self, from_sq: chess.Square, to_sq: chess.Square) -> bool:
        """Return True if a legal move from→to would be a pawn promotion."""
        piece = self.board.piece_at(from_sq)
        if piece is None or piece.piece_type != chess.PAWN:
            return False
        rank = chess.square_rank(to_sq)
        reaches_back_rank = (
            (piece.color == chess.WHITE and rank == 7)
            or (piece.color == chess.BLACK and rank == 0)
        )
        if not reaches_back_rank:
            return False

        return any(
            move.from_square == from_sq
            and move.to_square == to_sq
            and move.promotion is not None
            for move in self.legal_moves_for_square(from_sq)
        )

    # ── Clock tick ────────────────────────────────────────────────────────────
    def tick_clock(self):
        """Call once per frame to decrement the active player's clock."""
        if not self.clock_running or self.base_time <= 0 or self.result:
            return
        now = time.time()
        dt = now - self._last_tick
        self._last_tick = now
        if self.board.turn == chess.WHITE:
            self.white_clock = max(0.0, self.white_clock - dt)
            if self.white_clock <= 0:
                self.result = "0-1"
                self.resigned_color = None
                self.clock_running = False
        else:
            self.black_clock = max(0.0, self.black_clock - dt)
            if self.black_clock <= 0:
                self.result = "1-0"
                self.resigned_color = None
                self.clock_running = False

    # ── Result detection ──────────────────────────────────────────────────────
    def _check_result(self):
        b = self.board
        self.resigned_color = None
        if b.is_checkmate():
            self.result = "0-1" if b.turn == chess.WHITE else "1-0"
        elif b.is_stalemate():
            self.result = "1/2-1/2"
        elif b.is_insufficient_material():
            self.result = "1/2-1/2"
        elif b.can_claim_threefold_repetition():
            self.result = "1/2-1/2"
        elif b.can_claim_fifty_moves():
            self.result = "1/2-1/2"

    def is_game_over(self) -> bool:
        return self.result is not None

    def result_reason(self) -> str:
        """Human-readable reason for the result."""
        if not self.result:
            return ""
        b = self.board
        if b.is_checkmate():
            winner = "Black" if b.turn == chess.WHITE else "White"
            return f"Checkmate – {winner} wins"
        if b.is_stalemate():
            return "Stalemate – Draw"
        if b.is_insufficient_material():
            return "Insufficient material – Draw"
        if b.can_claim_threefold_repetition():
            return "Threefold repetition – Draw"
        if b.can_claim_fifty_moves():
            return "50-move rule – Draw"
        if self.result == "1/2-1/2":
            return "Draw by agreement"
        if self.resigned_color is not None:
            resigner = "White" if self.resigned_color == chess.WHITE else "Black"
            winner = "Black" if self.resigned_color == chess.WHITE else "White"
            return f"{resigner} resigns - {winner} wins"
        if self.base_time > 0 and self.white_clock <= 0:
            return "White's time ran out – Black wins"
        if self.base_time > 0 and self.black_clock <= 0:
            return "Black's time ran out – White wins"
        return self.result

    # ── PGN ───────────────────────────────────────────────────────────────────
    def to_pgn(self) -> str:
        """Export the current game as PGN text."""
        game = chess.pgn.Game()
        game.headers["White"] = self.white_name
        game.headers["Black"] = self.black_name
        game.headers["Result"] = self.result or "*"
        if self.starting_fen != chess.STARTING_FEN:
            game.headers["SetUp"] = "1"
            game.headers["FEN"] = self.starting_fen
        node = game
        temp = chess.Board(self.starting_fen)
        for san in self.move_list:
            move = temp.parse_san(san)
            node = node.add_variation(move)
            temp.push(move)
        out = io.StringIO()
        print(game, file=out)
        return out.getvalue()

    def save_pgn(self, filename: Optional[str] = None) -> str:
        """Save the PGN to disk and return the file path."""
        os.makedirs(PGN_DIR, exist_ok=True)
        if filename is None:
            ts = time.strftime("%Y%m%d_%H%M%S")
            filename = f"game_{ts}.pgn"
        path = os.path.join(PGN_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_pgn())
        return path

    # ── Resign / draw ─────────────────────────────────────────────────────────
    def resign(self, color: chess.Color):
        self.clear_premove()
        self.result = "0-1" if color == chess.WHITE else "1-0"
        self.resigned_color = color
        self.clock_running = False

    def accept_draw(self):
        self.clear_premove()
        self.result = "1/2-1/2"
        self.resigned_color = None
        self.clock_running = False

    # ── Format helpers ────────────────────────────────────────────────────────
    @staticmethod
    def format_clock(seconds: float) -> str:
        if seconds <= 0:
            return "0:00"
        m = int(seconds) // 60
        s = int(seconds) % 60
        return f"{m}:{s:02d}"

    @property
    def status_text(self) -> str:
        """One-line game status string for the UI."""
        if self.result:
            return self.result_reason()
        check = " – CHECK!" if self.board.is_check() else ""
        return f"{self.turn_name} to move{check}"
