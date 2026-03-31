"""
board_view.py – Ursina-based chessboard renderer.

Renders an 8×8 board using coloured quads in camera.ui space.
Pieces are shown as Unicode text entities.
Supports click selection, legal-move highlighting, last-move highlighting,
check highlighting, and board flipping.
"""

from __future__ import annotations

import chess
from ursina import (
    Entity, Button, Text, camera, color,
    mouse, destroy, Func, Vec2, Vec3, window,
)

from settings import (
    BOARD_SIZE, SQUARE_SIZE,
    BOARD_ORIGIN_X, BOARD_ORIGIN_Y,
    LIGHT_COLOR, DARK_COLOR,
    HIGHLIGHT_COLOR, LEGAL_COLOR, LAST_MOVE_COLOR, CHECK_COLOR, PREMOVE_COLOR,
    PIECE_UNICODE, WINDOW_SIZE,
)
from game_state import GameState


DEFAULT_ASPECT_RATIO = WINDOW_SIZE[0] / WINDOW_SIZE[1]
DEFAULT_BOARD_CENTER_X = BOARD_ORIGIN_X + ((BOARD_SIZE - 1) * SQUARE_SIZE / 2)
DEFAULT_BOARD_CENTER_Y = BOARD_ORIGIN_Y - ((BOARD_SIZE - 1) * SQUARE_SIZE / 2)
DEFAULT_BOARD_WIDTH_FRACTION = (BOARD_SIZE * SQUARE_SIZE) / DEFAULT_ASPECT_RATIO
MAX_BOARD_HEIGHT = 0.78
PIECE_SCALE_BASE = 1.8


