#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reliable pre-rendered Sophia clip launcher for demo day.

Focus the terminal, then press `1`-`8` to play a canned WAV from
`/tmp/sophia_clips`. This mode has no LLM, STT, or XTTS dependency once the
clips are rendered.
"""
from __future__ import annotations

import argparse
import re
import select
import shutil
import subprocess
import sys
import termios
import tty
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CLIP_DIR = Path("/tmp/sophia_clips")


@dataclass(frozen=True)
class Clip:
    key: str
    path: Path
    label: str


class RawTerminal:
    def __enter__(self) -> "RawTerminal":
        if not sys.stdin.isatty():
            raise SystemExit("stdin is not a TTY; run this in a focused terminal.")
        self.fd = sys.stdin.fileno()
        self.original = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.original)


class ClipPlayer:
    def __init__(self, command: str = "aplay") -> None:
        binary = shutil.which(command)
        if not binary:
            raise SystemExit(f"{command!r} not found in PATH.")
        self.command = binary
        self.proc: subprocess.Popen[bytes] | None = None

    def stop(self) -> None:
        if not self.proc or self.proc.poll() is not None:
            self.proc = None
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=0.5)
        self.proc = None

    def play(self, clip: Clip) -> None:
        self.stop()
        self.proc = subprocess.Popen([self.command, "-q", str(clip.path)])

    def close(self) -> None:
        self.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clip-dir",
        type=Path,
        default=DEFAULT_CLIP_DIR,
        help="Directory containing 01_*.wav through 08_*.wav",
    )
    parser.add_argument(
        "--player",
        default="aplay",
        help="Playback command to use (default: aplay)",
    )
    return parser.parse_args()


def load_clips(clip_dir: Path) -> dict[str, Clip]:
    if not clip_dir.exists():
        raise SystemExit(f"Clip directory not found: {clip_dir}")

    clips: dict[str, Clip] = {}
    for path in sorted(clip_dir.glob("*.wav")):
        match = re.match(r"^0?([1-8])(?:[_-](.*))?$", path.stem)
        if not match:
            continue
        key = match.group(1)
        label = (match.group(2) or path.stem).replace("_", " ").replace("-", " ")
        clips[key] = Clip(key=key, path=path, label=label)

    missing = [str(i) for i in range(1, 9) if str(i) not in clips]
    if missing:
        raise SystemExit(
            f"Missing clip(s) for key(s): {', '.join(missing)} in {clip_dir}. "
            "Expected files like 01_greeting.wav ... 08_close.wav."
        )
    return clips


def read_key(timeout: float = 0.1) -> str | None:
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        return None
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        select.select([sys.stdin], [], [], 0.01)
        while select.select([sys.stdin], [], [], 0.0)[0]:
            sys.stdin.read(1)
        return None
    return ch


def print_banner(clips: dict[str, Clip], clip_dir: Path) -> None:
    print()
    print("Sophia Hotkeys")
    print(f"Clip dir: {clip_dir}")
    print("Keys: 1-8 play, 0 stop, r replay last, q quit")
    for key in sorted(clips):
        clip = clips[key]
        print(f"  {clip.key}: {clip.label} [{clip.path.name}]")
    print()


def main() -> int:
    args = parse_args()
    clips = load_clips(args.clip_dir)
    player = ClipPlayer(args.player)
    last_key: str | None = None

    print_banner(clips, args.clip_dir)
    try:
        with RawTerminal():
            while True:
                key = read_key()
                if key is None:
                    continue
                if key in clips:
                    player.play(clips[key])
                    last_key = key
                    print(f"\rPlaying {key}: {clips[key].label:<40}", end="", flush=True)
                    continue
                if key in {"r", "R"} and last_key:
                    player.play(clips[last_key])
                    print(f"\rReplaying {last_key}: {clips[last_key].label:<38}", end="", flush=True)
                    continue
                if key == "0":
                    player.stop()
                    print("\rStopped playback.                               ", end="", flush=True)
                    continue
                if key in {"q", "Q", "\x03"}:
                    break
    finally:
        player.close()

    print("\nExited cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
