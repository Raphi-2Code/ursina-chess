"""
network_manager.py – Multiplayer networking using ursina.networking (RPCPeer).

Host-authoritative model:
  • Host maintains the canonical board state and validates every move.
  • Client sends move *requests*; host accepts or rejects.
  • State is synchronised via FEN + last-move + clocks + status.

RPC message catalogue
  hello           – client → host (player name)
  assign_color    – host → client (color, host_name)
  sync_state      – host → client (FEN, last_move_uci, w_clock, b_clock, status, move_list_csv)
  request_move    – client → host (uci_move)
  move_accepted   – host → client (uci_move, san)
  move_rejected   – host → client (reason)
  offer_takeback  – either → other
  takeback_response – either → other (accepted: bool)
  offer_draw      – either → other
  draw_response   – either → other (accepted: bool)
  resign_msg      – either → other (color_int)
  ping            – client → host (just for keep-alive)
"""

import chess
import time
from typing import Optional, Callable

from ursina.networking import RPCPeer, rpc

from settings import DEFAULT_HOST, DEFAULT_PORT


class NetworkManager:
    """
    Thin wrapper around RPCPeer that exposes chess-specific RPCs.

    Usage
    -----
    nm = NetworkManager()
    nm.host(port=25565, player_name='Alice')   # host side
    nm.join(ip='1.2.3.4', port=25565, name='Bob')  # client side

    Every frame, call  nm.update().
    """

    def __init__(self):
        self.peer: Optional[RPCPeer] = None
        self.is_host_flag: bool = False
        self.connected: bool = False
        self.player_name: str = "Player"

        # Assigned colour (set after handshake)
        self.my_color: Optional[chess.Color] = None

        # Callbacks the UI / main loop should set
        self.on_connected: Optional[Callable] = None          # ()
        self.on_disconnected: Optional[Callable] = None       # ()
        self.on_state_synced: Optional[Callable] = None       # (fen, last_uci, w_clock, b_clock, status, move_list)
        self.on_color_assigned: Optional[Callable] = None     # (color, opponent_name)
        self.on_move_accepted: Optional[Callable] = None      # (uci, san)
        self.on_move_rejected: Optional[Callable] = None      # (reason)
        self.on_takeback_offered: Optional[Callable] = None   # ()
        self.on_takeback_response: Optional[Callable] = None  # (accepted)
        self.on_draw_offered: Optional[Callable] = None       # ()
        self.on_draw_response: Optional[Callable] = None      # (accepted)
        self.on_opponent_resigned: Optional[Callable] = None  # (color_int)

        # Internal: host keeps a reference to the client connection
        self._client_conn = None
        # Internal: client keeps host connection
        self._host_conn = None

        # Host-side board reference (set by main after new_game)
        self.host_board: Optional[chess.Board] = None

    # ── Setup ─────────────────────────────────────────────────────────────────
    def host(self, port: int = DEFAULT_PORT, player_name: str = "Host"):
        """Start hosting a game."""
        self._setup_peer()
        self.is_host_flag = True
        self.player_name = player_name
        self.my_color = chess.WHITE
        try:
            self.peer.start("0.0.0.0", port, is_host=True)
            print(f"[Net] Hosting on port {port}")
        except Exception as e:
            print(f"[Net] Failed to host: {e}")

    def join(self, ip: str = "127.0.0.1", port: int = DEFAULT_PORT,
             player_name: str = "Guest"):
        """Join a hosted game."""
        self._setup_peer()
        self.is_host_flag = False
        self.player_name = player_name
        try:
            self.peer.start(ip, port, is_host=False)
            print(f"[Net] Connecting to {ip}:{port}")
        except Exception as e:
            print(f"[Net] Failed to connect: {e}")

    def stop(self):
        if self.peer:
            try:
                self.peer.stop()
            except Exception:
                pass
        self.peer = None
        self.connected = False
        self._client_conn = None
        self._host_conn = None

    def update(self):
        if self.peer:
            self.peer.update()

    @property
    def is_hosting(self) -> bool:
        return self.is_host_flag

    @property
    def is_running(self) -> bool:
        return self.peer is not None and self.peer.is_running()

    # ── Outgoing RPCs (called by UI / game logic) ────────────────────────────

    def send_move_request(self, uci: str):
        """Client sends a move request to the host."""
        conn = self._host_conn
        if conn and self.peer:
            print(f"[Net] -> request_move {uci}")
            self.peer.request_move(conn, uci)

    def send_state_sync(self, fen: str, last_uci: str,
                        w_clock: float, b_clock: float,
                        status: str, move_list_csv: str):
        """Host broadcasts state to client."""
        conn = self._client_conn
        if conn and self.peer:
            move_count = len(move_list_csv.split(",")) if move_list_csv else 0
            print(f"[Net] -> sync_state last={last_uci or '-'} moves={move_count} status={status}")
            self.peer.sync_state(conn, fen, last_uci,
                                 w_clock, b_clock, status, move_list_csv)

    def send_move_accepted(self, uci: str, san: str):
        conn = self._client_conn
        if conn and self.peer:
            print(f"[Net] -> move_accepted {uci} ({san})")
            self.peer.move_accepted(conn, uci, san)

    def send_move_rejected(self, reason: str):
        conn = self._client_conn
        if conn and self.peer:
            print(f"[Net] -> move_rejected {reason}")
            self.peer.move_rejected(conn, reason)

    def send_offer_draw(self):
        conn = self._client_conn if self.is_host_flag else self._host_conn
        if conn and self.peer:
            self.peer.offer_draw(conn)

    def send_offer_takeback(self):
        conn = self._client_conn if self.is_host_flag else self._host_conn
        if conn and self.peer:
            self.peer.offer_takeback(conn)

    def send_takeback_response(self, accepted: bool):
        conn = self._client_conn if self.is_host_flag else self._host_conn
        if conn and self.peer:
            self.peer.takeback_response(conn, accepted)

    def send_draw_response(self, accepted: bool):
        conn = self._client_conn if self.is_host_flag else self._host_conn
        if conn and self.peer:
            self.peer.draw_response(conn, accepted)

    def send_resign(self, color: int):
        conn = self._client_conn if self.is_host_flag else self._host_conn
        if conn and self.peer:
            self.peer.resign_msg(conn, color)

    def send_ping(self):
        conn = self._host_conn
        if conn and self.peer:
            self.peer.ping(conn)

    # ── Internal setup ────────────────────────────────────────────────────────

    def _setup_peer(self):
        """Create a fresh RPCPeer and register all RPC functions."""
        self.stop()
        self.peer = RPCPeer()
        self.peer.print_connect = False
        self.peer.print_disconnect = False
        self._register_rpcs()

    def _register_rpcs(self):
        """Register all RPC handlers on self.peer."""
        peer = self.peer
        nm = self   # capture reference for closures

        # ── on_connect / on_disconnect ────────────────────────────────────
        @rpc(peer)
        def on_connect(connection, time_connected):
            if nm.is_host_flag:
                # A client connected
                nm._client_conn = connection
                nm.connected = True
                print("[Net] Client connected")
            else:
                # We connected to host
                nm._host_conn = connection
                nm.connected = True
                print("[Net] Connected to host")
                # Send hello
                peer.hello(connection, nm.player_name)

            if nm.on_connected:
                nm.on_connected()

        @rpc(peer)
        def on_disconnect(connection, time_disconnected):
            nm.connected = False
            nm._client_conn = None
            nm._host_conn = None
            print("[Net] Disconnected")
            if nm.on_disconnected:
                nm.on_disconnected()

        # ── hello (client → host) ────────────────────────────────────────
        @rpc(peer)
        def hello(connection, time_received, name: str):
            if nm.is_host_flag:
                print(f"[Net] Client says hello: {name}")
                # Assign black to the client
                peer.assign_color(connection, 0, nm.player_name)  # 0 = BLACK
                # Also trigger callback so host can sync state
                nm.my_color = chess.WHITE
                if nm.on_color_assigned:
                    nm.on_color_assigned(chess.WHITE, name)

        # ── assign_color (host → client) ─────────────────────────────────
        @rpc(peer)
        def assign_color(connection, time_received, color_int: int, host_name: str):
            if not nm.is_host_flag:
                nm.my_color = chess.Color(color_int)   # 0=BLACK, 1=WHITE
                print(f"[Net] Assigned colour: {'White' if color_int else 'Black'}")
                if nm.on_color_assigned:
                    nm.on_color_assigned(chess.Color(color_int), host_name)

        # ── sync_state (host → client) ───────────────────────────────────
        @rpc(peer)
        def sync_state(connection, time_received,
                       fen: str, last_uci: str,
                       w_clock: float, b_clock: float,
                       status: str, move_list_csv: str):
            if not nm.is_host_flag:
                move_count = len(move_list_csv.split(",")) if move_list_csv else 0
                print(f"[Net] <- sync_state last={last_uci or '-'} moves={move_count} status={status}")
                if nm.on_state_synced:
                    nm.on_state_synced(fen, last_uci, w_clock, b_clock,
                                       status, move_list_csv)

        # ── request_move (client → host) ─────────────────────────────────
        @rpc(peer)
        def request_move(connection, time_received, uci: str):
            if nm.is_host_flag and nm.host_board:
                try:
                    print(f"[Net] <- request_move {uci}")
                    move = chess.Move.from_uci(uci)
                    if move in nm.host_board.legal_moves:
                        san = nm.host_board.san(move)
                        nm.host_board.push(move)
                        peer.move_accepted(connection, uci, san)
                        if nm.on_move_accepted:
                            nm.on_move_accepted(uci, san)
                    else:
                        peer.move_rejected(connection, "Illegal move")
                except Exception as e:
                    peer.move_rejected(connection, str(e))

        # ── move_accepted (host → client) ────────────────────────────────
        @rpc(peer)
        def move_accepted(connection, time_received, uci: str, san: str):
            if not nm.is_host_flag:
                print(f"[Net] <- move_accepted {uci} ({san})")
                if nm.on_move_accepted:
                    nm.on_move_accepted(uci, san)

        # ── move_rejected (host → client) ────────────────────────────────
        @rpc(peer)
        def move_rejected(connection, time_received, reason: str):
            if not nm.is_host_flag:
                print(f"[Net] <- move_rejected {reason}")
                if nm.on_move_rejected:
                    nm.on_move_rejected(reason)

        # ── offer_takeback ────────────────────────────────────────────────
        @rpc(peer)
        def offer_takeback(connection, time_received):
            if nm.on_takeback_offered:
                nm.on_takeback_offered()

        # ── takeback_response ─────────────────────────────────────────────
        @rpc(peer)
        def takeback_response(connection, time_received, accepted: bool):
            if nm.on_takeback_response:
                nm.on_takeback_response(accepted)

        # ── offer_draw ────────────────────────────────────────────────────
        @rpc(peer)
        def offer_draw(connection, time_received):
            if nm.on_draw_offered:
                nm.on_draw_offered()

        # ── draw_response ─────────────────────────────────────────────────
        @rpc(peer)
        def draw_response(connection, time_received, accepted: bool):
            if nm.on_draw_response:
                nm.on_draw_response(accepted)

        # ── resign_msg ────────────────────────────────────────────────────
        @rpc(peer)
        def resign_msg(connection, time_received, color_int: int):
            if nm.on_opponent_resigned:
                nm.on_opponent_resigned(color_int)

        # ── ping ──────────────────────────────────────────────────────────
        @rpc(peer)
        def ping(connection, time_received):
            pass  # keep-alive, no action needed
