from __future__ import annotations

import unittest

import chess

from game_state import GameState


class GameStateTests(unittest.TestCase):
    def test_sync_remote_state_preserves_time_control_and_starting_fen(self):
        gs = GameState()
        starting_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        board = chess.Board(starting_fen)
        board.push_san("c5")

        gs.sync_remote_state(
            board.fen(),
            starting_fen=starting_fen,
            time_control="5+3",
            white_clock=300.0,
            black_clock=298.4,
            move_list=["c5"],
            clear_premove=False,
        )
        gs.last_move = chess.Move.from_uci("c7c5")

        self.assertEqual(gs.fen, board.fen())
        self.assertEqual(gs.starting_fen, starting_fen)
        self.assertEqual(gs.time_control_label, "5+3")
        self.assertEqual(gs.base_time, 300.0)
        self.assertEqual(gs.increment, 3.0)
        self.assertEqual(gs.white_clock, 300.0)
        self.assertEqual(gs.black_clock, 298.4)
        self.assertTrue(gs.clock_running)
        self.assertEqual(gs.move_list, ["c5"])
        self.assertEqual(gs.last_move, chess.Move.from_uci("c7c5"))

    def test_sync_remote_state_restores_host_result_reason(self):
        gs = GameState()
        board = chess.Board()
        board.push_san("f3")
        board.push_san("e5")
        board.push_san("g4")
        board.push_san("Qh4#")

        gs.sync_remote_state(
            board.fen(),
            starting_fen=chess.STARTING_FEN,
            time_control="1+0",
            white_clock=0.0,
            black_clock=42.0,
            move_list=["f3", "e5", "g4", "Qh4#"],
            result="0-1",
            clear_premove=False,
        )

        self.assertEqual(gs.result, "0-1")
        self.assertFalse(gs.clock_running)


if __name__ == "__main__":
    unittest.main()
