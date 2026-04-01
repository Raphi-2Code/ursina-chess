"""
ui_menus.py – All Ursina UI panels: main menu, settings, promotion dialog,
engine download dialog, HUD (clocks, move list, status), and in-game toolbar.
"""

from __future__ import annotations

import chess
import pyperclip
from pathlib import Path
from textwrap import wrap
from time import monotonic
from ursina import (
    Entity, Button, Text, camera, color,
    destroy, Func, application, WindowPanel,
    Slider, InputField, ButtonGroup, mouse, invoke, Draggable,
)

from settings import (
    TIME_CONTROLS, BOARD_SIZE, SQUARE_SIZE, BOARD_ORIGIN_X, BOARD_ORIGIN_Y,
    LIGHT_COLOR, DARK_COLOR, PIECE_UNICODE,
    DEFAULT_SKILL_LEVEL, DEFAULT_ENGINE_DEPTH, DEFAULT_ENGINE_TIME, PGN_DIR,
)


UNDO_BUTTON_TEXTURE_PATH = Path(__file__).resolve().parent / "assets" / "undo_button_menu.png"
UNDO_BUTTON_TEXTURE_NAME = "assets/undo_button_menu.png"
REDO_BUTTON_TEXTURE_PATH = Path(__file__).resolve().parent / "assets" / "redo_button_menu.png"
REDO_BUTTON_TEXTURE_NAME = "assets/redo_button_menu.png"
FLIP_BUTTON_TEXTURE_PATH = Path(__file__).resolve().parent / "assets" / "flip_button.png"
FLIP_BUTTON_TEXTURE_NAME = "assets/flip_button.png"
RESIGN_BUTTON_TEXTURE_PATH = Path(__file__).resolve().parent / "assets" / "resign_button.png"
RESIGN_BUTTON_TEXTURE_NAME = "assets/resign_button.png"
DRAW_BUTTON_TEXTURE_PATH = Path(__file__).resolve().parent / "assets" / "draw_button.png"
DRAW_BUTTON_TEXTURE_NAME = "assets/draw_button.png"
RESTART_BUTTON_TEXTURE_PATH = Path(__file__).resolve().parent / "assets" / "restart_button.png"
RESTART_BUTTON_TEXTURE_NAME = "assets/restart_button.png"
SAVE_PGN_BUTTON_TEXTURE_PATH = Path(__file__).resolve().parent / "assets" / "save_pgn_button.png"
SAVE_PGN_BUTTON_TEXTURE_NAME = "assets/save_pgn_button.png"
COPY_FEN_BUTTON_TEXTURE_PATH = Path(__file__).resolve().parent / "assets" / "copy_fen_button.png"
COPY_FEN_BUTTON_TEXTURE_NAME = "assets/copy_fen_button.png"
MENU_BUTTON_TEXTURE_PATH = Path(__file__).resolve().parent / "assets" / "menu_button.png"
MENU_BUTTON_TEXTURE_NAME = "assets/menu_button.png"
BUTTON_ICON_HEIGHT = 0.80
FEN_TEXT_MAX_LINE_LENGTH = 18
SHARED_FEN_DISPLAY_SCALE = (0.34, 0.10)
INPUT_FIELD_VIEWPORT_WIDTH_RATIO = 0.72
INPUT_FIELD_TEXT_PRESCALE = 1.25
SHARED_FEN_TEXT_SCALE = 0.5
SHARED_FEN_TEXT_LINE_HEIGHT = 1.0


def _wrap_ui_text(text: str, width: int) -> str:
    """Wrap UI text before handing it to Ursina's Text widget."""
    if not text:
        return ""

    wrapped_lines: list[str] = []
    for line in text.splitlines() or [""]:
        wrapped = wrap(
            line,
            width=width,
            break_long_words=False,
            break_on_hyphens=False,
        )
        wrapped_lines.extend(wrapped or [""])
    return "\n".join(wrapped_lines)


def _format_fen_for_display(fen: str, line_width: int = FEN_TEXT_MAX_LINE_LENGTH) -> str:
    """Format a FEN into compact display lines that fit narrow UI panels."""
    parts = fen.split()
    if not parts:
        return ""

    board_part = parts[0]
    board_lines: list[str] = []
    current_line = ""
    for rank in board_part.split("/"):
        candidate = rank if not current_line else f"{current_line}/{rank}"
        if current_line and len(candidate) > line_width:
            board_lines.append(current_line)
            current_line = rank
        else:
            current_line = candidate
    if current_line:
        board_lines.append(current_line)

    extra_lines: list[str] = []
    extra_fields = " ".join(parts[1:])
    if extra_fields:
        extra_lines = wrap(
            extra_fields,
            width=line_width,
            break_long_words=False,
            break_on_hyphens=False,
        )

    return "\n".join(board_lines + extra_lines)


def _rgba255(r: int, g: int, b: int, a: int = 255):
    """Convenience wrapper for Ursina colors when working with 0-255 RGBA values."""
    return color.rgba(r / 255, g / 255, b / 255, a / 255)


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN MENU
# ═══════════════════════════════════════════════════════════════════════════════

class MainMenu:
    """Full-screen main menu with game mode buttons."""

    def __init__(self, callbacks: dict):
        """
        callbacks keys:
            local, start_from_fen, start_from_pgn, open_saved_pgn,
            vs_engine, host, join, settings, exit
        """
        self.entities: list[Entity] = []
        self.callbacks = callbacks
        self._build()

    def _build(self):
        # Title
        t = Text(
            text="URSINA CHESS",
            parent=camera.ui,
            scale=3.0,
            position=(0, 0.38),
            origin=(0, 0),
            color=color.white,
        )
        self.entities.append(t)

        buttons = [
            ("Local Game",          self.callbacks.get("local")),
            ("Start From FEN",      self.callbacks.get("start_from_fen")),
            ("Start From PGN",      self.callbacks.get("start_from_pgn")),
            ("Open Saved PGN",      self.callbacks.get("open_saved_pgn")),
            ("Play vs Engine",      self.callbacks.get("vs_engine")),
            ("Host Multiplayer",    self.callbacks.get("host")),
            ("Join Multiplayer",    self.callbacks.get("join")),
            ("Settings",            self.callbacks.get("settings")),
            ("Exit",                self.callbacks.get("exit")),
        ]
        for i, (label, cb) in enumerate(buttons):
            b = Button(
                text=label,
                parent=camera.ui,
                scale=(0.35, 0.05),
                position=(0, 0.18 - i * 0.07),
                color=color.dark_gray,
                highlight_color=color.gray,
                on_click=cb if cb else Func(print, label),
            )
            self.entities.append(b)

    def show(self):
        for e in self.entities:
            e.enabled = True

    def hide(self):
        for e in self.entities:
            e.enabled = False

    def destroy(self):
        for e in self.entities:
            destroy(e)
        self.entities.clear()


# ═══════════════════════════════════════════════════════════════════════════════
#  TEXT IMPORT DIALOGS
# ═══════════════════════════════════════════════════════════════════════════════

