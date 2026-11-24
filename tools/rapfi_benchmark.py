#!/usr/bin/env python3
"""Course-rule matches with Windows peak-memory and CPU accounting.

Both players are pinned to the same allowed logical processor. Only the player
whose turn it is searches. Peak memory is read from the OS after every response;
it includes transient allocations between samples. This is a Windows benchmark,
not evidence of Linux runtime compatibility or a statistically measured win rate.
"""
from __future__ import annotations

import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import platform
import time

import arena


class MemoryCounters(C.Structure):
    _fields_ = [("cb", W.DWORD), ("PageFaultCount", W.DWORD)] + [
        (name, C.c_size_t) for name in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
            "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
            "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
            "PrivateUsage",
        )
    ]


class FileTime(C.Structure):
    _fields_ = [("low", W.DWORD), ("high", W.DWORD)]

    def seconds(self):
        return ((self.high << 32) | self.low) / 10_000_000


def fingerprint(path):
    p = Path(path).resolve()
    data = p.read_bytes()
    return {"path": str(p), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--black", required=True, type=Path)
    parser.add_argument("--white", required=True, type=Path)
    parser.add_argument("--games", type=arena.positive_int, default=2)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Windows OS memory counters required; use arena.py on other systems")

    kernel = C.WinDLL("kernel32", use_last_error=True)
    psapi = C.WinDLL("psapi", use_last_error=True)
    kernel.GetProcessAffinityMask.argtypes = [W.HANDLE, C.POINTER(C.c_size_t), C.POINTER(C.c_size_t)]
    kernel.GetProcessAffinityMask.restype = W.BOOL
    kernel.SetProcessAffinityMask.argtypes = [W.HANDLE, C.c_size_t]
    kernel.SetProcessAffinityMask.restype = W.BOOL
    kernel.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(FileTime)] * 4
    kernel.GetProcessTimes.restype = W.BOOL
    psapi.GetProcessMemoryInfo.argtypes = [W.HANDLE, C.POINTER(MemoryCounters), W.DWORD]
    psapi.GetProcessMemoryInfo.restype = W.BOOL

    observations = []
    base_brain = arena.Brain

    class MeasuredBrain(base_brain):
        def __init__(self, command):
            launch = time.perf_counter()
            super().__init__(command)
            self.launch = launch
            self.measurement = {"command": command, "pid": self.process.pid,
                                "peak_working_set_bytes": 0, "peak_commit_bytes": 0,
                                "cpu_seconds": 0, "turns": 0, "max_turn_seconds": 0}
            observations.append(self.measurement)
            allowed, system = C.c_size_t(), C.c_size_t()
            handle = W.HANDLE(int(self.process._handle))
            if not kernel.GetProcessAffinityMask(handle, C.byref(allowed), C.byref(system)):
                raise C.WinError(C.get_last_error())
            mask = allowed.value & -allowed.value
            if not kernel.SetProcessAffinityMask(handle, mask):
                raise C.WinError(C.get_last_error())
            self.measurement["affinity_mask"] = mask

        def sample(self):
            handle = W.HANDLE(int(self.process._handle))
            mem = MemoryCounters()
            mem.cb = C.sizeof(mem)
            if not psapi.GetProcessMemoryInfo(handle, C.byref(mem), mem.cb):
                raise C.WinError(C.get_last_error())
            self.measurement["peak_working_set_bytes"] = max(
                self.measurement["peak_working_set_bytes"], mem.PeakWorkingSetSize)
            self.measurement["peak_commit_bytes"] = max(
                self.measurement["peak_commit_bytes"], mem.PeakPagefileUsage)
            created, exited, kernel_time, user_time = (FileTime() for _ in range(4))
            if not kernel.GetProcessTimes(handle, C.byref(created), C.byref(exited),
                                          C.byref(kernel_time), C.byref(user_time)):
                raise C.WinError(C.get_last_error())
            self.measurement["cpu_seconds"] = kernel_time.seconds() + user_time.seconds()

        def request(self, command, timeout, limit_name):
            response = super().request(command, timeout, limit_name)
            self.sample()
            if command.startswith("START"):
                self.measurement["startup_including_launch_seconds"] = time.perf_counter() - self.launch
            if command == "TURN":
                self.measurement["turns"] += 1
                self.measurement["max_turn_seconds"] = max(self.measurement["max_turn_seconds"], response[1])
            return response

    arena.Brain = MeasuredBrain
    commands = {"A": [str(args.black.resolve())], "B": [str(args.white.resolve())]}
    report = {"schema_version": 1, "platform": platform.platform(),
              "board_size": 12, "initial_stones": arena.INITIAL,
              "commands": commands,
              "executables": {k: fingerprint(v[0]) for k, v in commands.items()},
              "settings": {"games": args.games, "move_timeout": 2.0, "total_timeout": 90.0,
                           "single_logical_processor": True},
              "games": [], "resources": observations}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for index in range(1, args.games + 1):
        game = arena.play_game(commands, index, 2.0, 90.0)
        report["games"].append(game)
        report["summary"] = arena.summarize(report["games"])
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"game {index}: colors={game['colors']}, winner={game['winner']}, "
              f"plies={len(game['moves'])}, reason={game['reason']}, forfeit={game['forfeit']}", flush=True)
    print(json.dumps(report["summary"], indent=2), flush=True)
    for record in observations:
        print(f"pid={record['pid']} peak_RSS={record['peak_working_set_bytes']/1048576:.2f} MiB "
              f"peak_commit={record['peak_commit_bytes']/1048576:.2f} MiB", flush=True)
    return int(any(game["forfeit"] for game in report["games"]))


if __name__ == "__main__":
    raise SystemExit(main())
