#!/usr/bin/env python3
"""Run two persistent Gomoku brains using only the Python standard library.

Examples (quote paths that contain spaces):
  python tools/arena.py --black build/brain.exe --white build/reference.exe --games 2
  python tools/arena.py --black python --black-arg toy.py --white build/brain.exe

The first command is competitor A, the second is competitor B. Odd-numbered
games use A as black; even-numbered games reverse the colors. Each game uses
fresh processes and the assignment's four-stone initial position. Arguments
are passed directly to subprocess.Popen, never through a shell. For an engine
argument starting with '-', use e.g. --black-arg=--time-ms=100.
"""

from __future__ import annotations

import argparse
from collections import deque
import json
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time


SIZE = 12
INITIAL = [(5, 5, 2), (6, 6, 2), (5, 6, 1), (6, 5, 1)]
COORDINATES = re.compile(r"\s*([+-]?[0-9]+)\s+([+-]?[0-9]+)\s*\Z")


class BrainFailure(Exception):
    def __init__(self, message: str, elapsed: float = 0.0):
        super().__init__(message)
        self.elapsed = elapsed


class Brain:
    """A child process with nonblocking, timestamped stdout on Windows/Linux."""

    def __init__(self, command: list[str]):
        self.command = command
        self.events: queue.Queue[tuple[float, str | None]] = queue.Queue(1024)
        self.overflow = False
        self.debug: list[str] = []
        self.debug_bytes = 0
        self.stderr_tail: deque[str] = deque(maxlen=40)
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self.stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self.stdout_thread.start()
        self.stderr_thread.start()

    def _enqueue(self, line: str | None) -> bool:
        try:
            self.events.put_nowait((time.perf_counter(), line))
            return True
        except queue.Full:
            self.overflow = True
            return False

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        try:
            while True:
                raw = self.process.stdout.readline(65537)
                if not raw:
                    self._enqueue(None)
                    return
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if len(raw) > 65536 or not raw.endswith(b"\n"):
                    self._enqueue("<unterminated or oversized stdout line>")
                    return
                if line == "DEBUG" or line.startswith("DEBUG ") or line.startswith("DEBUG["):
                    # The assignment records at most 16 KiB per debug line and
                    # 32 KiB in total. Excess debug text is ignored, not queued.
                    remaining = max(0, 32768 - self.debug_bytes)
                    fragment = raw[:min(16384, remaining)]
                    if fragment:
                        self.debug.append(fragment.decode("utf-8", errors="replace").rstrip())
                        self.debug_bytes += len(fragment)
                    continue
                if not self._enqueue(line):
                    return
        except (OSError, ValueError):
            self._enqueue(None)

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        try:
            while True:
                raw = self.process.stderr.readline(4096)
                if not raw:
                    return
                self.stderr_tail.append(raw.decode("utf-8", errors="replace").rstrip())
        except (OSError, ValueError):
            return

    def check_idle(self) -> None:
        """Reject unsolicited output or a process that exits before END."""
        if self.overflow:
            raise BrainFailure("stdout queue overflow (unsolicited output)")
        try:
            _, line = self.events.get_nowait()
        except queue.Empty:
            if self.process.poll() is not None:
                raise BrainFailure(f"process exited before END (code {self.process.returncode})")
            return
        if line is None:
            raise BrainFailure(f"stdout closed before END (code {self.process.poll()})")
        raise BrainFailure(f"unsolicited stdout: {line[:200]!r}")

    def send(self, command: str) -> None:
        assert self.process.stdin is not None
        try:
            self.process.stdin.write((command + "\n").encode("ascii"))
            self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise BrainFailure(f"cannot send {command!r}: {exc}") from exc

    def request(self, command: str, timeout: float, limit_name: str) -> tuple[str, float]:
        self.check_idle()
        started = time.perf_counter()
        try:
            self.send(command)
            remaining = timeout - (time.perf_counter() - started)
            if remaining <= 0:
                raise queue.Empty
            received, line = self.events.get(timeout=remaining)
            elapsed = received - started
            if received < started:
                raise BrainFailure(f"response arrived before {command!r}: {line!r}")
            if elapsed > timeout:
                raise BrainFailure(f"{limit_name} exceeded ({elapsed:.3f} s)")
            if self.overflow:
                raise BrainFailure("stdout queue overflow")
            if line is None:
                raise BrainFailure(f"stdout closed while waiting for {command!r} (code {self.process.poll()})")
            return line, elapsed
        except queue.Empty as exc:
            raise BrainFailure(f"{limit_name} exceeded ({timeout:.3f} s)", time.perf_counter() - started) from exc
        except BrainFailure as exc:
            exc.elapsed = max(0.0, time.perf_counter() - started)
            raise

    def close(self, result: int) -> None:
        if self.process.poll() is None:
            try:
                self.send(f"END {result}")
            except BrainFailure:
                pass
            try:
                self.process.wait(timeout=0.15)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=1.0)
        self.stdout_thread.join(timeout=0.3)
        self.stderr_thread.join(timeout=0.3)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()


