"""
benchmark_manager.py - Storage, validation, and Elo ranking for LLM benchmark
games imported as PGN.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import io
import math
from pathlib import Path

import chess
import chess.pgn

from settings import BENCHMARK_PGN_PATH


VALID_RESULTS = {"1-0", "0-1", "1/2-1/2"}
DEFAULT_ELO = 1200.0
DEFAULT_K_FACTOR = 32.0


@dataclass(slots=True)
class BenchmarkGameRecord:
    index: int
    white: str
    black: str
    result: str
    pgn_text: str
    starting_fen: str
    ply_count: int
    fingerprint: str


@dataclass(slots=True)
class LeaderboardEntry:
    rank: int
    model: str
    rating: float
    games: int
    wins: int
    draws: int
    losses: int


@dataclass(slots=True)
class BenchmarkSnapshot:
    leaderboard: list[LeaderboardEntry]
    games: list[BenchmarkGameRecord]


def ensure_benchmark_file(path: str | Path = BENCHMARK_PGN_PATH) -> Path:
    benchmark_path = Path(path)
    benchmark_path.parent.mkdir(parents=True, exist_ok=True)
    benchmark_path.touch(exist_ok=True)
    return benchmark_path


def load_benchmark_games(path: str | Path = BENCHMARK_PGN_PATH) -> list[BenchmarkGameRecord]:
    benchmark_path = ensure_benchmark_file(path)
    with benchmark_path.open("r", encoding="utf-8") as handle:
        content = handle.read()

    if not content.strip():
        return []

    records: list[BenchmarkGameRecord] = []
    stream = io.StringIO(content)
    index = 1
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        records.append(_game_to_record(game, index))
        index += 1

    return records


def load_benchmark_snapshot(path: str | Path = BENCHMARK_PGN_PATH) -> BenchmarkSnapshot:
    games = load_benchmark_games(path)
    leaderboard = build_leaderboard(games)
    return BenchmarkSnapshot(leaderboard=leaderboard, games=games)


def validate_benchmark_import(
    pgn_text: str,
    existing_games: list[BenchmarkGameRecord] | None = None,
) -> BenchmarkGameRecord:
    text = pgn_text.strip()
    if not text:
        raise ValueError("Please paste a PGN first.")

    stream = io.StringIO(text)
    game = chess.pgn.read_game(stream)
    if game is None:
        raise ValueError("No PGN game found.")

    extra_game = chess.pgn.read_game(stream)
    if extra_game is not None:
        raise ValueError("Please import exactly one PGN game at a time.")

    record = _game_to_record(game, 1)
    existing_fingerprints = {
        item.fingerprint for item in (existing_games or [])
    }
    if record.fingerprint in existing_fingerprints:
        raise ValueError("That benchmark game has already been imported.")

    return record


def import_benchmark_game(
    pgn_text: str,
    path: str | Path = BENCHMARK_PGN_PATH,
) -> BenchmarkGameRecord:
    benchmark_path = ensure_benchmark_file(path)
    existing_games = load_benchmark_games(benchmark_path)
    record = validate_benchmark_import(pgn_text, existing_games=existing_games)
    record = replace(record, index=len(existing_games) + 1)
    _append_normalized_game_text(benchmark_path, record.pgn_text)
    return record


def build_leaderboard(
    games: list[BenchmarkGameRecord],
    *,
    default_elo: float = DEFAULT_ELO,
    k_factor: float = DEFAULT_K_FACTOR,
) -> list[LeaderboardEntry]:
    ratings: dict[str, float] = {}
    stats: dict[str, dict[str, int]] = {}

    for game in games:
        white_rating = ratings.get(game.white, default_elo)
        black_rating = ratings.get(game.black, default_elo)

        expected_white = _expected_score(white_rating, black_rating)
        expected_black = 1.0 - expected_white
        actual_white = _score_for_result(game.result, is_white=True)
        actual_black = 1.0 - actual_white

        ratings[game.white] = white_rating + k_factor * (actual_white - expected_white)
        ratings[game.black] = black_rating + k_factor * (actual_black - expected_black)

        _ensure_stats(stats, game.white)
        _ensure_stats(stats, game.black)
        stats[game.white]["games"] += 1
        stats[game.black]["games"] += 1

        if game.result == "1-0":
            stats[game.white]["wins"] += 1
            stats[game.black]["losses"] += 1
        elif game.result == "0-1":
            stats[game.white]["losses"] += 1
            stats[game.black]["wins"] += 1
        else:
            stats[game.white]["draws"] += 1
            stats[game.black]["draws"] += 1

    ordered_models = sorted(
        ratings,
        key=lambda model: (-ratings[model], -stats[model]["games"], model.lower()),
    )

    leaderboard: list[LeaderboardEntry] = []
    for rank, model in enumerate(ordered_models, start=1):
        model_stats = stats[model]
        leaderboard.append(
            LeaderboardEntry(
                rank=rank,
                model=model,
                rating=ratings[model],
                games=model_stats["games"],
                wins=model_stats["wins"],
                draws=model_stats["draws"],
                losses=model_stats["losses"],
            )
        )

    return leaderboard


def _ensure_stats(stats: dict[str, dict[str, int]], model: str):
    if model not in stats:
        stats[model] = {
            "games": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
        }


def _expected_score(player_rating: float, opponent_rating: float) -> float:
    return 1.0 / (1.0 + math.pow(10.0, (opponent_rating - player_rating) / 400.0))


def _score_for_result(result: str, *, is_white: bool) -> float:
    if result == "1-0":
        return 1.0 if is_white else 0.0
    if result == "0-1":
        return 0.0 if is_white else 1.0
    return 0.5


def _append_normalized_game_text(path: Path, normalized_pgn_text: str):
    existing = path.read_text(encoding="utf-8")
    text = normalized_pgn_text.strip()
    if not text:
        raise ValueError("Cannot import an empty PGN game.")

    with path.open("a", encoding="utf-8") as handle:
        if existing.strip():
            if not existing.endswith("\n"):
                handle.write("\n")
            handle.write("\n")
        handle.write(text)
        handle.write("\n")


def _game_to_record(game: chess.pgn.Game, index: int) -> BenchmarkGameRecord:
    headers = game.headers
    white = headers.get("White", "").strip()
    black = headers.get("Black", "").strip()
    result = headers.get("Result", "").strip()

    if not white:
        raise ValueError("Benchmark PGN is missing the White player name.")
    if not black:
        raise ValueError("Benchmark PGN is missing the Black player name.")
    if white == black:
        raise ValueError("White and Black must be different model names.")
    if result not in VALID_RESULTS:
        raise ValueError("Benchmark PGN must include a final result.")

    starting_fen = headers.get("FEN", "").strip() or chess.STARTING_FEN
    try:
        board = chess.Board(starting_fen)
    except ValueError as exc:
        raise ValueError(f"Invalid FEN inside benchmark PGN: {exc}") from exc

    move_uci: list[str] = []
    for move in game.mainline_moves():
        if move not in board.legal_moves:
            raise ValueError(f"Illegal move in benchmark PGN: {move.uci()}")
        move_uci.append(move.uci())
        board.push(move)

    normalized_pgn = _export_game(game)
    fingerprint_source = "\n".join(
        [
            white,
            black,
            result,
            starting_fen,
            " ".join(move_uci),
        ]
    )
    fingerprint = sha256(fingerprint_source.encode("utf-8")).hexdigest()

    return BenchmarkGameRecord(
        index=index,
        white=white,
        black=black,
        result=result,
        pgn_text=normalized_pgn,
        starting_fen=starting_fen,
        ply_count=len(move_uci),
        fingerprint=fingerprint,
    )


def _export_game(game: chess.pgn.Game) -> str:
    exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
    return game.accept(exporter).strip()
