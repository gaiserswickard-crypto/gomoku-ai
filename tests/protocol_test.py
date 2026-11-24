#!/usr/bin/env python3
"""Black-box protocol checks for the competition executable (standard library).

Run from any working directory:
  python gomoku/tests/protocol_test.py
  python gomoku/tests/protocol_test.py --engine gomoku/build/gomoku_fast.exe

These are short protocol/state tests, not full games or a strength benchmark.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
import queue
import subprocess
import sys
import time


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools"))
from arena import Brain, BrainFailure, COORDINATES, INITIAL  # noqa: E402


INITIAL_POINTS = {(row, col) for row, col, _ in INITIAL}
QUIET_SECONDS = 0.04


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def quiet(brain: Brain) -> None:
    """Leave enough time for unsolicited output to reach the reader thread."""
    try:
        _, line = brain.events.get(timeout=QUIET_SECONDS)
    except queue.Empty:
        brain.check_idle()
        return
    if line is None:
        raise AssertionError("process exited before END/EOF")
    raise AssertionError(f"unexpected stdout: {line!r}")


def start(brain: Brain, color: int) -> None:
    reply, elapsed = brain.request(f"START {color}", 1.0, "START time limit")
    require(reply == "OK", f"START {color}: expected exact OK, got {reply!r}")
    require(elapsed < 1.0, f"START took {elapsed:.3f} s")
    quiet(brain)


def turn(brain: Brain, occupied: set[tuple[int, int]]) -> tuple[int, int]:
    reply, elapsed = brain.request("TURN", 2.0, "TURN time limit")
    match = COORDINATES.fullmatch(reply)
    require(match is not None, f"invalid TURN response: {reply!r}")
    assert match is not None
    point = tuple(map(int, match.groups()))
    require(all(0 <= coordinate < 12 for coordinate in point), f"out-of-range move: {point}")
    require(point not in occupied, f"occupied move: {point}")
    require(elapsed < 2.0, f"TURN took {elapsed:.3f} s")
    quiet(brain)
    return point


def finish(brain: Brain, command: str | None = "END 0") -> None:
    """Check natural exit; Brain.close's forced termination cannot pass this."""
    if command is None:
        assert brain.process.stdin is not None
        brain.process.stdin.close()
    else:
        brain.send(command)
    try:
        code = brain.process.wait(timeout=1.0)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError("process did not exit within 1 s after END/EOF") from exc
    require(code == 0, f"abnormal exit code: {code}")
    brain.stdout_thread.join(timeout=0.3)
    require(not brain.stdout_thread.is_alive(), "stdout reader did not finish")
    require(not brain.overflow, "stdout queue overflow")
    while True:
        try:
            _, line = brain.events.get_nowait()
        except queue.Empty:
            break
        require(line is None, f"unexpected stdout during exit: {line!r}")


@contextmanager
def running(engine: Path):
    brain = Brain([str(engine)])
    try:
        yield brain
    finally:
        brain.close(0)


def test_black_start_turn(engine: Path) -> None:
    with running(engine) as brain:
        start(brain, 1)
        turn(brain, INITIAL_POINTS)
        finish(brain, "END 1")


def test_white_place_turn(engine: Path) -> None:
    with running(engine) as brain:
        start(brain, 2)
        point = (4, 5)
        brain.send(f"PLACE {point[0]} {point[1]}")
        quiet(brain)
        turn(brain, INITIAL_POINTS | {point})
        finish(brain, "END 2")


def test_multiple_turns_record_own_stones(engine: Path) -> None:
    with running(engine) as brain:
        start(brain, 1)
        occupied = set(INITIAL_POINTS)
        occupied.add(turn(brain, occupied))
        opponent = next((r, c) for r in range(12) for c in range(12) if (r, c) not in occupied)
        brain.send(f"PLACE {opponent[0]} {opponent[1]}")
        quiet(brain)
        occupied.add(opponent)
        occupied.add(turn(brain, occupied))
        finish(brain)