def has_five(board: list[list[int]], row: int, col: int, color: int) -> bool:
    for dr, dc in ((1, 0), (0, 1), (1, 1), (1, -1)):
        count = 1
        for sign in (-1, 1):
            r, c = row + sign * dr, col + sign * dc
            while 0 <= r < SIZE and 0 <= c < SIZE and board[r][c] == color:
                count += 1
                r += sign * dr
                c += sign * dc
        if count >= 5:
            return True
    return False


def play_game(commands: dict[str, list[str]], game_index: int, move_timeout: float,
              total_timeout: float) -> dict:
    colors = {1: "A", 2: "B"} if game_index % 2 else {1: "B", 2: "A"}
    board = [[0] * SIZE for _ in range(SIZE)]
    for row, col, color in INITIAL:
        board[row][col] = color
    result = {
        "game": game_index,
        "colors": {"black": colors[1], "white": colors[2]},
        "winner": None,
        "winner_color": 0,
        "reason": "draw",
        "forfeit": None,
        "moves": [],
        "total_seconds": {"A": 0.0, "B": 0.0},
        "startup_seconds": {"A": 0.0, "B": 0.0},
    }
    brains: dict[int, Brain] = {}
    offending_color = 1
    game_started = time.perf_counter()
    try:
        for color in (1, 2):
            offending_color = color
            try:
                brains[color] = Brain(commands[colors[color]])
            except OSError as exc:
                raise BrainFailure(f"cannot launch process: {exc}") from exc
            try:
                reply, elapsed = brains[color].request(f"START {color}", min(1.0, total_timeout), "START time limit")
            except BrainFailure as exc:
                result["total_seconds"][colors[color]] += exc.elapsed
                raise
            result["startup_seconds"][colors[color]] = elapsed
            result["total_seconds"][colors[color]] += elapsed
            if reply.strip() != "OK":
                raise BrainFailure(f"expected OK after START, got {reply[:200]!r}")
        for ply in range(SIZE * SIZE - len(INITIAL)):
            color = 1 + ply % 2
            for checked_color in (1, 2):
                offending_color = checked_color
                brains[checked_color].check_idle()
            offending_color = color
            competitor = colors[color]
            remaining = total_timeout - result["total_seconds"][competitor]
            if remaining <= 0:
                raise BrainFailure(f"game time limit exceeded ({total_timeout:.3f} s)")
            timeout = min(move_timeout, remaining)
            limit_name = "move time limit" if move_timeout <= remaining else "game time limit"
            try:
                reply, elapsed = brains[color].request("TURN", timeout, limit_name)
            except BrainFailure as exc:
                result["total_seconds"][competitor] += exc.elapsed
                raise
            result["total_seconds"][competitor] += elapsed
            match = COORDINATES.fullmatch(reply)
            if match is None:
                raise BrainFailure(f"invalid TURN response: {reply[:200]!r}")
            try:
                row, col = map(int, match.groups())
            except ValueError as exc:
                raise BrainFailure("coordinate integer is too large") from exc
            if not (0 <= row < SIZE and 0 <= col < SIZE):
                raise BrainFailure(f"out-of-board move ({row}, {col})")
            if board[row][col]:
                raise BrainFailure(f"occupied move ({row}, {col})")
            board[row][col] = color
            result["moves"].append({
                "ply": ply + 1, "color": color, "engine": competitor,
                "row": row, "col": col, "seconds": elapsed,
                "total_seconds": result["total_seconds"][competitor],
            })
            # The other brain receives the final placement too; no TURN follows
            # if this placement ends the game.
            offending_color = 3 - color
            brains[3 - color].check_idle()
            brains[3 - color].send(f"PLACE {row} {col}")
            if has_five(board, row, col, color):
                result["winner"] = competitor
                result["winner_color"] = color
                result["reason"] = "five"
                break
    except BrainFailure as exc:
        result["winner_color"] = 3 - offending_color
        result["winner"] = colors[3 - offending_color]
        result["reason"] = "forfeit"
        result["forfeit"] = {
            "engine": colors[offending_color], "color": offending_color, "message": str(exc),
        }
    finally:
        for color, brain in brains.items():
            outcome = 0 if not result["winner_color"] else (1 if result["winner_color"] == color else 2)
            brain.close(outcome)
        result["wall_seconds"] = time.perf_counter() - game_started
        result["debug"] = {colors[c]: brain.debug for c, brain in brains.items()}
        result["stderr_tail"] = {colors[c]: list(brain.stderr_tail) for c, brain in brains.items()}
    return result


