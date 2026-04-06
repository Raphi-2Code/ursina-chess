from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from benchmark_manager import (
    build_leaderboard,
    import_benchmark_game,
    load_benchmark_games,
    load_benchmark_snapshot,
    validate_benchmark_import,
)


WHITE_WIN_PGN = """
[Event "LLM Benchmark"]
[White "GPT-5.4"]
[Black "Grok 4.20"]
[Result "1-0"]

1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0
"""


WHITE_WIN_PGN_ALT = """
[Event "LLM Benchmark"]
[White "GPT-5.4"]
[Black "Grok 4.20"]
[Result "1-0"]

1. d4 d5 2. e4 dxe4 3. Nc3 Nf6 4. f3 exf3 5. Nxf3 Bg4 6. h3 Bxf3 7. Qxf3 c6 8. Be3 e6 9. Bd3 Be7 10. O-O O-O 11. Qg3 Nd5 12. Nxd5 cxd5 13. Bh6 Bf6 14. Rxf6 Qxf6 15. Bg5 Qxd4+ 16. Be3 Qxb2 17. Rf1 Nc6 18. Qh4 g6 19. Rf6 Qa1+ 20. Kh2 Qe5+ 21. Bf4 Qd4 22. Bg5 Qe5+ 23. Bf4 Qd4 24. Bg5 1-0
"""


BLACK_WIN_PGN = """
[Event "LLM Benchmark"]
[White "GPT-5.4"]
[Black "Grok 4.20"]
[Result "0-1"]

1. f3 e5 2. g4 Qh4# 0-1
"""


DRAW_PGN = """
[Event "LLM Benchmark"]
[White "GPT-5.4"]
[Black "Claude 4.1"]
[Result "1/2-1/2"]

1. Nf3 Nf6 1/2-1/2
"""


class BenchmarkManagerTests(unittest.TestCase):
    def test_imports_single_game_and_rebuilds_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            benchmark_path = Path(temp_dir) / "llm_benchmark.pgn"

            record = import_benchmark_game(WHITE_WIN_PGN, path=benchmark_path)
            snapshot = load_benchmark_snapshot(benchmark_path)

            self.assertEqual(record.index, 1)
            self.assertEqual(len(snapshot.games), 1)
            self.assertEqual(snapshot.games[0].white, "GPT-5.4")
            self.assertEqual(snapshot.games[0].black, "Grok 4.20")
            self.assertEqual(snapshot.games[0].result, "1-0")
            self.assertEqual(len(snapshot.leaderboard), 2)

    def test_loads_multiple_games_in_import_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            benchmark_path = Path(temp_dir) / "llm_benchmark.pgn"

            import_benchmark_game(WHITE_WIN_PGN, path=benchmark_path)
            import_benchmark_game(DRAW_PGN, path=benchmark_path)
            games = load_benchmark_games(benchmark_path)

            self.assertEqual(len(games), 2)
            self.assertEqual(games[0].index, 1)
            self.assertEqual(games[1].index, 2)
            self.assertEqual(games[1].black, "Claude 4.1")

    def test_rejects_missing_result(self):
        missing_result = WHITE_WIN_PGN.replace('[Result "1-0"]', '[Result "*"]').replace("1-0", "*", 1)
        with self.assertRaisesRegex(ValueError, "final result"):
            validate_benchmark_import(missing_result)

    def test_rejects_missing_white_name(self):
        missing_white = WHITE_WIN_PGN.replace('[White "GPT-5.4"]', '[White ""]')
        with self.assertRaisesRegex(ValueError, "White player name"):
            validate_benchmark_import(missing_white)

    def test_rejects_missing_black_name(self):
        missing_black = WHITE_WIN_PGN.replace('[Black "Grok 4.20"]', '[Black ""]')
        with self.assertRaisesRegex(ValueError, "Black player name"):
            validate_benchmark_import(missing_black)

    def test_rejects_identical_model_names(self):
        same_names = WHITE_WIN_PGN.replace('[Black "Grok 4.20"]', '[Black "GPT-5.4"]')
        with self.assertRaisesRegex(ValueError, "different model names"):
            validate_benchmark_import(same_names)

    def test_rejects_duplicate_import(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            benchmark_path = Path(temp_dir) / "llm_benchmark.pgn"

            import_benchmark_game(WHITE_WIN_PGN, path=benchmark_path)
            with self.assertRaisesRegex(ValueError, "already been imported"):
                import_benchmark_game(WHITE_WIN_PGN, path=benchmark_path)

    def test_expected_win_changes_rating_less_than_repeat_upset(self):
        first_snapshot = build_leaderboard(load_benchmark_games_from_texts(WHITE_WIN_PGN))
        second_snapshot = build_leaderboard(load_benchmark_games_from_texts(WHITE_WIN_PGN, WHITE_WIN_PGN_ALT))
        upset_snapshot = build_leaderboard(load_benchmark_games_from_texts(WHITE_WIN_PGN, BLACK_WIN_PGN))

        first_ratings = {entry.model: entry.rating for entry in first_snapshot}
        second_ratings = {entry.model: entry.rating for entry in second_snapshot}
        upset_ratings = {entry.model: entry.rating for entry in upset_snapshot}

        repeated_expected_gain = second_ratings["GPT-5.4"] - first_ratings["GPT-5.4"]
        upset_gain = upset_ratings["Grok 4.20"] - first_ratings["Grok 4.20"]

        self.assertLess(repeated_expected_gain, 16.0)
        self.assertGreater(upset_gain, 16.0)

    def test_draw_between_unequal_models_helps_lower_rated_side(self):
        snapshot = build_leaderboard(load_benchmark_games_from_texts(WHITE_WIN_PGN, DRAW_PGN))
        ratings = {entry.model: entry.rating for entry in snapshot}

        self.assertLess(ratings["GPT-5.4"], 1216.0)
        self.assertGreater(ratings["Claude 4.1"], 1200.0)

    def test_rebuild_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            benchmark_path = Path(temp_dir) / "llm_benchmark.pgn"

            import_benchmark_game(WHITE_WIN_PGN, path=benchmark_path)
            import_benchmark_game(DRAW_PGN, path=benchmark_path)

            first = load_benchmark_snapshot(benchmark_path)
            second = load_benchmark_snapshot(benchmark_path)

            self.assertEqual(
                [(entry.model, round(entry.rating, 6)) for entry in first.leaderboard],
                [(entry.model, round(entry.rating, 6)) for entry in second.leaderboard],
            )


def load_benchmark_games_from_texts(*games: str):
    records = []
    for index, pgn_text in enumerate(games, start=1):
        records.append(validate_benchmark_import(pgn_text, existing_games=records))
        records[-1].index = index
    return records


if __name__ == "__main__":
    unittest.main()