def make_gap_four(brain: Brain, target: tuple[int, int]) -> set[tuple[int, int]]:
    """Build an opponent split four whose sole completion is target.

    Used after START reset to test whether a previously occupied square is
    empty again. Multiple PLACEs are a synthetic protocol fixture, not a game.
    """
    row, col = target
    for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
        for gap_index in (2, 1, 3):
            line = [(row + (k-gap_index)*dr, col + (k-gap_index)*dc) for k in range(5)]
            if not all(0 <= r < 12 and 0 <= c < 12 for r, c in line):
                continue
            if set(line) & INITIAL_POINTS:
                continue
            # Keep the fixture away from the initial central pieces, so they
            # cannot supply an unrelated immediate five in another direction.
            if any(max(abs(r-ir), abs(c-ic)) <= 1 for r, c in line for ir, ic in INITIAL_POINTS):
                continue
            stones = set(line) - {target}
            for r, c in sorted(stones):
                brain.send(f"PLACE {r} {c}")
            quiet(brain)
            return stones
    raise AssertionError(f"cannot construct isolated reset fixture around {target}")


def test_repeated_start_clears_opponent(engine: Path) -> None:
    with running(engine) as brain:
        start(brain, 1)
        target = (2, 2)
        brain.send("PLACE 2 2")
        quiet(brain)
        start(brain, 1)
        stones = make_gap_four(brain, target)
        actual = turn(brain, INITIAL_POINTS | stones)
        require(actual == target, f"START did not clear old opponent stone; expected {target}, got {actual}")
        finish(brain)


def test_repeated_start_clears_own_stone_and_changes_color(engine: Path) -> None:
    with running(engine) as brain:
        start(brain, 1)
        # Force black's first answer to a known isolated square. It is then
        # black's own stone until START 2 must discard the whole old position.
        target = (2, 2)
        stones = make_gap_four(brain, target)
        actual = turn(brain, INITIAL_POINTS | stones)
        require(actual == target, f"fixture expected forced block {target}, got {actual}")
        start(brain, 2)
        stones = make_gap_four(brain, target)
        actual = turn(brain, INITIAL_POINTS | stones)
        require(actual == target, f"START did not clear own stone/change color; expected {target}, got {actual}")
        finish(brain)


def test_unknown_and_invalid_place(engine: Path) -> None:
    with running(engine) as brain:
        # These malformed inputs are outside the official referee's protocol;
        # robust handling should stay silent, alive, and in bounds.
        for command in ("HELLO", "TURN", "PLACE 0 0", "START 0", "START x", "START"):
            brain.send(command)
        quiet(brain)
        start(brain, 1)
        for command in ("", "UNKNOWN 1 2", "PLACE -1 0", "PLACE 0 -1", "PLACE 12 0",
                        "PLACE 0 12", "PLACE 999999999999999999 0", "PLACE x y",
                        "PLACE", "PLACE 3", "PLACE 5 5", "PLACE 5 6"):
            brain.send(command)
        quiet(brain)
        brain.send("PLACE 2 2")
        quiet(brain)
        turn(brain, INITIAL_POINTS | {(2, 2)})
        finish(brain)


def test_end_before_start(engine: Path) -> None:
    with running(engine) as brain:
        finish(brain, "END 0")


def test_eof_before_start(engine: Path) -> None:
    with running(engine) as brain:
        finish(brain, None)


def test_eof_after_start(engine: Path) -> None:
    with running(engine) as brain:
        start(brain, 2)
        finish(brain, None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--engine", type=Path, default=PROJECT / "build" / "gomoku.exe")
    args = parser.parse_args()
    engine = args.engine.resolve()
    if not engine.is_file():
        parser.error(f"engine does not exist: {engine}")
    tests = (
        test_black_start_turn, test_white_place_turn,
        test_multiple_turns_record_own_stones, test_repeated_start_clears_opponent,
        test_repeated_start_clears_own_stone_and_changes_color, test_unknown_and_invalid_place,
        test_end_before_start, test_eof_before_start, test_eof_after_start,
    )
    failures = 0
    started = time.perf_counter()
    for test in tests:
        try:
            test(engine)
        except (AssertionError, BrainFailure, OSError, ValueError, subprocess.SubprocessError) as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}", flush=True)
        else:
            print(f"PASS {test.__name__}", flush=True)
    print(f"Protocol tests: {len(tests)-failures}/{len(tests)} passed, "
          f"{failures} failed ({time.perf_counter()-started:.2f} s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