def summarize(games: list[dict]) -> dict:
    summary = {"games": len(games), "wins": {"A": 0, "B": 0}, "draws": 0,
               "forfeits": {"A": 0, "B": 0}, "timing": {}}
    for game in games:
        if game["winner"] is None:
            summary["draws"] += 1
        else:
            summary["wins"][game["winner"]] += 1
        if game["forfeit"]:
            summary["forfeits"][game["forfeit"]["engine"]] += 1
    for competitor in ("A", "B"):
        times = [m["seconds"] for game in games for m in game["moves"] if m["engine"] == competitor]
        summary["timing"][competitor] = {
            "moves": len(times), "average_seconds": sum(times) / len(times) if times else 0,
            "maximum_seconds": max(times, default=0),
            "maximum_game_seconds": max((g["total_seconds"][competitor] for g in games), default=0),
        }
    return summary


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if not (0 < parsed < float("inf")):
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--black", required=True, help="competitor A executable; black in game 1")
    parser.add_argument("--white", required=True, help="competitor B executable; white in game 1")
    parser.add_argument("--black-arg", action="append", default=[], help="repeat for each argument to A")
    parser.add_argument("--white-arg", action="append", default=[], help="repeat for each argument to B")
    parser.add_argument("--games", type=positive_int, default=2, help="number of games, alternating colors (default 2)")
    parser.add_argument("--move-timeout", type=positive_float, default=2.0)
    parser.add_argument("--total-timeout", type=positive_float, default=90.0)
    parser.add_argument("--output", type=Path, help="write complete JSON report, updating after every game")
    args = parser.parse_args()
    commands = {"A": [args.black, *args.black_arg], "B": [args.white, *args.white_arg]}
    report = {
        "schema_version": 1, "board_size": SIZE, "initial_stones": INITIAL,
        "commands": commands,
        "settings": {"games": args.games, "move_timeout": args.move_timeout, "total_timeout": args.total_timeout},
        "games": [], "summary": {},
    }
    print(f"A: {subprocess.list2cmdline(commands['A'])}", flush=True)
    print(f"B: {subprocess.list2cmdline(commands['B'])}", flush=True)
    try:
        for index in range(1, args.games + 1):
            game = play_game(commands, index, args.move_timeout, args.total_timeout)
            report["games"].append(game)
            report["summary"] = summarize(report["games"])
            outcome = "draw" if game["winner"] is None else f"{game['winner']} wins"
            reason = game["forfeit"]["message"] if game["forfeit"] else game["reason"]
            print(f"Game {index}: black={game['colors']['black']}, white={game['colors']['white']}; "
                  f"{outcome}; {len(game['moves'])} moves; {reason}", flush=True)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    summary = report["summary"]
    print(f"Summary: A {summary['wins']['A']} wins, B {summary['wins']['B']} wins, "
          f"{summary['draws']} draws; forfeits A={summary['forfeits']['A']}, B={summary['forfeits']['B']}")
    for competitor in ("A", "B"):
        timing = summary["timing"][competitor]
        print(f"{competitor}: average {timing['average_seconds']:.4f} s/move, "
              f"max {timing['maximum_seconds']:.4f} s/move, "
              f"max {timing['maximum_game_seconds']:.3f} s/game")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
