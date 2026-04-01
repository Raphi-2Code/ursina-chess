"""
main.py – Entry point for the Ursina Chess application.

Wires together game_state, board_view, engine_manager, network_manager,
and ui_menus into a coherent game loop.
"""

from __future__ import annotations

import sys
import os
import threading
import chess
import pyperclip

from settings import (
    ENABLE_FXAA,
    ENABLE_VSYNC,
    TEXTURE_FILTERING,
    WINDOW_BORDERLESS,
    WINDOW_FULLSCREEN,
    WINDOW_SIZE,
    WINDOW_TITLE,
)

from ursina import Ursina, Texture, application, camera, color, Entity, Text, window

try:
    from ursina.shaders import fxaa_shader
except ImportError:
    fxaa_shader = None

# ── Project modules ───────────────────────────────────────────────────────────
from game_state import GameState, GameMode
from board_view import BoardView
from engine_manager import EngineManager, find_engine_path, download_stockfish, set_engine_path
from network_manager import NetworkManager
from ui_menus import (
    MainMenu, SettingsPanel, ColorChooser, TimeControlChooser,
    PromotionDialog, JoinDialog, HostDialog, TextImportDialog, FenEditorDialog, SavedGamesDialog,
    EngineDownloadDialog, GameHUD, ResultBanner, ConfirmBanner,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  Application controller
# ═══════════════════════════════════════════════════════════════════════════════

class ChessApp:
    """Top-level controller managing screens and game flow."""

    def __init__(self):
        # Core objects
        self.gs = GameState()
        self.engine = EngineManager()
        self.net = NetworkManager()

        # UI layers (created lazily)
        self.board_view: BoardView | None = None
        self.main_menu: MainMenu | None = None
        self.hud: GameHUD | None = None
        self.settings_panel: SettingsPanel | None = None
        self.result_banner: ResultBanner | ConfirmBanner | None = None
        self._fen_editor_dialog: FenEditorDialog | None = None

        # Pending promotion info
        self._promo_from: int | None = None
        self._promo_to: int | None = None
        self._promotion_dialog: PromotionDialog | None = None

        # Engine result to apply on main thread
        self._pending_engine_move: chess.Move | None = None
        self._pending_engine_score = None
        self._pending_engine_request_id: int | None = None
        self._engine_request_serial = 0
        self._deferred_engine_request = False

        # Download progress string (set from bg thread)
        self._download_progress: str | None = None
        self._download_dialog: EngineDownloadDialog | None = None
        self._download_result_handled = False

        # Flag: show result banner once
        self._result_shown = False
        self._banner_kind: str | None = None
        self._restore_result_banner_after_modal = False
        self._mp_takeback_request_pending = False
        self._window_size = self._get_window_size()
        self._restart_state: dict | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        """Called once after Ursina() init."""
        self._show_main_menu()

    def update(self):
        """Called every frame by Ursina."""
        self._handle_window_resize()

        # Network tick
        self.net.update()

        # Clock tick
        self.gs.tick_clock()

        # Apply engine move queued from bg thread
        if self._pending_engine_move is not None:
            move = self._pending_engine_move
            score = self._pending_engine_score
            request_id = self._pending_engine_request_id
            self._pending_engine_move = None
            self._pending_engine_score = None
            self._pending_engine_request_id = None

            if request_id == self._engine_request_serial:
                self._apply_move(move)
                # Update eval display
                if score and self.hud:
                    try:
                        cp = score.white().score(mate_score=10000)
                        self.hud.update_eval(f"Eval: {cp/100:+.2f}")
                    except Exception:
                        self.hud.update_eval("")

        # Download progress
        if self._download_progress is not None:
            progress = self._download_progress
            if self._download_dialog:
                self._download_dialog.set_progress(progress)

            if not self._download_result_handled:
                progress_lower = progress.lower()
                if "ready" in progress_lower:
                    self._download_result_handled = True
                    self._download_progress = None
                    if self._download_dialog:
                        self._download_dialog.destroy_panel()
                        self._download_dialog = None
                    self._engine_ready_choose_color()
                elif "failed" in progress_lower:
                    self._download_result_handled = True
                    self._download_progress = None

        # HUD updates
        if self.hud:
            white_label, black_label = self._hud_side_labels()
            self.hud.update_status(self.gs.status_text)
            if self.gs.base_time > 0:
                self.hud.update_clocks(
                    self.gs.format_clock(self.gs.white_clock),
                    self.gs.format_clock(self.gs.black_clock),
                    white_label=white_label,
                    black_label=black_label,
                )
            else:
                self.hud.update_clocks(
                    "--:--",
                    "--:--",
                    white_label=white_label,
                    black_label=black_label,
                )
            self.hud.update_move_list(self.gs.move_list)
            self.hud.tick()

        # Result detection
        if self.gs.is_game_over() and not self._result_shown:
            self._result_shown = True
            self.gs.clock_running = False
            self._clear_board_selection()
            self._show_result_banner(
                self.gs.result_reason(),
                on_dismiss=self._dismiss_result,
            )

        if (
            self._deferred_engine_request
            and self.gs.mode == GameMode.VS_ENGINE
            and not self.gs.is_game_over()
            and not self.gs.is_human_turn()
            and not self.engine.is_thinking
        ):
            self._deferred_engine_request = False
            self._request_engine_move()

    # ── Main menu ─────────────────────────────────────────────────────────────

    def _show_main_menu(self):
        self._teardown_game()
        self._restart_state = None
        self.main_menu = MainMenu({
            "local":           self._on_local,
            "start_from_fen":  self._on_start_from_fen,
            "start_from_pgn":  self._on_start_from_pgn,
            "open_saved_pgn":  self._on_open_saved_pgn,
            "vs_engine":       self._on_vs_engine,
            "host":            self._on_host_mp,
            "join":            self._on_join_mp,
            "settings":        self._on_settings,
            "exit":            self._on_exit,
        })

    def _hide_main_menu(self):
        if self.main_menu:
            self.main_menu.destroy()
            self.main_menu = None

    # ── Local game ────────────────────────────────────────────────────────────

    def _on_local(self):
        self._hide_main_menu()
        TimeControlChooser(
            on_choose=self._start_local_with_tc,
            on_back=self._show_main_menu,
        )

    def _start_local_with_tc(self, tc_label: str):
        self.gs.new_game(mode=GameMode.LOCAL, time_control=tc_label)
        self._restart_state = {"kind": "local", "time_control": tc_label}
        self._setup_board_and_hud()

    def _on_start_from_fen(self):
        self._hide_main_menu()
        self._show_fen_editor(
            title="FEN Editor",
            help_text="Build a position by dragging pieces, or paste a FEN to load it. Starting creates a local game from that position without a clock.",
            default_value=chess.STARTING_FEN,
            submit_label="Start",
            on_back=self._show_main_menu,
        )

    def _try_start_from_fen(self, fen_text: str) -> str | None:
        fen = fen_text.strip()
        if not fen:
            return "Please paste a FEN first."

        try:
            self._start_from_fen_game(fen)
        except ValueError as exc:
            return f"Invalid FEN: {exc}"

        return None

    def _start_from_fen_game(self, fen: str):
        self._teardown_game()
        self.gs.new_game(mode=GameMode.LOCAL, time_control="No limit", fen=fen)
        self._restart_state = {"kind": "fen", "fen": fen}
        self._setup_board_and_hud()
        self._result_shown = self.gs.is_game_over()

    def _on_start_from_pgn(self):
        self._hide_main_menu()
        TextImportDialog(
            title="Start From PGN",
            help_text="Paste a PGN. The move list and final position will be loaded for local review or continuation.",
            on_submit=self._try_start_from_pgn,
            on_back=self._show_main_menu,
            submit_label="Load",
            max_lines=14,
            character_limit=20000,
            panel_scale=(0.90, 0.74),
            input_scale=(0.78, 0.36),
            input_offset_y=-0.06,
        )

    def _try_start_from_pgn(self, pgn_text: str) -> str | None:
        text = pgn_text.strip()
        if not text:
            return "Please paste a PGN first."

        try:
            self._start_from_pgn_game(text)
        except ValueError as exc:
            return str(exc)

        return None

    def _start_from_pgn_game(self, pgn_text: str):
        self.gs.load_pgn(pgn_text, mode=GameMode.LOCAL, time_control="No limit")
        self._restart_state = {"kind": "pgn", "pgn_text": pgn_text}
        self._setup_board_and_hud()
        self._result_shown = self.gs.is_game_over()

    def _on_open_saved_pgn(self):
        self._hide_main_menu()
        SavedGamesDialog(
            files=GameState.list_saved_pgns(),
            on_open=self._try_open_saved_pgn,
            on_back=self._show_main_menu,
        )

    def _try_open_saved_pgn(self, path: str) -> str | None:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                pgn_text = handle.read()
            self._start_from_pgn_game(pgn_text)
        except OSError as exc:
            return f"Could not open file: {exc}"
        except ValueError as exc:
            return str(exc)

        return None

    # ── Engine game ───────────────────────────────────────────────────────────

    def _on_vs_engine(self):
        self._hide_main_menu()
        # Check engine availability
        path = find_engine_path()
        if path:
            self._engine_ready_choose_color()
        else:
            self._show_download_dialog()

    def _engine_ready_choose_color(self):
        ColorChooser(
            on_choose=self._start_engine_with_color,
            on_back=self._show_main_menu,
        )

    def _start_engine_with_color(self, chosen_color: chess.Color):
        TimeControlChooser(
            on_choose=lambda tc: self._start_engine_game(chosen_color, tc),
            on_back=self._engine_ready_choose_color,
        )

    def _start_engine_game(self, chosen_color: chess.Color, tc_label: str):
        self.gs.new_game(mode=GameMode.VS_ENGINE, player_color=chosen_color,
                         time_control=tc_label)
        self._restart_state = {
            "kind": "engine",
            "player_color": chosen_color,
            "time_control": tc_label,
        }
        self.gs.white_name = "You" if chosen_color == chess.WHITE else "Stockfish"
        self.gs.black_name = "You" if chosen_color == chess.BLACK else "Stockfish"

        if not self.engine.is_running:
            self.engine.start()

        if chosen_color == chess.BLACK:
            self.gs.flipped = True

        self._setup_board_and_hud()

        # If engine plays white, request move immediately
        if not self.gs.is_human_turn():
            self._request_engine_move()

    # ── Engine download ───────────────────────────────────────────────────────

    def _show_download_dialog(self):
        self._download_progress = None
        self._download_result_handled = False
        self._download_dialog = EngineDownloadDialog(
            on_download=self._do_download,
            on_browse=self._do_browse_engine,
            on_skip=self._engine_skip,
        )

    def _do_download(self):
        self._download_result_handled = False

        def _bg():
            ok, msg = download_stockfish(progress_callback=self._set_download_progress)
            if not ok:
                self._set_download_progress(f"Failed: {msg}")

        threading.Thread(target=_bg, daemon=True).start()

    def _set_download_progress(self, msg: str):
        self._download_progress = msg

    def _do_browse_engine(self):
        """Fallback: let user type a path (simplified)."""
        # For a real file dialog you'd use tkinter.filedialog; here we accept
        # console input so as not to pull in tkinter.
        print("[Info] Enter the Stockfish binary path in the console:")
        path = input("Path: ").strip()
        if set_engine_path(path):
            self._engine_ready_choose_color()
        else:
            print("[Error] Invalid path. Returning to menu.")
            self._show_main_menu()

    def _engine_skip(self):
        """User chose to skip engine download – go back to menu."""
        self._show_main_menu()

    # ── Multiplayer ───────────────────────────────────────────────────────────

    def _on_host_mp(self):
        self._hide_main_menu()
        HostDialog(on_host=self._start_hosting, on_cancel=self._show_main_menu)

    def _start_hosting(self, port: int, name: str):
        self.gs.new_game(mode=GameMode.MULTIPLAYER, time_control="No limit")
        self._restart_state = None
        self._mp_takeback_request_pending = False
        self.gs.white_name = name
        self.gs.player_color = chess.WHITE       # host always plays White

        # Wire callbacks
        self.net.on_color_assigned = self._mp_host_color_assigned
        self.net.on_move_accepted = self._mp_host_move_accepted
        self.net.on_takeback_offered = self._mp_takeback_offered
        self.net.on_takeback_response = self._mp_takeback_response
        self.net.on_draw_offered = self._mp_draw_offered
        self.net.on_draw_response = self._mp_draw_response
        self.net.on_opponent_resigned = self._mp_opponent_resigned
        self.net.on_disconnected = self._mp_disconnected
        self.net.host_board = self.gs.board
        self.net.host(port=port, player_name=name)

        self._setup_board_and_hud()
        if self.hud:
            self.hud.update_status("Waiting for opponent…")

    def _on_join_mp(self):
        self._hide_main_menu()
        JoinDialog(on_join=self._do_join, on_cancel=self._show_main_menu)

    def _do_join(self, ip: str, port: int, name: str):
        self.gs.new_game(mode=GameMode.MULTIPLAYER, time_control="No limit")
        self._restart_state = None
        self._mp_takeback_request_pending = False
        self.net.on_color_assigned = self._mp_client_color_assigned
        self.net.on_state_synced = self._mp_state_synced
        self.net.on_move_accepted = self._mp_client_move_accepted
        self.net.on_move_rejected = self._mp_move_rejected
        self.net.on_takeback_offered = self._mp_takeback_offered
        self.net.on_takeback_response = self._mp_takeback_response
        self.net.on_draw_offered = self._mp_draw_offered
        self.net.on_draw_response = self._mp_draw_response
        self.net.on_opponent_resigned = self._mp_opponent_resigned
        self.net.on_disconnected = self._mp_disconnected
        self.net.join(ip=ip, port=port, player_name=name)

        self._setup_board_and_hud()
        if self.hud:
            self.hud.update_status("Connecting…")

    # Multiplayer callbacks ────────────────────────────────────────────────────

    def _mp_host_color_assigned(self, my_color, opponent_name):
        """Host learned opponent's name."""
        self.gs.black_name = opponent_name
        # Send initial state sync
        self._mp_sync_to_client()
        if self.hud:
            self.hud.update_status(self.gs.status_text)

    def _mp_client_color_assigned(self, my_color, host_name):
        """Client received colour assignment."""
        self.gs.player_color = my_color
        self.net.my_color = my_color
        self.gs.white_name = host_name if my_color == chess.BLACK else self.net.player_name
        self.gs.black_name = self.net.player_name if my_color == chess.BLACK else host_name
        if my_color == chess.BLACK:
            self.gs.flipped = True
            if self.board_view:
                self.board_view.reposition()
        if self.hud:
            if my_color == chess.BLACK:
                self.hud.update_status("Connected as Black - waiting for White")
            else:
                self.hud.update_status("Connected as White - your move")

    def _mp_host_move_accepted(self, uci: str, san: str):
        """Host: a client move was validated and applied on host_board.
           Also apply it in the GameState so the view updates."""
        move = chess.Move.from_uci(uci)
        self.gs.last_move = move
        self.gs.move_list.append(san)
        self.gs._check_result()
        if self._try_execute_premove():
            return

        # Board already pushed in network_manager (host_board IS gs.board)
        if self.board_view:
            self.board_view.refresh()
        self._mp_sync_to_client()

    def _mp_client_move_accepted(self, uci: str, san: str):
        """Client: host accepted our (or their) move – apply to local board."""
        move = chess.Move.from_uci(uci)
        move_applied = False
        if move in self.gs.board.legal_moves:
            move_applied = self.gs.try_move(move)
        if self.board_view:
            self.board_view.refresh()
        if move_applied:
            self._try_execute_premove()

    def _mp_move_rejected(self, reason: str):
        print(f"[Net] Move rejected: {reason}")

    def _mp_state_synced(self, fen, last_uci, w_clock, b_clock, status, move_list_csv):
        """Client received full state from host."""
        self.gs.set_fen(fen, clear_premove=False)
        if last_uci:
            try:
                self.gs.last_move = chess.Move.from_uci(last_uci)
            except Exception:
                self.gs.last_move = None
        self.gs.white_clock = w_clock
        self.gs.black_clock = b_clock
        if move_list_csv:
            self.gs.move_list = move_list_csv.split(",")
        else:
            self.gs.move_list = []
        if self.board_view:
            self.board_view.refresh()
        self._try_execute_premove()

    def _mp_sync_to_client(self):
        """Host pushes current state to the client."""
        last_uci = self.gs.last_move.uci() if self.gs.last_move else ""
        move_csv = ",".join(self.gs.move_list)
        self.net.send_state_sync(
            self.gs.fen, last_uci,
            self.gs.white_clock, self.gs.black_clock,
            self.gs.status_text, move_csv,
        )

    def _mp_draw_offered(self):
        print("[Net] Draw offered by opponent")
        self._show_confirm_banner(
            "Opponent offers a draw.",
            on_confirm=self._accept_mp_draw,
            on_cancel=self._decline_mp_draw,
            confirm_text="Accept",
            cancel_text="Decline",
        )

    def _accept_mp_draw(self):
        self._dismiss_confirm_banner()
        self._clear_board_selection()
        self.gs.accept_draw()
        self.net.send_draw_response(True)
        self._result_shown = False  # let normal result flow handle it

    def _decline_mp_draw(self):
        self.net.send_draw_response(False)
        self._dismiss_confirm_banner(restore_result=True)
        if self.hud:
            self.hud.update_eval("Draw declined", duration=2.0)

    def _mp_draw_response(self, accepted: bool):
        if not accepted:
            if self.hud:
                self.hud.update_eval("Draw declined", duration=2.0)
            return

        self._clear_board_selection()
        self.gs.accept_draw()
        self._result_shown = False
        if self.hud:
            self.hud.update_eval("Draw accepted", duration=2.0)

    def _mp_takeback_offered(self):
        print("[Net] Takeback offered by opponent")
        if not self.gs.move_list:
            self.net.send_takeback_response(False)
            if self.hud:
                self.hud.update_eval("Nothing to take back", duration=2.0)
            return

        self._show_confirm_banner(
            "Opponent proposes a takeback.",
            on_confirm=self._accept_mp_takeback,
            on_cancel=self._decline_mp_takeback,
            confirm_text="Accept",
            cancel_text="Decline",
        )

    def _accept_mp_takeback(self):
        self._dismiss_confirm_banner()
        self._clear_board_selection()

        if self.net.is_hosting:
            accepted = self._mp_apply_takeback()
            self.net.send_takeback_response(accepted)
            if not accepted:
                if self.gs.is_game_over() and self._result_shown:
                    self._show_result_banner(
                        self.gs.result_reason(),
                        on_dismiss=self._dismiss_result,
                    )
                if self.hud:
                    self.hud.update_eval("Nothing to take back", duration=2.0)
                return
            self._mp_sync_to_client()
        else:
            self._result_shown = False
            self.net.send_takeback_response(True)

        if self.hud:
            self.hud.update_eval("Takeback accepted", duration=2.0)

    def _decline_mp_takeback(self):
        self.net.send_takeback_response(False)
        self._dismiss_confirm_banner(restore_result=True)
        if self.hud:
            self.hud.update_eval("Takeback declined", duration=2.0)

    def _mp_takeback_response(self, accepted: bool):
        self._mp_takeback_request_pending = False
        if not accepted:
            if self.hud:
                self.hud.update_eval("Takeback declined", duration=2.0)
            return

        if self.net.is_hosting:
            if not self._mp_apply_takeback():
                if self.hud:
                    self.hud.update_eval("Nothing to take back", duration=2.0)
                return
            self._mp_sync_to_client()
        else:
            self._result_shown = False
            self._destroy_result_banner()
            self._clear_board_selection()

        if self.hud:
            self.hud.update_eval("Takeback accepted", duration=2.0)

    def _mp_opponent_resigned(self, color_int):
        self.gs.resign(chess.Color(color_int))

    def _mp_disconnected(self):
        self._clear_premove(refresh=True)
        if self.hud:
            self.hud.update_status("Opponent disconnected")

    # ── Board + HUD setup ─────────────────────────────────────────────────────

    def _setup_board_and_hud(self):
        self._result_shown = False
        self.board_view = BoardView(self.gs)
        self.board_view.on_move = self._handle_board_move
        self.board_view.on_promotion_needed = self._handle_promotion_needed
        self.board_view.on_invalid_premove_target = self._cancel_premove_from_invalid_target

        self.hud = GameHUD({
            "undo":         self._undo_move,
            "redo":         self._redo_move,
            "flip":         self._flip_board,
            "resign":       self._resign,
            "offer_draw":   self._offer_draw,
            "fen":          self._copy_current_fen,
            "save_pgn":     self._save_pgn,
            "restart":      self._restart,
            "back_to_menu": self._back_to_menu,
        })
        self.hud.update_board_anchor(self.board_view)
        white_label, black_label = self._hud_side_labels()
        self.hud.update_status(self.gs.status_text)
        self.hud.update_clocks(
            self.gs.format_clock(self.gs.white_clock) if self.gs.base_time > 0 else "--:--",
            self.gs.format_clock(self.gs.black_clock) if self.gs.base_time > 0 else "--:--",
            white_label=white_label,
            black_label=black_label,
        )

    def _hud_side_labels(self) -> tuple[str, str]:
        if self.gs.mode == GameMode.MULTIPLAYER:
            return self.gs.white_name, self.gs.black_name
        return "White", "Black"

    def _teardown_game(self):
        self._invalidate_engine_request()
        self._dismiss_fen_editor_dialog()
        self._dismiss_promotion_dialog()
        self._mp_takeback_request_pending = False
        self.gs.clear_premove()
        if self.board_view:
            self.board_view.destroy()
            self.board_view = None
        if self.hud:
            self.hud.destroy()
            self.hud = None
        self._destroy_result_banner()
        self.net.stop()
        self.engine.quit()

    def _get_window_size(self) -> tuple[int, int]:
        return int(window.size.x), int(window.size.y)

    def _handle_window_resize(self):
        current_size = self._get_window_size()
        if 0 in current_size or current_size == self._window_size:
            return

        previous_size = self._window_size
        self._window_size = current_size
        window.prev_size = previous_size
        window.update_aspect_ratio()
        if self.board_view:
            self.board_view.reposition(preserve_selection=True)
            if self.hud:
                self.hud.update_board_anchor(self.board_view)

    def _invalidate_engine_request(self):
        self._engine_request_serial += 1
        self._pending_engine_move = None
        self._pending_engine_score = None
        self._pending_engine_request_id = None
        self._deferred_engine_request = False

    def _set_game_input_locked(self, locked: bool):
        if self.board_view:
            self.board_view.set_input_enabled(not locked)
        if self.hud:
            self.hud.set_input_enabled(not locked)

    def _clear_board_selection(self):
        if self.board_view:
            self.board_view.clear_selection()

    def _show_fen_editor(self, *, title: str, help_text: str,
                         default_value: str, submit_label: str,
                         on_back=None, back_label: str = "Back",
                         lock_game_input: bool = False):
        if self._fen_editor_dialog:
            self._fen_editor_dialog.destroy_panel()

        if lock_game_input:
            self._set_game_input_locked(True)

        self._fen_editor_dialog = FenEditorDialog(
            title=title,
            help_text=help_text,
            default_fen=default_value,
            on_submit=self._try_start_from_fen,
            on_back=on_back,
            submit_label=submit_label,
            back_label=back_label,
            on_destroy=self._on_fen_editor_destroyed,
        )

    def _dismiss_fen_editor_dialog(self):
        if self._fen_editor_dialog:
            self._fen_editor_dialog.destroy_panel()

    def _on_fen_editor_destroyed(self):
        self._fen_editor_dialog = None
        self._set_game_input_locked(False)

    def _clear_premove(self, *, refresh: bool = True,
                       message: str | None = None,
                       duration: float | None = 2.0) -> bool:
        had_premove = self.gs.premove_move is not None
        self.gs.clear_premove()
        if refresh and self.board_view:
            self.board_view.refresh()
        if message and self.hud:
            self.hud.update_eval(message, duration=duration)
        return had_premove

    def _cancel_premove_from_invalid_target(self, from_sq: int, _clicked_sq: int) -> bool:
        move = self.gs.premove_move
        if move is None or move.from_square != from_sq:
            return False
        return self._clear_premove(
            refresh=False,
            message="Premove canceled",
            duration=2.0,
        )

    def _queue_premove(self, move: chess.Move) -> bool:
        piece = self.gs.board.piece_at(move.from_square)
        if piece is None or not self.gs.can_premove_color(piece.color):
            return False
        if move not in self.gs.legal_moves_for_square(move.from_square):
            return False

        self.gs.set_premove(move, piece.color)
        if self.board_view:
            self.board_view.refresh()
        if self.hud:
            self.hud.update_eval("Premove queued", duration=2.0)
        return True

    def _try_execute_premove(self) -> bool:
        move = self.gs.premove_move
        color = self.gs.premove_color
        if move is None or color is None:
            return False
        if self._promotion_dialog or self.gs.is_game_over():
            self._clear_premove(refresh=True)
            return False
        if self.gs.board.turn != color:
            return False

        self.gs.clear_premove()
        if self.board_view:
            self.board_view.refresh()

        if move not in self.gs.board.legal_moves:
            if self.hud:
                self.hud.update_eval("Premove canceled", duration=2.0)
            return False

        self._handle_board_move(move)
        return True

    def _show_result_banner(self, text: str, on_dismiss):
        self._destroy_result_banner()
        self._set_game_input_locked(True)
        self.result_banner = ResultBanner(text, on_dismiss=on_dismiss)
        self._banner_kind = "result"

    def _show_confirm_banner(self, text: str, on_confirm, on_cancel,
                             confirm_text: str = "Accept",
                             cancel_text: str = "Decline"):
        restore_result = self._banner_kind == "result" and self.gs.is_game_over()
        self._destroy_result_banner()
        self._restore_result_banner_after_modal = restore_result
        self._set_game_input_locked(True)
        self.result_banner = ConfirmBanner(
            text,
            on_confirm=on_confirm,
            on_cancel=on_cancel,
            confirm_text=confirm_text,
            cancel_text=cancel_text,
        )
        self._banner_kind = "confirm"

    def _destroy_result_banner(self):
        if self.result_banner:
            self.result_banner.destroy_panel()
            self.result_banner = None
        self._banner_kind = None
        self._restore_result_banner_after_modal = False
        self._set_game_input_locked(False)

    def _dismiss_confirm_banner(self, restore_result: bool = False):
        self.result_banner = None
        self._banner_kind = None
        should_restore_result = (
            restore_result
            and self._restore_result_banner_after_modal
            and self.gs.is_game_over()
        )
        self._restore_result_banner_after_modal = False
        if should_restore_result:
            self._show_result_banner(
                self.gs.result_reason(),
                on_dismiss=self._dismiss_result,
            )
        else:
            self._set_game_input_locked(False)

    def _mp_apply_takeback(self) -> bool:
        if not self.gs.can_undo():
            return False

        if not self.gs.undo_move():
            return False

        self._destroy_result_banner()
        self._result_shown = False
        self._clear_board_selection()

        if self.board_view:
            self.board_view.refresh()
        if self.hud:
            self.hud.update_eval("")

        return True

    def _dismiss_promotion_dialog(self):
        if self._promotion_dialog:
            self._promotion_dialog.destroy_panel()
            self._promotion_dialog = None
        self._promo_from = None
        self._promo_to = None
        self._set_game_input_locked(False)

    # ── Move handling ─────────────────────────────────────────────────────────

    def _handle_board_move(self, move: chess.Move):
        """Called when the player clicks a legal move on the board."""
        if self._promotion_dialog:
            return

        if self.gs.is_game_over():
            return

        piece = self.gs.board.piece_at(move.from_square)
        if piece is None:
            return
        if piece.color != self.gs.board.turn:
            self._queue_premove(move)
            return

        if self.gs.mode == GameMode.MULTIPLAYER:
            # Only allow moves on our turn
            if self.gs.board.turn != self.gs.player_color:
                return
            if self.net.is_hosting:
                # Host can apply directly, then sync
                san = self.gs.board.san(move) if move in self.gs.board.legal_moves else ""
                if self.gs.try_move(move):
                    # host_board IS gs.board, already pushed
                    if self.board_view:
                        self.board_view.refresh()
                    # Tell client about host's move so they can apply it
                    self.net.send_move_accepted(move.uci(), san)
                    self._mp_sync_to_client()
            else:
                # Client: send request
                self.net.send_move_request(move.uci())
            return

        if self.gs.mode == GameMode.VS_ENGINE:
            if not self.gs.is_human_turn():
                return

        # Local or engine mode – apply move
        self._apply_move(move)

        # Engine mode: request engine reply
        if self.gs.mode == GameMode.VS_ENGINE and not self.gs.is_game_over():
            if not self.gs.is_human_turn():
                self._request_engine_move()

    def _apply_move(self, move: chess.Move):
        if self.gs.try_move(move):
            if self.board_view:
                self.board_view.refresh()
            self._try_execute_premove()

    def _handle_promotion_needed(self, from_sq: int, to_sq: int):
        """Show promotion dialog, then complete the move."""
        if self._promotion_dialog:
            return

        self._promo_from = from_sq
        self._promo_to = to_sq
        piece = self.gs.board.piece_at(from_sq)
        is_white = piece.color == chess.WHITE if piece else self.gs.board.turn == chess.WHITE
        self._set_game_input_locked(True)
        self._promotion_dialog = PromotionDialog(
            is_white,
            on_choose=self._complete_promotion,
            on_cancel=self._cancel_promotion,
        )

    def _complete_promotion(self, piece_type: int):
        if self._promo_from is not None and self._promo_to is not None:
            move = chess.Move(self._promo_from, self._promo_to, promotion=piece_type)
            self._dismiss_promotion_dialog()
            self._handle_board_move(move)

    def _cancel_promotion(self):
        self._dismiss_promotion_dialog()
        self._clear_board_selection()

    # ── Engine interaction ────────────────────────────────────────────────────

    def _request_engine_move(self):
        if self.engine.is_thinking:
            return
        if not self.engine.is_running:
            if not self.engine.start():
                if self.hud:
                    self.hud.update_eval("Engine not available")
                return

        self._deferred_engine_request = False
        request_id = self._engine_request_serial + 1
        self._engine_request_serial = request_id

        def _on_result(move, score):
            # Queue for main thread
            self._pending_engine_move = move
            self._pending_engine_score = score
            self._pending_engine_request_id = request_id

        self.engine.get_best_move(self.gs.board.copy(), callback=_on_result)

    # ── Toolbar actions ───────────────────────────────────────────────────────

    def _flip_board(self):
        if self._promotion_dialog:
            return
        self.gs.flipped = not self.gs.flipped
        if self.board_view:
            self.board_view.reposition()
            if self.hud:
                self.hud.update_board_anchor(self.board_view)

    def _undo_move(self):
        if self._promotion_dialog:
            return

        if self.gs.mode == GameMode.MULTIPLAYER:
            self._propose_takeback()
            return

        undone = False
        if self.gs.mode == GameMode.VS_ENGINE:
            self._invalidate_engine_request()
            while self.gs.can_undo():
                if not self.gs.undo_move():
                    break
                undone = True
                if self.gs.is_human_turn():
                    break
        else:
            undone = self.gs.undo_move()

        if not undone:
            if self.hud:
                self.hud.update_eval("Nothing to undo", duration=2.0)
            return

        self._destroy_result_banner()
        self._result_shown = False

        if self.board_view:
            self.board_view.refresh()
        if self.hud:
            self.hud.update_eval("")

        if self.gs.mode == GameMode.VS_ENGINE and not self.gs.is_human_turn():
            if self.engine.is_thinking:
                self._deferred_engine_request = True
            else:
                self._request_engine_move()

    def _redo_move(self):
        if self._promotion_dialog:
            return

        if self.gs.mode == GameMode.MULTIPLAYER:
            if self.hud:
                self.hud.update_eval("Redo unavailable online", duration=2.0)
            return

        redone = False
        if self.gs.mode == GameMode.VS_ENGINE:
            self._invalidate_engine_request()
            while self.gs.can_redo():
                if not self.gs.redo_move():
                    break
                redone = True
                if self.gs.is_human_turn():
                    break
        else:
            redone = self.gs.redo_move()

        if not redone:
            if self.hud:
                self.hud.update_eval("Nothing to redo", duration=2.0)
            return

        self._destroy_result_banner()
        self._result_shown = False

        if self.board_view:
            self.board_view.refresh()
        if self.hud:
            self.hud.update_eval("")

        if self.gs.mode == GameMode.VS_ENGINE and not self.gs.is_human_turn():
            if self.engine.is_thinking:
                self._deferred_engine_request = True
            else:
                self._request_engine_move()

    def _propose_takeback(self):
        if not self.net.connected:
            if self.hud:
                self.hud.update_eval("Not connected", duration=2.0)
            return

        if not self.gs.move_list:
            if self.hud:
                self.hud.update_eval("Nothing to take back", duration=2.0)
            return

        if self._mp_takeback_request_pending:
            if self.hud:
                self.hud.update_eval("Takeback already proposed", duration=2.0)
            return

        self.net.send_offer_takeback()
        self._mp_takeback_request_pending = True
        self._clear_board_selection()
        if self.hud:
            self.hud.update_eval("Takeback proposed", duration=2.0)

    def _resign(self):
        if self._promotion_dialog:
            return
        if self.gs.is_game_over():
            return
        if self.gs.mode == GameMode.MULTIPLAYER:
            c = self.gs.player_color
            self.gs.resign(c)
            self.net.send_resign(int(c))
        else:
            # In local mode, current side resigns
            self.gs.resign(self.gs.turn)
        self._clear_board_selection()

    def _offer_draw(self):
        if self._promotion_dialog:
            return
        if self.gs.is_game_over():
            return
        if self.gs.mode == GameMode.MULTIPLAYER:
            self.net.send_offer_draw()
        else:
            self.gs.accept_draw()
            self._clear_board_selection()

    def _open_fen_editor(self):
        if self._promotion_dialog or self._fen_editor_dialog:
            return
        self._show_fen_editor(
            title="FEN Editor",
            help_text="Edit the current position directly on the board, copy the resulting FEN, or load it as a local game without a clock.",
            default_value=self.gs.fen,
            submit_label="Load",
            back_label="Close",
            lock_game_input=True,
        )

    def _copy_current_fen(self):
        if self._promotion_dialog:
            return

        fen = self.gs.fen
        copied = True
        try:
            pyperclip.copy(fen)
        except Exception as exc:
            copied = False
            if self.hud:
                self.hud.update_eval(f"Clipboard access failed: {exc}", duration=2.0)

        if self.hud:
            self.hud.show_fen(fen, copied_to_clipboard=copied)

    def _save_pgn(self):
        if self._promotion_dialog:
            return
        path = self.gs.save_pgn()
        print(f"[PGN] Saved to {path}")
        if self.hud:
            self.hud.update_eval("PGN saved", duration=2.0)

    def _restart(self):
        if self._promotion_dialog:
            return

        restart_state = dict(self._restart_state) if self._restart_state else None
        self._teardown_game()
        if not restart_state:
            self._show_main_menu()
            return

        kind = restart_state.get("kind")
        if kind == "local":
            self._start_local_with_tc(restart_state["time_control"])
        elif kind == "engine":
            self._start_engine_game(
                restart_state["player_color"],
                restart_state["time_control"],
            )
        elif kind == "fen":
            self._start_from_fen_game(restart_state["fen"])
        elif kind == "pgn":
            self._start_from_pgn_game(restart_state["pgn_text"])
        else:
            self._show_main_menu()

    def _back_to_menu(self):
        if self._promotion_dialog:
            return
        self._teardown_game()
        self._show_main_menu()

    def _dismiss_result(self):
        self.result_banner = None
        self._banner_kind = None
        self._restore_result_banner_after_modal = False
        self._clear_board_selection()
        self._set_game_input_locked(False)

    # ── Settings ──────────────────────────────────────────────────────────────

    def _on_settings(self):
        self._hide_main_menu()
        self.settings_panel = SettingsPanel(
            on_close=self._close_settings,
            current_depth=self.engine.depth,
            current_skill=self.engine.skill_level,
            current_time=self.engine.move_time,
        )

    def _close_settings(self, skill, depth, move_time):
        self.engine.set_skill_level(skill)
        self.engine.set_depth(depth)
        self.engine.set_move_time(move_time)
        self.settings_panel = None
        self._show_main_menu()

    def _on_exit(self):
        self._teardown_game()
        application.quit()


# ═══════════════════════════════════════════════════════════════════════════════
#  Ursina bootstrap
# ═══════════════════════════════════════════════════════════════════════════════

app_instance: ChessApp | None = None

def update():
    """Global Ursina update hook."""
    if app_instance:
        app_instance.update()


def _apply_window_mode():
    """
    Prefer a large window by default and use borderless monitor-sized mode on
    macOS instead of Panda fullscreen, which is less reliable there.
    """
    if not WINDOW_FULLSCREEN:
        return

    if sys.platform == "darwin" and window.main_monitor:
        window.borderless = True
        window.position = (window.main_monitor.x, window.main_monitor.y)
        window.size = (window.main_monitor.width, window.main_monitor.height)
        return

    window.fullscreen = True


if __name__ == "__main__":
    import socket

    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    print("local ip", local_ip)

    Texture.default_filtering = TEXTURE_FILTERING

    ursina_app = Ursina(
        title=WINDOW_TITLE,
        borderless=WINDOW_BORDERLESS,
        fullscreen=False,
        size=WINDOW_SIZE,
        development_mode=False,
        vsync=ENABLE_VSYNC,
    )

    # Set orthographic camera for 2D UI
    camera.orthographic = True
    camera.fov = 1
    if ENABLE_FXAA and fxaa_shader is not None:
        camera.shader = fxaa_shader
    _apply_window_mode()

    app_instance = ChessApp()
    app_instance.start()

    ursina_app.run()