class TextImportDialog:
    """Overlay for importing a game from FEN or PGN text."""

    def __init__(self, title: str, help_text: str, on_submit, on_back,
                 default_value: str = "", submit_label: str = "Start",
                 max_lines: int = 1, character_limit: int = 256,
                 panel_scale: tuple[float, float] = (0.86, 0.40),
                 input_scale: tuple[float, float] = (0.74, 0.05),
                 input_offset_y: float = 0.0,
                 back_label: str = "Back",
                 copy_button_label: str | None = None,
                 on_destroy=None):
        self.title = title
        self.help_text = help_text
        self.on_submit = on_submit
        self.on_back = on_back
        self.default_value = default_value
        self.submit_label = submit_label
        self.max_lines = max_lines
        self.character_limit = character_limit
        self.panel_scale = panel_scale
        self.input_scale = input_scale
        self.input_offset_y = input_offset_y
        self.back_label = back_label
        self.copy_button_label = copy_button_label
        self.on_destroy = on_destroy
        self.entities: list[Entity] = []
        self.input_field: InputField | None = None
        self.error_text: Text | None = None
        self._destroyed = False
        self._error_generation = 0
        self._build()

    @staticmethod
    def _entity_alive(entity: Entity | None) -> bool:
        if entity is None:
            return False
        try:
            return not entity.is_empty()
        except Exception:
            return False

    def _input_field_alive(self, input_field: InputField | None = None) -> bool:
        if self._destroyed:
            return False

        field = input_field or self.input_field
        if not self._entity_alive(field):
            return False

        text_field = getattr(field, "text_field", None)
        return all(
            self._entity_alive(entity)
            for entity in (
                text_field,
                getattr(text_field, "text_entity", None),
                getattr(text_field, "scroll_parent", None),
                getattr(text_field, "cursor", None),
                getattr(text_field, "cursor_parent", None),
            )
        )

    def _set_error(self, message: str, duration: float | None = None):
        self._error_generation += 1
        generation = self._error_generation

        if self.error_text:
            self.error_text.text = _wrap_ui_text(message, 44) if message else ""

        if message and duration is not None:
            invoke(self._clear_error_if_current, generation, delay=max(0.0, duration))

    def _clear_error_if_current(self, generation: int):
        if self._destroyed or generation != self._error_generation or not self.error_text:
            return
        self.error_text.text = ""

    def _visible_input_columns(self, input_field: InputField) -> int:
        if not self._input_field_alive(input_field):
            return 8

        text_field = input_field.text_field
        try:
            char_width = text_field.character_width * max(text_field.scale_x, 0.0001)
            available_width = input_field.scale_x * INPUT_FIELD_VIEWPORT_WIDTH_RATIO
        except AssertionError:
            return 8

        if char_width <= 0:
            return 1
        return max(8, int(available_width / char_width))

    def _configure_input_field_viewport(self, input_field: InputField):
        text_field = input_field.text_field
        original_input = text_field.input
        original_text_input = text_field.text_input
        original_update = text_field.update
        original_get_mouse_position = text_field.get_mouse_position

        text_field._horizontal_scroll = 0
        text_field._prev_horizontal_scroll = 0

        def render():
            if not self._input_field_alive(input_field):
                return

            lines = text_field.text.split('\n')
            if not lines:
                lines = [""]

            if text_field.max_lines < 9999:
                max_vertical_scroll = max(0, len(lines) - text_field.max_lines)
                text_field.scroll = max(0, min(text_field.scroll, max_vertical_scroll))

            visible_columns = self._visible_input_columns(input_field)
            cursor_y = max(0, min(int(text_field.cursor.y), len(lines) - 1))
            cursor_x = max(0, int(text_field.cursor.x))
            current_line = lines[cursor_y]
            max_horizontal_scroll = max(0, len(current_line) - visible_columns)
            horizontal_scroll = int(getattr(text_field, "_horizontal_scroll", 0))

            if cursor_x < horizontal_scroll:
                horizontal_scroll = cursor_x
            elif cursor_x > horizontal_scroll + visible_columns - 1:
                horizontal_scroll = cursor_x - visible_columns + 1

            horizontal_scroll = max(0, min(horizontal_scroll, max_horizontal_scroll))
            text_field._horizontal_scroll = horizontal_scroll

            if text_field.max_lines < 9999:
                visible_lines = lines[text_field.scroll:text_field.max_lines + text_field.scroll]
                display_body = '\n'.join(
                    line[horizontal_scroll:horizontal_scroll + visible_columns]
                    for line in visible_lines
                )
                display_text = ('\n' * text_field.scroll) + display_body
                text_field.scroll_parent.y = text_field.scroll * Text.size * text_field.line_height
                text_field.cursor.visible = (
                    text_field.cursor.y >= text_field.scroll
                    and text_field.cursor.y < text_field.scroll + text_field.max_lines
                )
            else:
                display_text = '\n'.join(
                    line[horizontal_scroll:horizontal_scroll + visible_columns]
                    for line in lines
                )
                text_field.scroll_parent.y = text_field.scroll * Text.size * text_field.line_height
                text_field.cursor.visible = True

            previous_horizontal_scroll = getattr(text_field, "_prev_horizontal_scroll", None)
            if (
                not hasattr(text_field.text_entity, 'raw_text')
                or text_field._prev_text != display_text
                or text_field.scroll != text_field._prev_scroll
                or previous_horizontal_scroll != horizontal_scroll
            ):
                text_field.text_entity.text = display_text
                text_field._prev_text = display_text
                text_field._prev_scroll = text_field.scroll
                text_field._prev_horizontal_scroll = horizontal_scroll

            text_field.cursor_parent.x = -(horizontal_scroll * text_field.character_width)
            text_field.draw_selection()

            if text_field.on_value_changed:
                text_field.on_value_changed()

        def input_with_viewport(key):
            if not self._input_field_alive(input_field):
                return
            original_input(key)
            render()

        def text_input_with_viewport(key):
            if not self._input_field_alive(input_field):
                return
            original_text_input(key)
            render()

        def update_with_viewport():
            if not self._input_field_alive(input_field):
                return
            original_update()
            if text_field.active and mouse.left and mouse.moving:
                render()

        def get_mouse_position_with_viewport():
            if not self._input_field_alive(input_field):
                return 0, 0
            x, y = original_get_mouse_position()
            lines = text_field.text.split('\n')
            if not lines:
                return x, y

            y = max(0, min(y, len(lines) - 1))
            horizontal_scroll = int(getattr(text_field, "_horizontal_scroll", 0))
            x = min(x + horizontal_scroll, len(lines[y]))
            return x, y

        text_field.render = render
        text_field.input = input_with_viewport
        text_field.text_input = text_input_with_viewport
        text_field.update = update_with_viewport
        text_field.get_mouse_position = get_mouse_position_with_viewport
        text_field.render()

    def _build(self):
        panel_height = self.panel_scale[1]
        title_y = panel_height / 2 - 0.08
        help_y = title_y - 0.08
        input_y = help_y - (0.12 if self.max_lines == 1 else 0.20) + self.input_offset_y
        error_y = -panel_height / 2 + 0.11
        button_y = -panel_height / 2 + 0.05

        bg = Entity(parent=camera.ui, model="quad", color=color.rgba(0, 0, 0, 0.7),
                     scale=(2, 2), z=0.5)
        self.entities.append(bg)

        panel = Entity(parent=camera.ui, model="quad", color=color.dark_gray,
                        scale=self.panel_scale, z=0.4)
        self.entities.append(panel)

        title = Text(text=self.title, parent=camera.ui, scale=1.8,
                      position=(0, title_y), origin=(0, 0), z=0.3, color=color.white)
        self.entities.append(title)

        help_label = Text(
            text=_wrap_ui_text(self.help_text, 46),
            parent=camera.ui,
            scale=0.9,
            position=(0, help_y),
            origin=(0, 0),
            z=0.3,
            color=color.light_gray,
        )
        self.entities.append(help_label)

        self.input_field = InputField(
            default_value=self.default_value,
            parent=camera.ui,
            max_lines=self.max_lines,
            character_limit=self.character_limit,
            scale=self.input_scale,
            position=(0, input_y),
            z=0.3,
            color=color.black66,
            active=True,
        )
        self.input_field.text_field.x = -0.33
        self._configure_input_field_viewport(self.input_field)
        self.entities.append(self.input_field)

        action_btn_y = input_y + (self.input_scale[1] / 2) + 0.03
        if self.copy_button_label:
            copy_btn = Button(
                text=self.copy_button_label,
                parent=camera.ui,
                scale=(0.22, 0.035),
                position=(-0.12, action_btn_y),
                z=0.3,
                color=color.gray,
                on_click=Func(self._copy_to_clipboard),
            )
            self.entities.append(copy_btn)
            paste_btn_x = 0.12
            paste_btn_scale = (0.22, 0.035)
        else:
            paste_btn_x = 0.20
            paste_btn_scale = (0.26, 0.035)

        paste_btn = Button(
            text="Paste from Clipboard",
            parent=camera.ui,
            scale=paste_btn_scale,
            position=(paste_btn_x, action_btn_y),
            z=0.3,
            color=color.gray,
            on_click=Func(self._paste_from_clipboard),
        )
        self.entities.append(paste_btn)

        self.error_text = Text(
            text="",
            parent=camera.ui,
            scale=0.9,
            position=(0, error_y),
            origin=(0, 0),
            z=0.3,
            color=color.rgb(1.0, 0.45, 0.45),
        )
        self.entities.append(self.error_text)

        start_btn = Button(
            text=self.submit_label,
            parent=camera.ui,
            scale=(0.16, 0.04),
            position=(-0.09, button_y),
            z=0.3,
            color=color.azure,
            on_click=Func(self._submit),
        )
        self.entities.append(start_btn)

        back_btn = Button(
            text=self.back_label,
            parent=camera.ui,
            scale=(0.16, 0.04),
            position=(0.09, button_y),
            z=0.3,
            color=color.gray,
            on_click=Func(self._go_back),
        )
        self.entities.append(back_btn)

    def _submit(self):
        if not self.input_field:
            return

        value = self.input_field.text_field.text
        error = self.on_submit(value) if self.on_submit else None
        if error:
            self._set_error(error)
            return

        self.destroy_panel()

    def _paste_from_clipboard(self):
        if not self.input_field:
            return

        try:
            pasted_text = pyperclip.paste()
        except Exception as exc:
            self._set_error(f"Clipboard access failed: {exc}")
            return

        if pasted_text is None:
            pasted_text = ""
        elif not isinstance(pasted_text, str):
            pasted_text = str(pasted_text)

        pasted_text = pasted_text.strip()
        if not pasted_text:
            self._set_error("Clipboard is empty.", duration=2.0)
            return

        self.input_field.text = pasted_text
        self._set_error("")

    def _copy_to_clipboard(self):
        if not self.input_field:
            return

        value = self.input_field.text_field.text.strip()
        if not value:
            self._set_error("Nothing to copy.", duration=2.0)
            return

        try:
            pyperclip.copy(value)
        except Exception as exc:
            self._set_error(f"Clipboard access failed: {exc}")
            return

        self._set_error("Copied to clipboard.", duration=2.0)

    def _go_back(self):
        self.destroy_panel()
        if self.on_back:
            self.on_back()

    def destroy_panel(self):
        if self._destroyed:
            return

        self._destroyed = True
        self._error_generation += 1

        if self.input_field and self._entity_alive(self.input_field):
            try:
                self.input_field.active = False
            except Exception:
                pass

            text_field = getattr(self.input_field, "text_field", None)
            if self._entity_alive(text_field):
                try:
                    text_field.active = False
                except Exception:
                    pass
                text_field.input = lambda *_args, **_kwargs: None
                text_field.text_input = lambda *_args, **_kwargs: None
                text_field.update = lambda *_args, **_kwargs: None
                text_field.get_mouse_position = lambda *_args, **_kwargs: (0, 0)

        for e in self.entities:
            destroy(e)
        self.entities.clear()
        self.input_field = None
        self.error_text = None
        if self.on_destroy:
            self.on_destroy()


class _FenEditorPieceToken(Draggable):
    """Draggable palette or board piece inside the FEN editor."""

    def __init__(self, editor, piece_symbol: str, home_position,
                 *, source_square: int | None = None,
                 scale: tuple[float, float] = (0.05, 0.05),
                 background_color=None):
        tile_color = background_color or _rgba255(210, 210, 210, 64)
        super().__init__(
            parent=camera.ui,
            model="quad",
            scale=scale,
            position=home_position,
            z=0.22,
            color=tile_color,
            highlight_color=tile_color,
            pressed_color=tile_color,
            radius=0.06,
        )
        self.editor = editor
        self.piece_symbol = piece_symbol
        self.source_square = source_square
        self.home_position = home_position
        self.home_z = 0.22

        piece = chess.Piece.from_symbol(piece_symbol)
        glyph_color = (
            color.rgb(0.82, 0.80, 0.76)
            if piece.color == chess.WHITE
            else color.rgb(0.32, 0.28, 0.24)
        )
        self.glyph = Text(
            text=PIECE_UNICODE.get(piece_symbol, "?"),
            parent=self,
            origin=(0, 0),
            position=(0, 0, -0.01),
            scale=18.0,
            font="DejaVuSans.ttf",
            color=glyph_color,
        )

    def drag(self):
        self.z = 0.10

    def input(self, key):
        if self.hovered and key == "right mouse down" and self.source_square is not None:
            self.editor._clear_square(self.source_square)
            return
        super().input(key)

    def drop(self):
        if self.editor._destroyed:
            return

        accepted = self.editor._handle_piece_drop(self)
        if self.source_square is None or not accepted:
            self.snap_home()

    def snap_home(self):
        self.position = self.home_position
        self.z = self.home_z