class BoardView:
    """
    Draws the board and pieces and handles square-click interaction.
    """

    def __init__(self, game_state: GameState):
        self.gs = game_state
        self.squares: dict[chess.Square, Entity] = {}    # square → background quad
        self.pieces: dict[chess.Square, Entity] = {}     # square → piece text entity
        self.highlights: list[Entity] = []               # overlay entities for highlights
        self.selected_square: chess.Square | None = None
        self.input_enabled = True
        self.square_size = SQUARE_SIZE
        self.board_origin_x = BOARD_ORIGIN_X
        self.board_origin_y = BOARD_ORIGIN_Y

        # Callback: the caller (main.py) sets this to handle a completed move
        self.on_move: callable = None                    # (chess.Move) -> None
        # Callback: when promotion is needed
        self.on_promotion_needed: callable = None        # (from_sq, to_sq) -> None
        # Callback: when an invalid target click should cancel a queued premove
        self.on_invalid_premove_target: callable = None  # (from_sq, clicked_sq) -> bool

        self._update_layout()
        self._build_board()

    # ── Board construction ────────────────────────────────────────────────────

    def _update_layout(self):
        aspect_ratio = max(float(window.aspect_ratio), 0.1)
        board_width = min(DEFAULT_BOARD_WIDTH_FRACTION * aspect_ratio, MAX_BOARD_HEIGHT)
        self.square_size = board_width / BOARD_SIZE
        board_center_x = (DEFAULT_BOARD_CENTER_X / DEFAULT_ASPECT_RATIO) * aspect_ratio
        self.board_origin_x = board_center_x - ((BOARD_SIZE - 1) * self.square_size / 2)
        self.board_origin_y = DEFAULT_BOARD_CENTER_Y + ((BOARD_SIZE - 1) * self.square_size / 2)

    def _build_board(self):
        """Create the 64 square entities."""
        for sq in chess.SQUARES:
            file = chess.square_file(sq)
            rank = chess.square_rank(sq)
            x, y = self._square_to_ui(file, rank)
            is_light = (file + rank) % 2 == 1
            c = color.rgba(*LIGHT_COLOR) if is_light else color.rgba(*DARK_COLOR)
            btn = Button(
                parent=camera.ui,
                model="quad",
                color=c,
                scale=(self.square_size, self.square_size),
                position=(x, y, 1),
                origin=(0, 0),
                highlight_color=c.tint(0.08),
                pressed_color=c.tint(-0.05),
                text="",
                radius=0,
            )
            btn.square = sq   # stash for click handler
            btn.on_click = Func(self._on_square_click, sq)
            self.squares[sq] = btn

        self.refresh()

    def _square_to_ui(self, file: int, rank: int) -> tuple[float, float]:
        """Convert board file/rank to UI-space (x, y), respecting flip."""
        if self.gs.flipped:
            display_file = 7 - file
            display_rank = 7 - rank
        else:
            display_file = file
            display_rank = rank
        x = self.board_origin_x + display_file * self.square_size
        y = self.board_origin_y - (7 - display_rank) * self.square_size
        return x, y

    # ── Refresh rendering ─────────────────────────────────────────────────────

    def refresh(self, preserve_selection: bool = False):
        """Redraw all pieces from game state and update highlights."""
        selected_square = self.selected_square if preserve_selection else None
        self.selected_square = None
        self._clear_pieces()
        self._clear_highlights()

        board = self.gs.board

        self._add_persistent_highlights()

        # Draw pieces
        for sq in chess.SQUARES:
            piece = board.piece_at(sq)
            if piece is None:
                continue
            sym = piece.symbol()
            glyph = PIECE_UNICODE.get(sym, "?")
            file = chess.square_file(sq)
            rank = chess.square_rank(sq)
            x, y = self._square_to_ui(file, rank)
            t = Text(
                text=glyph,
                parent=camera.ui,
                scale=PIECE_SCALE_BASE * (self.square_size / SQUARE_SIZE),
                position=(x, y, -0.1),
                origin=(0, 0),
                font="DejaVuSans.ttf",
                color=color.white if piece.color == chess.WHITE else color.rgb(0.15, 0.15, 0.15),
            )
            self.pieces[sq] = t

        if selected_square is not None:
            if self.gs.can_select_square(selected_square):
                self.selected_square = selected_square
                self._clear_highlights()
                self._add_persistent_highlights()
                self._add_highlight(selected_square, HIGHLIGHT_COLOR)
                for move in self.gs.legal_moves_for_square(selected_square):
                    self._add_highlight(move.to_square, LEGAL_COLOR)

    # ── Square repositioning (for flip) ───────────────────────────────────────

    def reposition(self, preserve_selection: bool = False):
        """Recalculate UI positions for all squares and redraw pieces."""
        self._update_layout()
        for sq, btn in self.squares.items():
            file = chess.square_file(sq)
            rank = chess.square_rank(sq)
            x, y = self._square_to_ui(file, rank)
            btn.position = (x, y, 1)
            btn.scale = (self.square_size, self.square_size)
        self.refresh(preserve_selection=preserve_selection)

    def set_input_enabled(self, enabled: bool):
        """Enable or disable all square buttons without hiding the board."""
        self.input_enabled = enabled
        for btn in self.squares.values():
            if enabled:
                prev_collision = getattr(btn, "_saved_collision", None)
                prev_ignore_input = getattr(btn, "_saved_ignore_input", None)
                prev_disabled = getattr(btn, "_saved_disabled", None)

                if prev_collision is not None:
                    btn.collision = prev_collision
                    delattr(btn, "_saved_collision")
                if prev_ignore_input is not None:
                    btn.ignore_input = prev_ignore_input
                    delattr(btn, "_saved_ignore_input")
                if prev_disabled is not None:
                    btn.disabled = prev_disabled
                    delattr(btn, "_saved_disabled")
                continue

            if not hasattr(btn, "_saved_collision"):
                btn._saved_collision = btn.collision
            if not hasattr(btn, "_saved_ignore_input"):
                btn._saved_ignore_input = btn.ignore_input
            if not hasattr(btn, "_saved_disabled"):
                btn._saved_disabled = getattr(btn, "disabled", False)

            btn.collision = False
            btn.ignore_input = True
            btn.disabled = True

    # ── Click handling ────────────────────────────────────────────────────────

    def _on_square_click(self, sq: chess.Square):
        """Handle a click on a board square."""
        if not self.input_enabled:
            return

        board = self.gs.board

        if self.gs.is_game_over():
            return

        if self.selected_square is None:
            if self.gs.can_select_square(sq):
                self._select_square(sq)
        else:
            if sq == self.selected_square:
                # Deselect
                self._deselect()
                return

            from_sq = self.selected_square
            legal_targets = [
                move for move in self.gs.legal_moves_for_square(from_sq)
                if move.to_square == sq
            ]

            if legal_targets:
                if any(move.promotion is not None for move in legal_targets):
                    self._deselect()
                    if self.on_promotion_needed:
                        self.on_promotion_needed(from_sq, sq)
                    return

                self._deselect()
                if self.on_move:
                    self.on_move(chess.Move(from_sq, sq))
                return

            if (
                self.gs.premove_move is not None
                and self.gs.premove_move.from_square == from_sq
                and self.on_invalid_premove_target
            ):
                self.on_invalid_premove_target(from_sq, sq)

            if self.gs.can_select_square(sq):
                self._deselect()
                self._select_square(sq)
                return

            self._deselect()

    def _select_square(self, sq: chess.Square):
        self.selected_square = sq
        self._clear_highlights()
        self._add_persistent_highlights()

        # Highlight the selected square
        self._add_highlight(sq, HIGHLIGHT_COLOR)

        # Highlight legal targets
        for m in self.gs.legal_moves_for_square(sq):
            self._add_highlight(m.to_square, LEGAL_COLOR)

    def clear_selection(self):
        """Clear any active piece selection and keep only persistent highlights."""
        self._deselect()

    def _deselect(self):
        self.selected_square = None
        self._clear_highlights()
        self._add_persistent_highlights()

    def _add_persistent_highlights(self):
        """Re-add highlights that should stay visible across piece selection."""
        if self.gs.last_move:
            for sq in (self.gs.last_move.from_square, self.gs.last_move.to_square):
                self._add_highlight(sq, LAST_MOVE_COLOR)

        if self.gs.premove_move:
            for sq in (self.gs.premove_move.from_square, self.gs.premove_move.to_square):
                self._add_highlight(sq, PREMOVE_COLOR)

        if self.gs.board.is_check():
            king_sq = self.gs.board.king(self.gs.board.turn)
            if king_sq is not None:
                self._add_highlight(king_sq, CHECK_COLOR)

    # ── Highlights / overlays ─────────────────────────────────────────────────

    def _add_highlight(self, sq: chess.Square, rgba_tuple):
        file = chess.square_file(sq)
        rank = chess.square_rank(sq)
        x, y = self._square_to_ui(file, rank)
        e = Entity(
            parent=camera.ui,
            model="quad",
            color=color.rgba(*rgba_tuple),
            scale=(self.square_size, self.square_size),
            position=(x, y, -0.05),
            origin=(0, 0),
        )
        self.highlights.append(e)

    def _clear_highlights(self):
        for e in self.highlights:
            destroy(e)
        self.highlights.clear()

    def _clear_pieces(self):
        for e in self.pieces.values():
            destroy(e)
        self.pieces.clear()

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def destroy(self):
        """Remove all entities."""
        self._clear_highlights()
        self._clear_pieces()
        for e in self.squares.values():
            destroy(e)
        self.squares.clear()