class FenEditorDialog:
    """Overlay for visually building or editing a FEN position."""

    PANEL_SCALE = (0.96, 0.96)
    FEN_INPUT_SCALE = SHARED_FEN_DISPLAY_SCALE
    BOARD_SQUARE_SIZE = 0.052
    BOARD_ORIGIN_X = -0.36
    BOARD_ORIGIN_Y = 0.14
    CONTROL_X = 0.25
    STATUS_Y = -0.36125
    BOARD_FRAME_PADDING = 0.036

    def __init__(self, title: str, help_text: str, default_fen: str,
                 on_submit, on_back=None, submit_label: str = "Start",
                 back_label: str = "Back", on_destroy=None):
        self.title = title
        self.help_text = help_text
        self.default_fen = default_fen
        self.on_submit = on_submit
        self.on_back = on_back
        self.submit_label = submit_label
        self.back_label = back_label
        self.on_destroy = on_destroy

        self.entities: list[Entity] = []
        self.square_buttons: dict[int, Button] = {}
        self.board_piece_tokens: dict[int, _FenEditorPieceToken] = {}
        self.palette_tokens: list[_FenEditorPieceToken] = []
        self.turn_buttons: dict[bool, Button] = {}
        self.castling_buttons: dict[str, Button] = {}

        self.fen_input: InputField | None = None
        self.ep_input: InputField | None = None
        self.halfmove_input: InputField | None = None
        self.fullmove_input: InputField | None = None
        self.status_text: Text | None = None
        self._destroyed = False
        self._status_generation = 0
        self._synced_fen_text = ""
        self.board = chess.Board()

        self._build()
        error = self._load_fen(default_fen, show_status=False)
        if error:
            self._set_status(error)

    @staticmethod
    def _entity_alive(entity: Entity | None) -> bool:
        if entity is None:
            return False
        try:
            return not entity.is_empty()
        except Exception:
            return False

    def _set_status(self, message: str, duration: float | None = None):
        self._status_generation += 1
        generation = self._status_generation

        if self.status_text:
            self.status_text.text = _wrap_ui_text(message, 42) if message else ""

        if message and duration is not None:
            invoke(self._clear_status_if_current, generation, delay=max(0.0, duration))

    def _clear_status_if_current(self, generation: int):
        if self._destroyed or generation != self._status_generation or not self.status_text:
            return
        self.status_text.text = ""

    def _build(self):
        bg = Entity(
            parent=camera.ui,
            model="quad",
            color=color.rgba(0, 0, 0, 0.78),
            scale=(2, 2),
            z=0.5,
        )
        self.entities.append(bg)

        panel = Entity(
            parent=camera.ui,
            model="quad",
            color=color.dark_gray,
            scale=self.PANEL_SCALE,
            z=0.4,
        )
        self.entities.append(panel)

        board_span = BOARD_SIZE * self.BOARD_SQUARE_SIZE
        board_center_x = self.BOARD_ORIGIN_X + ((BOARD_SIZE - 1) * self.BOARD_SQUARE_SIZE / 2)
        board_center_y = self.BOARD_ORIGIN_Y - ((BOARD_SIZE - 1) * self.BOARD_SQUARE_SIZE / 2)
        board_frame_scale = board_span + (self.BOARD_FRAME_PADDING * 2)

        title = Text(
            text=self.title,
            parent=camera.ui,
            scale=1.8,
            position=(0, 0.34),
            origin=(0, 0),
            z=0.3,
            color=color.white,
        )
        self.entities.append(title)

        help_label = Text(
            text=_wrap_ui_text(self.help_text, 72),
            parent=camera.ui,
            scale=0.86,
            position=(0, 0.27),
            origin=(0, 0),
            z=0.3,
            color=color.light_gray,
        )
        self.entities.append(help_label)

        board_frame = Entity(
            parent=camera.ui,
            model="quad",
            color=color.black66,
            scale=(board_frame_scale, board_frame_scale),
            position=(board_center_x, board_center_y),
            z=0.28,
        )
        self.entities.append(board_frame)

        controls_panel = Entity(
            parent=camera.ui,
            model="quad",
            color=color.clear,
            scale=(0.42, 0.76),
            position=(0.26, -0.02),
            z=0.28,
        )
        self.entities.append(controls_panel)

        self._build_board()
        self._build_palette()
        self._build_controls()

    def _build_board(self):
        for sq in chess.SQUARES:
            file_index = chess.square_file(sq)
            rank_index = chess.square_rank(sq)
            x, y = self._square_to_ui(file_index, rank_index)
            is_light = (file_index + rank_index) % 2 == 1
            square_color = color.rgba(*LIGHT_COLOR) if is_light else color.rgba(*DARK_COLOR)
            btn = Button(
                parent=camera.ui,
                model="quad",
                color=square_color,
                scale=(self.BOARD_SQUARE_SIZE, self.BOARD_SQUARE_SIZE),
                position=(x, y, 0.24),
                origin=(0, 0),
                highlight_color=square_color.tint(0.08),
                pressed_color=square_color.tint(-0.05),
                radius=0,
                text="",
            )
            btn.square = sq
            btn.on_click = Func(self._handle_square_left_click, sq)
            btn.input = lambda key, square=sq, button=btn: self._handle_square_input(button, square, key)
            self.square_buttons[sq] = btn
            self.entities.append(btn)

        for file_index in range(BOARD_SIZE):
            x, _ = self._square_to_ui(file_index, 0)
            file_label = Text(
                text=chr(ord("a") + file_index),
                parent=camera.ui,
                scale=0.8,
                position=(x, self.BOARD_ORIGIN_Y - (BOARD_SIZE - 1) * self.BOARD_SQUARE_SIZE - 0.045),
                origin=(0, 0),
                z=0.23,
                color=color.light_gray,
            )
            self.entities.append(file_label)

        for rank_index in range(BOARD_SIZE):
            _, y = self._square_to_ui(0, rank_index)
            rank_label = Text(
                text=str(rank_index + 1),
                parent=camera.ui,
                scale=0.8,
                position=(self.BOARD_ORIGIN_X - 0.05, y),
                origin=(0, 0),
                z=0.23,
                color=color.light_gray,
            )
            self.entities.append(rank_label)

    def _build_palette(self):
        board_span = BOARD_SIZE * self.BOARD_SQUARE_SIZE
        board_center_x = self.BOARD_ORIGIN_X + ((BOARD_SIZE - 1) * self.BOARD_SQUARE_SIZE / 2)
        board_center_y = self.BOARD_ORIGIN_Y - ((BOARD_SIZE - 1) * self.BOARD_SQUARE_SIZE / 2)
        board_frame_top = board_center_y + ((board_span + (self.BOARD_FRAME_PADDING * 2)) / 2)

        label = Text(
            text="Drag pieces onto the board. Right click a square to clear it.",
            parent=camera.ui,
            scale=0.8,
            position=(board_center_x, board_frame_top + 0.025),
            origin=(0, 0),
            z=0.3,
            color=color.light_gray,
        )
        self.entities.append(label)

        symbols = ["K", "Q", "R", "B", "N", "P", "k", "q", "r", "b", "n", "p"]
        start_x = -0.33
        start_y = -0.34
        step_x = 0.062
        step_y = 0.07
        for index, symbol in enumerate(symbols):
            column = index % 6
            row = index // 6
            token = _FenEditorPieceToken(
                self,
                symbol,
                (start_x + column * step_x, start_y - row * step_y, 0.22),
                scale=(0.052, 0.052),
                background_color=_rgba255(214, 206, 194, 78),
            )
            self.palette_tokens.append(token)
            self.entities.append(token)

    def _build_controls(self):
        x = self.CONTROL_X
        controls_center_x = x + 0.01

        fen_label = Text(
            text="FEN",
            parent=camera.ui,
            scale=1.0,
            position=(x, 0.20),
            origin=(0, 0),
            z=0.3,
            color=color.white,
        )
        self.entities.append(fen_label)

        fen_input_bg = Entity(
            parent=camera.ui,
            model="quad",
            color=color.rgba(0, 0, 0, 0.70),
            scale=self.FEN_INPUT_SCALE,
            position=(x, 0.12),
            z=0.295,
        )
        self.entities.append(fen_input_bg)

        self.fen_input = InputField(
            default_value="",
            parent=camera.ui,
            max_lines=4,
            character_limit=256,
            scale=self.FEN_INPUT_SCALE,
            position=(x, 0.12),
            z=0.301,
            color=color.clear,
        )
        self.fen_input.highlight_color = color.clear
        self.fen_input.pressed_color = color.clear
        self.fen_input.text_field.scale *= SHARED_FEN_TEXT_SCALE / INPUT_FIELD_TEXT_PRESCALE
        self.fen_input.text_field.line_height = SHARED_FEN_TEXT_LINE_HEIGHT
        self.fen_input.text_field.text_entity.line_height = SHARED_FEN_TEXT_LINE_HEIGHT
        self.fen_input.text_field.cursor_parent.scale = (
            self.fen_input.text_field.character_width,
            -Text.size * SHARED_FEN_TEXT_LINE_HEIGHT,
        )
        self.fen_input.text_field.highlight_color = color.rgba(1, 1, 1, 0.08)
        self.fen_input.text_field.x = -(self.FEN_INPUT_SCALE[0] / 2) + 0.01
        self.entities.append(self.fen_input)

        load_btn = Button(
            text="Load FEN",
            parent=camera.ui,
            scale=(0.11, 0.035),
            position=(x - 0.12, 0.02),
            z=0.3,
            color=color.gray,
            on_click=Func(self._load_from_field),
        )
        self.entities.append(load_btn)

        paste_btn = Button(
            text="Paste",
            parent=camera.ui,
            scale=(0.09, 0.035),
            position=(x, 0.02),
            z=0.3,
            color=color.gray,
            on_click=Func(self._paste_fen_from_clipboard),
        )
        self.entities.append(paste_btn)

        copy_btn = Button(
            text="Copy",
            parent=camera.ui,
            scale=(0.09, 0.035),
            position=(x + 0.11, 0.02),
            z=0.3,
            color=color.azure,
            on_click=Func(self._copy_fen),
        )
        self.entities.append(copy_btn)

        turn_label = Text(
            text="Side to move",
            parent=camera.ui,
            scale=0.92,
            position=(controls_center_x, -0.05),
            origin=(0, 0),
            z=0.3,
            color=color.white,
        )
        self.entities.append(turn_label)

        for index, (turn, label_text) in enumerate(((chess.WHITE, "White"), (chess.BLACK, "Black"))):
            btn = Button(
                text=label_text,
                parent=camera.ui,
                scale=(0.12, 0.04),
                position=(x - 0.06 + index * 0.14, -0.10),
                z=0.3,
                color=color.gray,
                on_click=Func(self._set_turn, turn),
            )
            self.turn_buttons[turn] = btn
            self.entities.append(btn)

        castling_label = Text(
            text="Castling",
            parent=camera.ui,
            scale=0.92,
            position=(controls_center_x, -0.16),
            origin=(0, 0),
            z=0.3,
            color=color.white,
        )
        self.entities.append(castling_label)

        for index, right in enumerate("KQkq"):
            btn = Button(
                text=right,
                parent=camera.ui,
                scale=(0.055, 0.04),
                position=(x - 0.15 + index * 0.08, -0.21),
                z=0.3,
                color=color.gray,
                on_click=Func(self._toggle_castling, right),
            )
            self.castling_buttons[right] = btn
            self.entities.append(btn)

        clear_castling_btn = Button(
            text="Clear",
            parent=camera.ui,
            scale=(0.09, 0.04),
            position=(x + 0.12, -0.16),
            z=0.3,
            color=color.gray,
            on_click=Func(self._clear_castling_rights),
        )
        self.entities.append(clear_castling_btn)

        ep_label = Text(
            text="En passant",
            parent=camera.ui,
            scale=0.88,
            position=(x - 0.13, -0.28),
            origin=(0, 0),
            z=0.3,
            color=color.white,
        )
        self.entities.append(ep_label)

        self.ep_input = InputField(
            default_value="-",
            parent=camera.ui,
            max_lines=1,
            character_limit=4,
            scale=(0.12, 0.04),
            position=(x - 0.13, -0.33),
            z=0.3,
            color=color.black66,
        )
        self.ep_input.text_field.x = -0.042
        self.entities.append(self.ep_input)

        halfmove_label = Text(
            text="Halfmove",
            parent=camera.ui,
            scale=0.88,
            position=(x + 0.01, -0.28),
            origin=(0, 0),
            z=0.3,
            color=color.white,
        )
        self.entities.append(halfmove_label)

        self.halfmove_input = InputField(
            default_value="0",
            parent=camera.ui,
            max_lines=1,
            character_limit=4,
            scale=(0.11, 0.04),
            position=(x + 0.01, -0.33),
            z=0.3,
            color=color.black66,
        )
        self.halfmove_input.text_field.x = -0.038
        self.entities.append(self.halfmove_input)

        fullmove_label = Text(
            text="Fullmove",
            parent=camera.ui,
            scale=0.88,
            position=(x + 0.13, -0.28),
            origin=(0, 0),
            z=0.3,
            color=color.white,
        )
        self.entities.append(fullmove_label)

        self.fullmove_input = InputField(
            default_value="1",
            parent=camera.ui,
            max_lines=1,
            character_limit=4,
            scale=(0.11, 0.04),
            position=(x + 0.13, -0.33),
            z=0.3,
            color=color.black66,
        )
        self.fullmove_input.text_field.x = -0.038
        self.entities.append(self.fullmove_input)

        reset_btn = Button(
            text="Standard",
            parent=camera.ui,
            scale=(0.12, 0.04),
            position=(x - 0.08, -0.39),
            z=0.3,
            color=color.gray,
            on_click=Func(self._reset_to_start_position),
        )
        self.entities.append(reset_btn)

        clear_btn = Button(
            text="Clear Board",
            parent=camera.ui,
            scale=(0.14, 0.04),
            position=(x + 0.10, -0.39),
            z=0.3,
            color=color.gray,
            on_click=Func(self._clear_board),
        )
        self.entities.append(clear_btn)

        start_btn = Button(
            text=self.submit_label,
            parent=camera.ui,
            scale=(0.14, 0.045),
            position=(x - 0.08, -0.45),
            z=0.3,
            color=color.azure,
            on_click=Func(self._submit),
        )
        self.entities.append(start_btn)

        back_btn = Button(
            text=self.back_label,
            parent=camera.ui,
            scale=(0.14, 0.045),
            position=(x + 0.10, -0.45),
            z=0.3,
            color=color.gray,
            on_click=Func(self._go_back),
        )
        self.entities.append(back_btn)

        self.status_text = Text(
            text="",
            parent=camera.ui,
            scale=0.86,
            position=(x, self.STATUS_Y),
            origin=(0, 0),
            z=0.3,
            color=color.rgb(1.0, 0.45, 0.45),
        )
        self.entities.append(self.status_text)

    def _square_to_ui(self, file_index: int, rank_index: int) -> tuple[float, float]:
        x = self.BOARD_ORIGIN_X + file_index * self.BOARD_SQUARE_SIZE
        y = self.BOARD_ORIGIN_Y - (7 - rank_index) * self.BOARD_SQUARE_SIZE
        return x, y

    def _piece_home_position(self, square: int):
        file_index = chess.square_file(square)
        rank_index = chess.square_rank(square)
        x, y = self._square_to_ui(file_index, rank_index)
        return x, y, 0.22

    def _refresh_board_pieces(self):
        for token in self.board_piece_tokens.values():
            if token in self.entities:
                self.entities.remove(token)
            destroy(token)
        self.board_piece_tokens.clear()

        for square, piece in self.board.piece_map().items():
            is_light = (chess.square_file(square) + chess.square_rank(square)) % 2 == 1
            token = _FenEditorPieceToken(
                self,
                piece.symbol(),
                self._piece_home_position(square),
                source_square=square,
                scale=(self.BOARD_SQUARE_SIZE * 0.96, self.BOARD_SQUARE_SIZE * 0.96),
                background_color=(
                    _rgba255(216, 204, 188, 92)
                    if is_light
                    else _rgba255(118, 94, 72, 92)
                ),
            )
            self.board_piece_tokens[square] = token
            self.entities.append(token)

    def _field_text(self, input_field: InputField | None) -> str:
        if not input_field:
            return ""
        return input_field.text_field.text.strip()

    @staticmethod
    def _normalize_fen_text(fen_text: str) -> str:
        text = fen_text.strip()
        if not text:
            return ""

        if "\n" not in text:
            return " ".join(text.split())

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""

        board_lines: list[str] = []
        extra_lines: list[str] = []
        rank_count = 0

        for line in lines:
            tokens = line.split()
            if not tokens:
                continue

            if rank_count < 8:
                board_chunk = tokens[0]
                board_lines.append(board_chunk)
                rank_count += board_chunk.count("/") + 1
                if len(tokens) > 1:
                    extra_lines.append(" ".join(tokens[1:]))
            else:
                extra_lines.append(" ".join(tokens))

        normalized = "/".join(board_lines)
        extra_text = " ".join(extra_lines).strip()
        if extra_text:
            normalized = f"{normalized} {extra_text}"
        return normalized.strip()

    def _fen_field_text(self) -> str:
        return self._normalize_fen_text(self._field_text(self.fen_input))

    def _set_fen_input_value(self, fen: str):
        self._set_input_value(self.fen_input, _format_fen_for_display(fen))

    def _set_input_value(self, input_field: InputField | None, value: str):
        if not input_field:
            return
        input_field.text = value

    def _current_castling_fen(self) -> str:
        rights = []
        if self.board.has_kingside_castling_rights(chess.WHITE):
            rights.append("K")
        if self.board.has_queenside_castling_rights(chess.WHITE):
            rights.append("Q")
        if self.board.has_kingside_castling_rights(chess.BLACK):
            rights.append("k")
        if self.board.has_queenside_castling_rights(chess.BLACK):
            rights.append("q")
        return "".join(rights) or "-"

    def _set_castling_fen(self, castling_fen: str):
        rights = castling_fen if castling_fen and castling_fen != "-" else "-"
        self.board.set_castling_fen(rights)

    def _sync_ui_from_board(self, *, update_fen_field: bool = True):
        self._refresh_board_pieces()

        for turn, button in self.turn_buttons.items():
            button.color = color.azure if self.board.turn == turn else color.gray

        castling_fen = self._current_castling_fen()
        for right, button in self.castling_buttons.items():
            button.color = color.azure if right in castling_fen else color.gray

        ep_text = chess.square_name(self.board.ep_square) if self.board.ep_square is not None else "-"
        self._set_input_value(self.ep_input, ep_text)
        self._set_input_value(self.halfmove_input, str(self.board.halfmove_clock))
        self._set_input_value(self.fullmove_input, str(max(1, self.board.fullmove_number)))

        if update_fen_field:
            fen = self.board.fen()
            self._synced_fen_text = fen
            self._set_fen_input_value(fen)

    def _load_fen(self, fen_text: str, *, show_status: bool = True) -> str | None:
        fen = self._normalize_fen_text(fen_text)
        if not fen:
            return "Please enter a FEN first."

        try:
            board = chess.Board(fen)
        except ValueError as exc:
            return f"Invalid FEN: {exc}"

        self.board = board
        self._sync_ui_from_board(update_fen_field=True)
        if show_status:
            self._set_status("FEN loaded.", duration=2.0)
        else:
            self._set_status("")
        return None

    def _apply_metadata_fields(self) -> str | None:
        ep_text = self._field_text(self.ep_input) or "-"
        halfmove_text = self._field_text(self.halfmove_input) or "0"
        fullmove_text = self._field_text(self.fullmove_input) or "1"

        try:
            halfmove = int(halfmove_text)
        except ValueError:
            return "Halfmove must be a number."
        if halfmove < 0:
            return "Halfmove must not be negative."

        try:
            fullmove = int(fullmove_text)
        except ValueError:
            return "Fullmove must be a number."
        if fullmove < 1:
            return "Fullmove must be at least 1."

        if ep_text == "-":
            self.board.ep_square = None
        else:
            try:
                self.board.ep_square = chess.parse_square(ep_text.lower())
            except ValueError:
                return "En passant must be '-' or a square like e3."

        self.board.halfmove_clock = halfmove
        self.board.fullmove_number = fullmove
        self._sync_ui_from_board(update_fen_field=True)
        return None

    def _load_from_field(self):
        error = self._load_fen(self._fen_field_text())
        if error:
            self._set_status(error)

    def _paste_fen_from_clipboard(self):
        if not self.fen_input:
            return

        try:
            pasted_text = pyperclip.paste()
        except Exception as exc:
            self._set_status(f"Clipboard access failed: {exc}")
            return

        pasted_text = (pasted_text or "").strip()
        if not pasted_text:
            self._set_status("Clipboard is empty.", duration=2.0)
            return

        self.fen_input.text = pasted_text
        self._load_from_field()

    def _copy_fen(self):
        fen, error = self._prepare_fen_for_export(require_valid=False)
        if error:
            self._set_status(error)
            return

        try:
            pyperclip.copy(fen)
        except Exception as exc:
            self._set_status(f"Clipboard access failed: {exc}")
            return

        self._set_status("FEN copied to clipboard.", duration=2.0)

    def _prepare_fen_for_export(self, *, require_valid: bool = True) -> tuple[str, str | None]:
        field_fen = self._fen_field_text()
        if field_fen and field_fen != self._synced_fen_text:
            error = self._load_fen(field_fen, show_status=False)
            if error:
                return "", error

        error = self._apply_metadata_fields()
        if error:
            return "", error

        if require_valid and not self.board.is_valid():
            return "", "Position is not valid for play."

        fen = self.board.fen()
        self._synced_fen_text = fen
        self._set_fen_input_value(fen)
        return fen, None

    def _submit(self):
        fen, error = self._prepare_fen_for_export()
        if error:
            duration = 2.0 if error == "Position is not valid for play." else None
            self._set_status(error, duration=duration)
            return

        submit_error = self.on_submit(fen) if self.on_submit else None
        if submit_error:
            self._set_status(submit_error)
            return

        self.destroy_panel()

    def _go_back(self):
        self.destroy_panel()
        if self.on_back:
            self.on_back()

    def _set_turn(self, turn: chess.Color):
        self.board.turn = turn
        self._sync_ui_from_board(update_fen_field=True)

    def _toggle_castling(self, right: str):
        rights = set(self._current_castling_fen().replace("-", ""))
        if right in rights:
            rights.remove(right)
        else:
            rights.add(right)
        ordered = "".join(flag for flag in "KQkq" if flag in rights)
        self._set_castling_fen(ordered)
        self._sync_ui_from_board(update_fen_field=True)

    def _clear_castling_rights(self):
        self._set_castling_fen("-")
        self._sync_ui_from_board(update_fen_field=True)

    def _normalize_castling_after_piece_edit(self):
        rights = []
        if self.board.piece_at(chess.E1) == chess.Piece(chess.KING, chess.WHITE):
            if self.board.piece_at(chess.H1) == chess.Piece(chess.ROOK, chess.WHITE):
                rights.append("K")
            if self.board.piece_at(chess.A1) == chess.Piece(chess.ROOK, chess.WHITE):
                rights.append("Q")
        if self.board.piece_at(chess.E8) == chess.Piece(chess.KING, chess.BLACK):
            if self.board.piece_at(chess.H8) == chess.Piece(chess.ROOK, chess.BLACK):
                rights.append("k")
            if self.board.piece_at(chess.A8) == chess.Piece(chess.ROOK, chess.BLACK):
                rights.append("q")
        self._set_castling_fen("".join(rights))

    def _handle_square_left_click(self, _square: int):
        self._set_status("Drag a piece from the palette or another square.", duration=2.0)

    def _handle_square_input(self, button: Button, square: int, key: str):
        if self._destroyed or not button.hovered or key != "right mouse down":
            return

        self._clear_square(square)

    def _clear_square(self, square: int):
        if self.board.piece_at(square) is None:
            self._set_status("Square is already empty.", duration=2.0)
            return

        self.board.remove_piece_at(square)
        self.board.ep_square = None
        self.board.halfmove_clock = 0
        self._normalize_castling_after_piece_edit()
        self._sync_ui_from_board(update_fen_field=True)

    def _square_from_position(self, position) -> int | None:
        x = float(position[0])
        y = float(position[1])
        left = self.BOARD_ORIGIN_X - (self.BOARD_SQUARE_SIZE / 2)
        top = self.BOARD_ORIGIN_Y + (self.BOARD_SQUARE_SIZE / 2)
        board_width = BOARD_SIZE * self.BOARD_SQUARE_SIZE
        board_height = BOARD_SIZE * self.BOARD_SQUARE_SIZE

        if x < left or x > left + board_width or y > top or y < top - board_height:
            return None

        file_index = int((x - left) / self.BOARD_SQUARE_SIZE)
        row_index = int((top - y) / self.BOARD_SQUARE_SIZE)
        if not (0 <= file_index < BOARD_SIZE and 0 <= row_index < BOARD_SIZE):
            return None

        rank_index = 7 - row_index
        return chess.square(file_index, rank_index)

    def _handle_piece_drop(self, token: _FenEditorPieceToken) -> bool:
        target_square = self._square_from_position(token.position)
        if target_square is None:
            return False

        piece = chess.Piece.from_symbol(token.piece_symbol)
        if token.source_square is not None and token.source_square != target_square:
            self.board.remove_piece_at(token.source_square)
        self.board.set_piece_at(target_square, piece)
        self.board.ep_square = None
        self.board.halfmove_clock = 0
        self._normalize_castling_after_piece_edit()
        self._sync_ui_from_board(update_fen_field=True)
        return True

    def _reset_to_start_position(self):
        error = self._load_fen(chess.STARTING_FEN)
        if error:
            self._set_status(error)

    def _clear_board(self):
        self.board = chess.Board(None)
        self.board.turn = chess.WHITE
        self.board.ep_square = None
        self.board.halfmove_clock = 0
        self.board.fullmove_number = 1
        self._set_castling_fen("-")
        self._sync_ui_from_board(update_fen_field=True)
        self._set_status("Board cleared.", duration=2.0)

    def destroy_panel(self):
        if self._destroyed:
            return

        self._destroyed = True
        self._status_generation += 1

        for entity in self.entities:
            destroy(entity)
        self.entities.clear()
        self.square_buttons.clear()
        self.board_piece_tokens.clear()
        self.palette_tokens.clear()
        self.turn_buttons.clear()
        self.castling_buttons.clear()
        self.fen_input = None
        self.ep_input = None
        self.halfmove_input = None
        self.fullmove_input = None
        self.status_text = None

        if self.on_destroy:
            self.on_destroy()


class SavedGamesDialog:
    """Overlay listing saved PGN files from the saved_games folder."""

    PAGE_SIZE = 5

    def __init__(self, files: list[Path], on_open, on_back):
        self.files = files
        self.on_open = on_open
        self.on_back = on_back
        self.page = 0
        self.entities: list[Entity] = []
        self.file_entities: list[Entity] = []
        self.page_text: Text | None = None
        self.empty_text: Text | None = None
        self.error_text: Text | None = None
        self.prev_button: Button | None = None
        self.next_button: Button | None = None
        self._build()

    def _build(self):
        bg = Entity(parent=camera.ui, model="quad", color=color.rgba(0, 0, 0, 0.7),
                     scale=(2, 2), z=0.5)
        self.entities.append(bg)

        panel = Entity(parent=camera.ui, model="quad", color=color.dark_gray,
                        scale=(0.86, 0.62), z=0.4)
        self.entities.append(panel)

        title = Text(text="Open Saved PGN", parent=camera.ui, scale=1.8,
                      position=(0, 0.22), origin=(0, 0), z=0.3, color=color.white)
        self.entities.append(title)

        folder_label = Text(
            text=f"Folder: {Path(PGN_DIR).name}",
            parent=camera.ui,
            scale=0.9,
            position=(0, 0.16),
            origin=(0, 0),
            z=0.3,
            color=color.light_gray,
        )
        self.entities.append(folder_label)

        self.page_text = Text(
            text="",
            parent=camera.ui,
            scale=0.9,
            position=(0, -0.20),
            origin=(0, 0),
            z=0.3,
            color=color.light_gray,
        )
        self.entities.append(self.page_text)

        self.error_text = Text(
            text="",
            parent=camera.ui,
            scale=0.9,
            position=(0, -0.27),
            origin=(0, 0),
            z=0.3,
            color=color.rgb(1.0, 0.45, 0.45),
        )
        self.entities.append(self.error_text)

        self.prev_button = Button(
            text="Prev",
            parent=camera.ui,
            scale=(0.12, 0.04),
            position=(-0.18, -0.34),
            z=0.3,
            color=color.gray,
            on_click=Func(self._change_page, -1),
        )
        self.entities.append(self.prev_button)

        self.next_button = Button(
            text="Next",
            parent=camera.ui,
            scale=(0.12, 0.04),
            position=(-0.04, -0.34),
            z=0.3,
            color=color.gray,
            on_click=Func(self._change_page, 1),
        )
        self.entities.append(self.next_button)

        back_btn = Button(
            text="Back",
            parent=camera.ui,
            scale=(0.16, 0.04),
            position=(0.16, -0.34),
            z=0.3,
            color=color.azure,
            on_click=Func(self._go_back),
        )
        self.entities.append(back_btn)

        self._refresh_page()

    def _change_page(self, delta: int):
        max_page = max(0, (len(self.files) - 1) // self.PAGE_SIZE)
        self.page = min(max(self.page + delta, 0), max_page)
        self._refresh_page()

    def _refresh_page(self):
        for entity in self.file_entities:
            destroy(entity)
        self.file_entities.clear()

        if self.error_text:
            self.error_text.text = ""

        page_count = max(1, (len(self.files) - 1) // self.PAGE_SIZE + 1)
        if self.page_text:
            self.page_text.text = f"Page {self.page + 1}/{page_count}"

        if not self.files:
            self.empty_text = Text(
                text="No saved PGN files found.",
                parent=camera.ui,
                scale=1.0,
                position=(0, 0.02),
                origin=(0, 0),
                z=0.3,
                color=color.white,
            )
            self.file_entities.append(self.empty_text)
        else:
            start = self.page * self.PAGE_SIZE
            page_files = self.files[start:start + self.PAGE_SIZE]
            for index, file_path in enumerate(page_files):
                button = Button(
                    text=self._format_file_label(file_path),
                    parent=camera.ui,
                    scale=(0.62, 0.05),
                    position=(0, 0.08 - index * 0.08),
                    z=0.3,
                    color=color.black66,
                    highlight_color=color.gray,
                    on_click=Func(self._open_file, file_path),
                )
                self.file_entities.append(button)

        self._set_nav_button_state(
            self.prev_button,
            enabled=self.page > 0,
            active_color=color.gray,
        )
        self._set_nav_button_state(
            self.next_button,
            enabled=(self.page + 1) * self.PAGE_SIZE < len(self.files),
            active_color=color.gray,
        )

    def _format_file_label(self, file_path: Path) -> str:
        name = file_path.name
        if len(name) <= 42:
            return name
        return f"{name[:39]}..."

    def _set_nav_button_state(self, button: Button | None, enabled: bool, active_color):
        if not button:
            return
        button.disabled = not enabled
        button.ignore_input = not enabled
        button.color = active_color if enabled else color.dark_gray

    def _open_file(self, file_path: Path):
        error = self.on_open(str(file_path)) if self.on_open else None
        if error:
            if self.error_text:
                self.error_text.text = _wrap_ui_text(error, 40)
            return

        self.destroy_panel()

    def _go_back(self):
        self.destroy_panel()
        if self.on_back:
            self.on_back()

    def destroy_panel(self):
        for e in self.file_entities:
            destroy(e)
        self.file_entities.clear()
        for e in self.entities:
            destroy(e)
        self.entities.clear()
        self.page_text = None
        self.empty_text = None
        self.error_text = None
        self.prev_button = None
        self.next_button = None


# ═══════════════════════════════════════════════════════════════════════════════
#  SETTINGS PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class SettingsPanel:
    """Overlay panel for engine / game settings."""

    def __init__(self, on_close, current_depth=DEFAULT_ENGINE_DEPTH,
                 current_skill=DEFAULT_SKILL_LEVEL,
                 current_time=DEFAULT_ENGINE_TIME):
        self.on_close = on_close
        self.depth = current_depth
        self.skill = current_skill
        self.move_time = current_time
        self.entities: list[Entity] = []
        self._build()

    def _build(self):
        # Backdrop
        bg = Entity(parent=camera.ui, model="quad", color=color.rgba(0, 0, 0, 0.7),
                     scale=(2, 2), z=0.5)
        self.entities.append(bg)

        # Panel background
        panel = Entity(parent=camera.ui, model="quad", color=color.dark_gray,
                        scale=(0.5, 0.45), z=0.4)
        self.entities.append(panel)

        title = Text(text="Settings", parent=camera.ui, scale=2,
                      position=(0, 0.18), origin=(0, 0), z=0.3, color=color.white)
        self.entities.append(title)

        # Skill Level slider
        skill_label = Text(text=f"Skill Level: {self.skill}", parent=camera.ui,
                           scale=1.2, position=(-0.2, 0.10), origin=(-0.5, 0),
                           z=0.3, color=color.white)
        self.entities.append(skill_label)

        skill_slider = Slider(min=0, max=20, default=self.skill,
                               parent=camera.ui, position=(-0.17, 0.06),
                               scale=(0.7, 0.7), z=0.3)
        skill_slider.step = 1
        skill_slider.on_value_changed = lambda: self._on_skill_change(skill_slider, skill_label)
        self.entities.append(skill_slider)
        self.skill_slider = skill_slider

        # Depth slider
        depth_label = Text(text=f"Search Depth: {self.depth}", parent=camera.ui,
                           scale=1.2, position=(-0.2, 0.00), origin=(-0.5, 0),
                           z=0.3, color=color.white)
        self.entities.append(depth_label)

        depth_slider = Slider(min=1, max=24, default=self.depth,
                               parent=camera.ui, position=(-0.17, -0.04),
                               scale=(0.7, 0.7), z=0.3)
        depth_slider.step = 1
        depth_slider.on_value_changed = lambda: self._on_depth_change(depth_slider, depth_label)
        self.entities.append(depth_slider)
        self.depth_slider = depth_slider

        # Move time slider
        time_label = Text(text=f"Move Time: {self.move_time:.1f}s", parent=camera.ui,
                          scale=1.2, position=(-0.2, -0.10), origin=(-0.5, 0),
                          z=0.3, color=color.white)
        self.entities.append(time_label)

        time_slider = Slider(min=0.5, max=10, default=self.move_time,
                              parent=camera.ui, position=(-0.17, -0.14),
                              scale=(0.7, 0.7), z=0.3)
        time_slider.step = 0.5
        time_slider.on_value_changed = lambda: self._on_time_change(time_slider, time_label)
        self.entities.append(time_slider)
        self.time_slider = time_slider

        # Close button
        close_btn = Button(text="Close", parent=camera.ui,
                            scale=(0.15, 0.04), position=(0, -0.20), z=0.3,
                            color=color.azure,
                            on_click=Func(self._close))
        self.entities.append(close_btn)

    def _on_skill_change(self, slider, label):
        self.skill = int(slider.value)
        label.text = f"Skill Level: {self.skill}"

    def _on_depth_change(self, slider, label):
        self.depth = int(slider.value)
        label.text = f"Search Depth: {self.depth}"

    def _on_time_change(self, slider, label):
        self.move_time = round(slider.value, 1)
        label.text = f"Move Time: {self.move_time:.1f}s"

    def _close(self):
        if self.on_close:
            self.on_close(self.skill, self.depth, self.move_time)
        self.destroy_panel()

    def destroy_panel(self):
        for e in self.entities:
            destroy(e)
        self.entities.clear()


# ═══════════════════════════════════════════════════════════════════════════════
#  COLOUR CHOOSER (for vs-engine)
# ═══════════════════════════════════════════════════════════════════════════════

class ColorChooser:
    """Popup: choose White or Black (engine mode)."""

    def __init__(self, on_choose, on_back=None):
        """on_choose(chess.WHITE or chess.BLACK)"""
        self.on_choose = on_choose
        self.on_back = on_back
        self.entities: list[Entity] = []
        self._build()

    def _build(self):
        bg = Entity(parent=camera.ui, model="quad", color=color.rgba(0, 0, 0, 0.7),
                     scale=(2, 2), z=0.5)
        self.entities.append(bg)

        t = Text(text="Play as…", parent=camera.ui, scale=2,
                  position=(0, 0.06), origin=(0, 0), z=0.3, color=color.white)
        self.entities.append(t)

        w = Button(text="White", parent=camera.ui, scale=(0.15, 0.05),
                    position=(-0.1, -0.02), z=0.3, color=color.white,
                    text_color=color.black,
                    on_click=Func(self._pick, chess.WHITE))
        self.entities.append(w)

        b = Button(text="Black", parent=camera.ui, scale=(0.15, 0.05),
                    position=(0.1, -0.02), z=0.3, color=color.rgb(0.2, 0.2, 0.2),
                    on_click=Func(self._pick, chess.BLACK))
        self.entities.append(b)

        back_btn = Button(text="Back", parent=camera.ui, scale=(0.14, 0.04),
                           position=(0, -0.11), z=0.3, color=color.gray,
                           on_click=Func(self._go_back))
        self.entities.append(back_btn)

    def _pick(self, c):
        self.destroy_panel()
        if self.on_choose:
            self.on_choose(c)

    def _go_back(self):
        self.destroy_panel()
        if self.on_back:
            self.on_back()

    def destroy_panel(self):
        for e in self.entities:
            destroy(e)
        self.entities.clear()


# ═══════════════════════════════════════════════════════════════════════════════
#  TIME CONTROL CHOOSER
# ═══════════════════════════════════════════════════════════════════════════════

class TimeControlChooser:
    """Popup: pick a time control before starting a game."""

    def __init__(self, on_choose, on_back=None):
        """on_choose(label: str)"""
        self.on_choose = on_choose
        self.on_back = on_back
        self.entities: list[Entity] = []
        self._build()

    def _build(self):
        bg = Entity(parent=camera.ui, model="quad", color=color.rgba(0, 0, 0, 0.7),
                     scale=(2, 2), z=0.5)
        self.entities.append(bg)

        t = Text(text="Time Control", parent=camera.ui, scale=2,
                  position=(0, 0.15), origin=(0, 0), z=0.3, color=color.white)
        self.entities.append(t)

        labels = list(TIME_CONTROLS.keys())
        for i, label in enumerate(labels):
            btn = Button(text=label, parent=camera.ui,
                          scale=(0.20, 0.045), position=(0, 0.06 - i * 0.055),
                          z=0.3, color=color.dark_gray,
                          on_click=Func(self._pick, label))
            self.entities.append(btn)

        back_btn = Button(text="Back", parent=camera.ui,
                           scale=(0.16, 0.04), position=(0, -0.25),
                           z=0.3, color=color.gray,
                           on_click=Func(self._go_back))
        self.entities.append(back_btn)

    def _pick(self, label):
        self.destroy_panel()
        if self.on_choose:
            self.on_choose(label)

    def _go_back(self):
        self.destroy_panel()
        if self.on_back:
            self.on_back()

    def destroy_panel(self):
        for e in self.entities:
            destroy(e)
        self.entities.clear()


# ═══════════════════════════════════════════════════════════════════════════════
#  PROMOTION DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class PromotionDialog:
    """Overlay for choosing a promotion piece or cancelling the move."""

    def __init__(self, is_white: bool, on_choose, on_cancel=None):
        """on_choose(chess.QUEEN / chess.ROOK / chess.BISHOP / chess.KNIGHT)"""
        self.on_choose = on_choose
        self.on_cancel = on_cancel
        self.entities: list[Entity] = []
        self._build(is_white)

    def _build(self, is_white):
        bg = Entity(parent=camera.ui, model="quad", color=color.rgba(0, 0, 0, 0.6),
                     scale=(2, 2), z=-0.2)
        self.entities.append(bg)

        pieces = [
            (chess.QUEEN, "Q" if is_white else "q"),
            (chess.ROOK, "R" if is_white else "r"),
            (chess.BISHOP, "B" if is_white else "b"),
            (chess.KNIGHT, "N" if is_white else "n"),
        ]
        from settings import PIECE_UNICODE

        t = Text(text="Promote to:", parent=camera.ui, scale=2,
                  position=(0, 0.06), origin=(0, 0), z=-0.3, color=color.white)
        self.entities.append(t)

        for i, (pt, sym) in enumerate(pieces):
            glyph = PIECE_UNICODE.get(sym, "?")
            btn = Button(
                text=glyph, parent=camera.ui,
                scale=(0.07, 0.07),
                position=(-0.12 + i * 0.08, -0.02),
                z=-0.3,
                color=color.dark_gray,
                text_color=color.white if is_white else color.rgb(0.15, 0.15, 0.15),
                on_click=Func(self._pick, pt),
            )
            btn.text_entity.font="DejaVuSans.ttf"
            self.entities.append(btn)

        back_btn = Button(
            text="Back",
            parent=camera.ui,
            scale=(0.18, 0.05),
            position=(0, -0.11),
            z=-0.3,
            color=color.gray,
            text_color=color.white,
            on_click=self._cancel,
        )
        self.entities.append(back_btn)

    def _pick(self, piece_type):
        self.destroy_panel()
        if self.on_choose:
            self.on_choose(piece_type)

    def _cancel(self):
        self.destroy_panel()
        if self.on_cancel:
            self.on_cancel()

    def destroy_panel(self):
        for e in self.entities:
            destroy(e)
        self.entities.clear()


# ═══════════════════════════════════════════════════════════════════════════════
#  MULTIPLAYER JOIN DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class JoinDialog:
    """Simple IP / port input dialog for joining a multiplayer game."""

    def __init__(self, on_join, on_cancel):
        """on_join(ip: str, port: int, name: str)"""
        self.on_join = on_join
        self.on_cancel = on_cancel
        self.entities: list[Entity] = []
        self._build()

    def _build(self):
        bg = Entity(parent=camera.ui, model="quad", color=color.rgba(0, 0, 0, 0.7),
                     scale=(2, 2), z=0.5)
        self.entities.append(bg)

        t = Text(text="Join Multiplayer", parent=camera.ui, scale=2,
                  position=(0, 0.15), origin=(0, 0), z=0.3, color=color.white)
        self.entities.append(t)

        # IP field
        ip_label = Text(text="Host IP:", parent=camera.ui, scale=1.2,
                         position=(-0.18, 0.08), origin=(-0.5, 0), z=0.3, color=color.white)
        self.entities.append(ip_label)
        self.ip_field = InputField(default_value="127.0.0.1", parent=camera.ui,
                                    scale=(0.25, 0.04), position=(0.06, 0.08), z=0.3)
        self.entities.append(self.ip_field)

        # Port field
        port_label = Text(text="Port:", parent=camera.ui, scale=1.2,
                           position=(-0.18, 0.02), origin=(-0.5, 0), z=0.3, color=color.white)
        self.entities.append(port_label)
        self.port_field = InputField(default_value="25565", parent=camera.ui,
                                      scale=(0.25, 0.04), position=(0.06, 0.02), z=0.3)
        self.entities.append(self.port_field)

        # Name field
        name_label = Text(text="Name:", parent=camera.ui, scale=1.2,
                           position=(-0.18, -0.04), origin=(-0.5, 0), z=0.3, color=color.white)
        self.entities.append(name_label)
        self.name_field = InputField(default_value="Guest", parent=camera.ui,
                                      scale=(0.25, 0.04), position=(0.06, -0.04), z=0.3)
        self.entities.append(self.name_field)

        # Buttons
        join_btn = Button(text="Join", parent=camera.ui, scale=(0.12, 0.04),
                           position=(-0.07, -0.12), z=0.3, color=color.azure,
                           on_click=Func(self._do_join))
        self.entities.append(join_btn)

        cancel_btn = Button(text="Cancel", parent=camera.ui, scale=(0.12, 0.04),
                             position=(0.07, -0.12), z=0.3, color=color.gray,
                             on_click=Func(self._do_cancel))
        self.entities.append(cancel_btn)

    def _do_join(self):
        ip = self.ip_field.text_field.text.strip() or "127.0.0.1"
        try:
            port = int(self.port_field.text_field.text.strip())
        except ValueError:
            port = 25565
        name = self.name_field.text_field.text.strip() or "Guest"
        self.destroy_panel()
        if self.on_join:
            self.on_join(ip, port, name)

    def _do_cancel(self):
        self.destroy_panel()
        if self.on_cancel:
            self.on_cancel()

    def destroy_panel(self):
        for e in self.entities:
            destroy(e)
        self.entities.clear()


# ═══════════════════════════════════════════════════════════════════════════════
#  HOST DIALOG (port input)
# ═══════════════════════════════════════════════════════════════════════════════

class HostDialog:
    """Simple port / name input for hosting."""

    def __init__(self, on_host, on_cancel):
        self.on_host = on_host
        self.on_cancel = on_cancel
        self.entities: list[Entity] = []
        self._build()

    def _build(self):
        bg = Entity(parent=camera.ui, model="quad", color=color.rgba(0, 0, 0, 0.7),
                     scale=(2, 2), z=0.5)
        self.entities.append(bg)

        t = Text(text="Host Multiplayer", parent=camera.ui, scale=2,
                  position=(0, 0.12), origin=(0, 0), z=0.3, color=color.white)
        self.entities.append(t)

        port_label = Text(text="Port:", parent=camera.ui, scale=1.2,
                           position=(-0.18, 0.05), origin=(-0.5, 0), z=0.3, color=color.white)
        self.entities.append(port_label)
        self.port_field = InputField(default_value="25565", parent=camera.ui,
                                      scale=(0.25, 0.04), position=(0.06, 0.05), z=0.3)
        self.entities.append(self.port_field)

        name_label = Text(text="Name:", parent=camera.ui, scale=1.2,
                           position=(-0.18, -0.01), origin=(-0.5, 0), z=0.3, color=color.white)
        self.entities.append(name_label)
        self.name_field = InputField(default_value="Host", parent=camera.ui,
                                      scale=(0.25, 0.04), position=(0.06, -0.01), z=0.3)
        self.entities.append(self.name_field)

        host_btn = Button(text="Start Hosting", parent=camera.ui,
                           scale=(0.18, 0.04), position=(-0.07, -0.09), z=0.3,
                           color=color.azure, on_click=Func(self._do_host))
        self.entities.append(host_btn)

        cancel_btn = Button(text="Cancel", parent=camera.ui,
                             scale=(0.12, 0.04), position=(0.1, -0.09), z=0.3,
                             color=color.gray, on_click=Func(self._do_cancel))
        self.entities.append(cancel_btn)

    def _do_host(self):
        try:
            port = int(self.port_field.text_field.text.strip())
        except ValueError:
            port = 25565
        name = self.name_field.text_field.text.strip() or "Host"
        self.destroy_panel()
        if self.on_host:
            self.on_host(port, name)

    def _do_cancel(self):
        self.destroy_panel()
        if self.on_cancel:
            self.on_cancel()

    def destroy_panel(self):
        for e in self.entities:
            destroy(e)
        self.entities.clear()


# ═══════════════════════════════════════════════════════════════════════════════
#  ENGINE DOWNLOAD DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class EngineDownloadDialog:
    """'Stockfish not found – download now?' dialog with progress."""

    def __init__(self, on_download, on_browse, on_skip):
        self.on_download = on_download
        self.on_browse = on_browse
        self.on_skip = on_skip
        self.entities: list[Entity] = []
        self.progress_text: Text | None = None
        self._build()

    def _build(self):
        bg = Entity(parent=camera.ui, model="quad", color=color.rgba(0, 0, 0, 0.7),
                     scale=(2, 2), z=0.5)
        self.entities.append(bg)

        t = Text(text="Stockfish not found.\nDownload now?", parent=camera.ui,
                  scale=1.5, position=(0, 0.08), origin=(0, 0), z=0.3, color=color.white)
        self.entities.append(t)

        self.progress_text = Text(text="", parent=camera.ui, scale=1.0,
                                    position=(0, 0.00), origin=(0, 0), z=0.3,
                                    color=color.yellow)
        self.entities.append(self.progress_text)

        dl_width = 0.15
        br_width = 0.15
        skip_width = 0.12
        button_gap = 0.03

        dl_btn = Button(text="Download", parent=camera.ui, scale=(dl_width, 0.04),
                         position=(-(dl_width + br_width) / 2 - button_gap, -0.07),
                         z=0.3, color=color.azure,
                         on_click=Func(self._download))
        self.entities.append(dl_btn)

        br_btn = Button(text="Browse…", parent=camera.ui, scale=(br_width, 0.04),
                         position=(0.0, -0.07), z=0.3, color=color.gray,
                         on_click=Func(self._browse))
        self.entities.append(br_btn)

        skip_btn = Button(text="Skip", parent=camera.ui, scale=(skip_width, 0.04),
                           position=((br_width + skip_width) / 2 + button_gap, -0.07),
                           z=0.3, color=color.dark_gray,
                           on_click=Func(self._skip))
        self.entities.append(skip_btn)

    def set_progress(self, msg: str):
        if self.progress_text:
            self.progress_text.text = msg

    def _download(self):
        if self.on_download:
            self.on_download()

    def _browse(self):
        self.destroy_panel()
        if self.on_browse:
            self.on_browse()

    def _skip(self):
        self.destroy_panel()
        if self.on_skip:
            self.on_skip()

    def destroy_panel(self):
        for e in self.entities:
            destroy(e)
        self.entities.clear()
        self.progress_text = None


# ═══════════════════════════════════════════════════════════════════════════════
#  IN-GAME HUD (clocks, status, move list, toolbar)
# ═══════════════════════════════════════════════════════════════════════════════

class GameHUD:
    """Right-side HUD showing clocks, status, move list, and action buttons."""

    FEN_PANEL_SCALE = SHARED_FEN_DISPLAY_SCALE
    FEN_PANEL_TOP_Y = -0.12
    FEN_PANEL_LEFT_PADDING = 0.01

    def __init__(self, callbacks: dict):
        """
        callbacks keys:
            undo, redo, resign, offer_draw, flip, fen, save_pgn,
            back_to_menu, restart
        """
        self.entities: list[Entity] = []
        self.action_buttons: list[Button] = []
        self.callbacks = callbacks

        # Text references for live updates
        self.status_text: Text | None = None
        self.white_clock_text: Text | None = None
        self.black_clock_text: Text | None = None
        self.move_list_text: Text | None = None
        self.eval_text: Text | None = None
        self._eval_clear_at: float | None = None
        self.fen_panel: Entity | None = None
        self.fen_text: Text | None = None
        self._fen_clear_at: float | None = None

        self._build()

    def _build(self):
        rx = 0.27   # right-side column x
        button_texture_configs = {
            "Undo": (UNDO_BUTTON_TEXTURE_PATH, UNDO_BUTTON_TEXTURE_NAME, 384 / 300),
            "Redo": (REDO_BUTTON_TEXTURE_PATH, REDO_BUTTON_TEXTURE_NAME, 384 / 300),
            "Flip": (FLIP_BUTTON_TEXTURE_PATH, FLIP_BUTTON_TEXTURE_NAME, 1.0),
            "Resign": (RESIGN_BUTTON_TEXTURE_PATH, RESIGN_BUTTON_TEXTURE_NAME, 1.0),
            "Draw": (DRAW_BUTTON_TEXTURE_PATH, DRAW_BUTTON_TEXTURE_NAME, 1.0),
            "FEN": (COPY_FEN_BUTTON_TEXTURE_PATH, COPY_FEN_BUTTON_TEXTURE_NAME, 1.0),
            "PGN": (SAVE_PGN_BUTTON_TEXTURE_PATH, SAVE_PGN_BUTTON_TEXTURE_NAME, 1.0),
            "Restart": (RESTART_BUTTON_TEXTURE_PATH, RESTART_BUTTON_TEXTURE_NAME, 1.0),
            "Menu": (MENU_BUTTON_TEXTURE_PATH, MENU_BUTTON_TEXTURE_NAME, 1.0),
        }

        # Status
        self.status_text = Text(
            text="White to move", parent=camera.ui, scale=1.2,
            position=(rx, 0.40), origin=(0, 0), color=color.white)
        self.entities.append(self.status_text)

        # Clocks
        self.black_clock_text = Text(
            text="Black: --:--", parent=camera.ui, scale=1.1,
            position=(rx, 0.35), origin=(0, 0), color=color.light_gray)
        self.entities.append(self.black_clock_text)

        self.white_clock_text = Text(
            text="White: --:--", parent=camera.ui, scale=1.1,
            position=(rx, -0.35), origin=(0, 0), color=color.light_gray)
        self.entities.append(self.white_clock_text)

        # Eval display
        self.eval_text = Text(
            text="", parent=camera.ui, scale=1.0,
            position=(rx, 0.30), origin=(0, 0), color=color.yellow)
        self.entities.append(self.eval_text)

        # Move list (scrollable text)
        self.move_list_text = Text(
            text="Moves:\n", parent=camera.ui, scale=0.8,
            position=(rx - 0.11, 0.25), origin=(-0.5, 0.5),
            color=color.smoke, wordwrap=30)
        self.entities.append(self.move_list_text)

        # Temporary FEN display beside the board
        self.fen_panel = Entity(
            parent=camera.ui,
            model="quad",
            color=color.rgba(0, 0, 0, 0.70),
            scale=self.FEN_PANEL_SCALE,
            enabled=False,
            z=-0.02,
        )
        self.entities.append(self.fen_panel)

        self.fen_text = Text(
            text=" ",
            parent=camera.ui,
            scale=0.5,
            origin=(-0.5, 0.5),
            color=color.white,
            enabled=False,
            z=-0.03,
        )
        self.fen_text.text = ""
        self.entities.append(self.fen_text)

        # Toolbar buttons
        btn_defs = [
            ("Undo",     self.callbacks.get("undo")),
            ("Redo",     self.callbacks.get("redo")),
            ("Flip",     self.callbacks.get("flip")),
            ("Resign",   self.callbacks.get("resign")),
            ("Draw",     self.callbacks.get("offer_draw")),
            ("FEN",      self.callbacks.get("fen")),
            ("PGN",      self.callbacks.get("save_pgn")),
            ("Restart",  self.callbacks.get("restart")),
            ("Menu",     self.callbacks.get("back_to_menu")),
        ]
        bx = rx - 0.11
        for i, (label, cb) in enumerate(btn_defs):
            texture_name = None
            texture_aspect = None
            texture_config = button_texture_configs.get(label)
            if texture_config and texture_config[0].exists():
                _, texture_name, texture_aspect = texture_config
            btn = Button(
                text="" if texture_name else label, parent=camera.ui,
                scale=(0.07, 0.03),
                position=(bx + (i % 4) * 0.075, -0.40 - (i // 4) * 0.04),
                color=color.dark_gray,
                highlight_color=color.gray,
                on_click=cb if cb else Func(print, label),
            )
            if texture_name:
                self._add_button_icon(btn, texture_name, texture_aspect)
            self.entities.append(btn)
            self.action_buttons.append(btn)

    def _add_button_icon(self, button: Button, texture_name: str, texture_aspect: float):
        button_aspect = button.scale_x / button.scale_y
        icon_scale_x = BUTTON_ICON_HEIGHT * (texture_aspect / button_aspect)
        icon = Entity(
            parent=button,
            model="quad",
            texture=texture_name,
            color=color.white,
            scale=(icon_scale_x, BUTTON_ICON_HEIGHT),
            position=(0, 0, -0.01),
        )
        icon.collision = False
        icon.ignore_input = True

    # ── Live updates ──────────────────────────────────────────────────────────

    def update_status(self, text: str):
        if self.status_text:
            self.status_text.text = text

    def update_clocks(
        self,
        white_str: str,
        black_str: str,
        white_label: str = "White",
        black_label: str = "Black",
    ):
        if self.white_clock_text:
            self.white_clock_text.text = f"{white_label}: {white_str}"
        if self.black_clock_text:
            self.black_clock_text.text = f"{black_label}: {black_str}"

    def update_move_list(self, moves: list[str]):
        if not self.move_list_text:
            return
        lines = []
        for i in range(0, len(moves), 2):
            num = i // 2 + 1
            white_m = moves[i]
            black_m = moves[i + 1] if i + 1 < len(moves) else ""
            lines.append(f"{num}. {white_m}  {black_m}")
        # Keep last ~16 moves visible
        visible = lines[-16:]
        self.move_list_text.text = "Moves:\n" + "\n".join(visible)

    def update_eval(self, text: str, duration: float | None = None):
        if not self.eval_text:
            return
        self.eval_text.text = text
        if text and duration is not None:
            self._eval_clear_at = monotonic() + max(0.0, duration)
        else:
            self._eval_clear_at = None

    def show_fen(self, fen: str, duration: float = 10.0, copied_to_clipboard: bool = True):
        if not self.fen_panel or not self.fen_text:
            return
        headline = "FEN copied" if copied_to_clipboard else "FEN"
        self.fen_text.text = f"{headline}\n{_format_fen_for_display(fen)}"
        self.fen_panel.enabled = True
        self.fen_text.enabled = True
        self._fen_clear_at = monotonic() + max(0.0, duration)

    def clear_fen(self):
        if self.fen_panel:
            self.fen_panel.enabled = False
        if self.fen_text:
            self.fen_text.text = ""
            self.fen_text.enabled = False
        self._fen_clear_at = None

    def update_board_anchor(self, board_view):
        if not self.fen_panel or not self.fen_text or not self.move_list_text:
            return

        move_left_x = self.move_list_text.position[0] - 0.01
        panel_width, panel_height = self.FEN_PANEL_SCALE
        panel_x = move_left_x + (panel_width / 2)
        panel_y = self.FEN_PANEL_TOP_Y - (panel_height / 2)

        self.fen_panel.position = (panel_x, panel_y, -0.02)
        self.fen_text.position = (
            move_left_x + self.FEN_PANEL_LEFT_PADDING,
            self.FEN_PANEL_TOP_Y - 0.005,
            -0.03,
        )

    def tick(self):
        if (
            self.eval_text
            and self._eval_clear_at is not None
            and monotonic() >= self._eval_clear_at
        ):
            self.eval_text.text = ""
            self._eval_clear_at = None
        if self._fen_clear_at is not None and monotonic() >= self._fen_clear_at:
            self.clear_fen()

    def set_input_enabled(self, enabled: bool):
        """Enable or disable toolbar buttons without hiding the HUD."""
        for btn in self.action_buttons:
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

    # ── Visibility ────────────────────────────────────────────────────────────

    def show(self):
        for e in self.entities:
            e.enabled = True

    def hide(self):
        for e in self.entities:
            e.enabled = False

    def destroy(self):
        for e in self.entities:
            destroy(e)
        self.entities.clear()


# ═══════════════════════════════════════════════════════════════════════════════
#  RESULT BANNER
# ═══════════════════════════════════════════════════════════════════════════════

class ResultBanner:
    """Large overlay announcing game result."""

    def __init__(self, text_str: str, on_dismiss):
        self.entities: list[Entity] = []
        overlay_bg_z = -0.2
        overlay_fg_z = -0.3
        bg = Entity(parent=camera.ui, model="quad", color=color.rgba(0, 0, 0, 0.65),
                     scale=(2, 2), z=overlay_bg_z)
        self.entities.append(bg)
        t = Text(text=text_str, parent=camera.ui, scale=2.2,
                  position=(0, 0.04), origin=(0, 0), z=overlay_fg_z, color=color.white)
        self.entities.append(t)
        btn = Button(text="OK", parent=camera.ui, scale=(0.12, 0.04),
                      position=(0, -0.06), z=overlay_fg_z, color=color.azure,
                      on_click=Func(self._dismiss, on_dismiss))
        self.entities.append(btn)

    def _dismiss(self, cb):
        self.destroy_panel()
        if cb:
            cb()

    def destroy_panel(self):
        for e in self.entities:
            destroy(e)
        self.entities.clear()


class ConfirmBanner:
    """Large overlay asking the player to confirm or decline an action."""

    def __init__(
        self,
        text_str: str,
        on_confirm,
        on_cancel,
        confirm_text: str = "Accept",
        cancel_text: str = "Decline",
    ):
        self.entities: list[Entity] = []
        overlay_bg_z = -0.2
        overlay_fg_z = -0.3
        bg = Entity(parent=camera.ui, model="quad", color=color.rgba(0, 0, 0, 0.65),
                    scale=(2, 2), z=overlay_bg_z)
        self.entities.append(bg)
        t = Text(text=text_str, parent=camera.ui, scale=2.0,
                 position=(0, 0.06), origin=(0, 0), z=overlay_fg_z, color=color.white)
        self.entities.append(t)
        confirm_btn = Button(text=confirm_text, parent=camera.ui, scale=(0.16, 0.04),
                             position=(-0.09, -0.08), z=overlay_fg_z, color=color.azure,
                             on_click=Func(self._dismiss, on_confirm))
        self.entities.append(confirm_btn)
        cancel_btn = Button(text=cancel_text, parent=camera.ui, scale=(0.16, 0.04),
                            position=(0.09, -0.08), z=overlay_fg_z, color=color.gray,
                            on_click=Func(self._dismiss, on_cancel))
        self.entities.append(cancel_btn)

    def _dismiss(self, cb):
        self.destroy_panel()
        if cb:
            cb()

    def destroy_panel(self):
        for e in self.entities:
            destroy(e)
        self.entities.clear()
