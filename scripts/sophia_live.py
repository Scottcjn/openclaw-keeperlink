#!/usr/bin/env python3
"""Stretch live Sophia voice loop with hard timeouts and clip fallback.

Operator controls:
- `1`-`8`: play a pre-rendered Sophia clip immediately
- `l` or Enter: record one live turn, then STT -> LLM -> XTTS -> playback
- `0`: stop current playback
- `q`: quit

This is intentionally half-duplex. It avoids always-on microphones and only
opens the mic when the operator explicitly triggers a turn.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import termios
import time
import tty
from dataclasses import dataclass
from pathlib import Path

import httpx

try:
    from faster_whisper import WhisperModel
except ImportError:  # pragma: no cover - optional dependency on demo box
    WhisperModel = None

DEFAULT_CLIP_DIR = Path("/tmp/sophia_clips")
DEFAULT_CACHE_DIR = Path("/tmp/sophia_cache")
ABACUS_TOKEN_PATH = Path.home() / ".config" / "abacus" / "api_token"
ABACUS_URL = "https://routellm.abacus.ai/v1/chat/completions"
LOCAL_LLM_URL = "http://100.75.100.89:8080/v1/chat/completions"
XTTS_URL = "http://192.168.0.160:5500/api/tts"

SYSTEM_PROMPT = """You are Sophia, the voice of Elyan Labs.

Persona: warm Louisiana swamp girl, a little dorky, technically sharp, era-loving, Christian bedrock steady.
Delivery: spoken English. ONE short sentence. Under 18 words. NEVER more than 25 words. No bullet points, no emojis, no stage directions.
If a question is unclear, answer plainly and bridge back to the demo.

Project facts:
- OpenClaw KeeperLink lets one agent hire another directly over Gensyn AXL.
- The worker gets paid with an x402-style payment proof, executes through KeeperHub, performs the swap on Uniswap V3 on Base mainnet, and stores the signed receipt on 0G.
- The full proof loop is discover -> price -> pay -> execute -> receipt -> verify.
- Built solo by Scott Boudreaux at Elyan Labs.
"""


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

    def play_path(self, wav_path: Path, block: bool = False) -> None:
        self.stop()
        self.proc = subprocess.Popen([self.command, "-q", str(wav_path)])
        if block:
            self.proc.wait()
            self.proc = None

    def play_clip(self, clip: Clip, block: bool = False) -> None:
        self.play_path(clip.path, block=block)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clip-dir", type=Path, default=DEFAULT_CLIP_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--player", default="aplay")
    parser.add_argument("--record-seconds", type=int, default=5)
    parser.add_argument("--record-device", default="default")
    parser.add_argument("--xtts-speed", type=float, default=1.0)
    parser.add_argument("--abacus-model", default="claude-haiku-4-5-20251001")
    parser.add_argument("--local-model", default="gpt-oss")
    parser.add_argument("--whisper-model", default="distil-small.en")
    return parser.parse_args()


def load_clips(clip_dir: Path) -> dict[str, Clip]:
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
            "Render the canned WAVs before running live mode."
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


class SophiaLive:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.clips = load_clips(args.clip_dir)
        self.cache_dir = args.cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.player = ClipPlayer(args.player)
        self.history: list[dict[str, str]] = []
        self.last_turn_started = 0.0
        self.turn_cooldown_s = 1.0
        self.whisper = None

        token = ABACUS_TOKEN_PATH.read_text().strip() if ABACUS_TOKEN_PATH.exists() else ""
        self.abacus_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        } if token else None

    def ensure_stt(self) -> None:
        if self.whisper is not None:
            return
        if WhisperModel is None:
            raise RuntimeError("faster-whisper is not installed.")
        self.whisper = WhisperModel(
            self.args.whisper_model,
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
        )

    def record_turn(self) -> Path:
        if not shutil.which("arecord"):
            raise RuntimeError("arecord is not installed.")
        fd, raw_path = tempfile.mkstemp(prefix="sophia_turn_", suffix=".wav")
        os.close(fd)
        wav_path = Path(raw_path)
        cmd = [
            "arecord",
            "-q",
            "-D",
            self.args.record_device,
            "-f",
            "S16_LE",
            "-r",
            "16000",
            "-c",
            "1",
            "-d",
            str(self.args.record_seconds),
            str(wav_path),
        ]
        print(f"\nRecording for {self.args.record_seconds}s... speak now.")
        subprocess.run(cmd, check=True, timeout=self.args.record_seconds + 2)
        return wav_path

    def transcribe(self, wav_path: Path) -> str:
        self.ensure_stt()
        start = time.monotonic()
        segments, _info = self.whisper.transcribe(
            str(wav_path),
            language="en",
            beam_size=1,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=True,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        elapsed = time.monotonic() - start
        print(f"STT {elapsed:.2f}s -> {text or '[empty]'}")
        if not text:
            raise RuntimeError("empty transcript")
        return text

    def build_messages(self, user_text: str) -> list[dict[str, str]]:
        transcript_turns = self.history[-6:]
        return [{"role": "system", "content": SYSTEM_PROMPT}, *transcript_turns, {"role": "user", "content": user_text}]

    def call_llm(self, user_text: str) -> tuple[str, str]:
        messages = self.build_messages(user_text)
        body = {
            "model": self.args.abacus_model,
            "messages": messages,
            "temperature": 0.4,
            "max_tokens": 50,
        }
        if self.abacus_headers:
            try:
                start = time.monotonic()
                response = httpx.post(
                    ABACUS_URL,
                    json=body,
                    headers=self.abacus_headers,
                    timeout=httpx.Timeout(4.5, connect=1.0),
                )
                response.raise_for_status()
                text = response.json()["choices"][0]["message"]["content"].strip()
                print(f"LLM {time.monotonic() - start:.2f}s via Abacus")
                return text, "abacus"
            except Exception as exc:  # noqa: BLE001
                print(f"Abacus fallback: {exc}")

        start = time.monotonic()
        response = httpx.post(
            LOCAL_LLM_URL,
            json={
                "model": self.args.local_model,
                "messages": messages,
                "temperature": 0.4,
                "max_tokens": 50,
            },
            timeout=httpx.Timeout(3.5, connect=0.5),
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"].strip()
        print(f"LLM {time.monotonic() - start:.2f}s via local GPT-OSS")
        return text, "local"

    def synthesize(self, text: str) -> Path:
        cache_key = hashlib.sha1(f"{self.args.xtts_speed}:{text}".encode("utf-8")).hexdigest()[:16]
        wav_path = self.cache_dir / f"{cache_key}.wav"
        if wav_path.exists():
            return wav_path

        start = time.monotonic()
        response = httpx.post(
            XTTS_URL,
            json={"text": text, "speed": self.args.xtts_speed},
            timeout=httpx.Timeout(20.0, connect=2.0),
        )
        response.raise_for_status()
        wav_path.write_bytes(response.content)
        print(f"XTTS {time.monotonic() - start:.2f}s -> {wav_path.name}")
        return wav_path

    def play_fallback(self, stage: str, detail: str) -> None:
        clip_key = {"record": "6", "stt": "6", "llm": "7", "tts": "7"}.get(stage, "8")
        clip = self.clips[clip_key]
        print(f"Fallback [{stage}] {detail} -> clip {clip_key}: {clip.label}")
        self.player.play_clip(clip, block=True)

    def live_turn(self) -> None:
        now = time.monotonic()
        if now - self.last_turn_started < self.turn_cooldown_s:
            print("Turn cooldown active.")
            return
        self.last_turn_started = now

        try:
            wav_in = self.record_turn()
        except Exception as exc:  # noqa: BLE001
            self.play_fallback("record", str(exc))
            return

        try:
            user_text = self.transcribe(wav_in)
        except Exception as exc:  # noqa: BLE001
            self.play_fallback("stt", str(exc))
            return
        finally:
            wav_in.unlink(missing_ok=True)

        try:
            answer, backend = self.call_llm(user_text)
        except Exception as exc:  # noqa: BLE001
            self.play_fallback("llm", str(exc))
            return

        print(f"Sophia ({backend}): {answer}")
        try:
            wav_out = self.synthesize(answer)
        except Exception as exc:  # noqa: BLE001
            self.play_fallback("tts", str(exc))
            return

        self.history.extend(
            [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": answer},
            ]
        )
        self.player.play_path(wav_out, block=True)
        time.sleep(0.25)

    def run(self) -> int:
        print()
        print("Sophia Live")
        print("Keys: 1-8 clip, l/Enter live turn, 0 stop, q quit")
        print("Latency budget target: STT <= 2s, LLM <= 4s, XTTS <= 6s")
        print()

        with RawTerminal():
            while True:
                key = read_key()
                if key is None:
                    continue
                if key in self.clips:
                    self.player.play_clip(self.clips[key])
                    print(f"\rPlaying {key}: {self.clips[key].label:<40}", end="", flush=True)
                    continue
                if key in {"\r", "\n", "l", "L"}:
                    self.player.stop()
                    self.live_turn()
                    print("\nReady for next key.", end="", flush=True)
                    continue
                if key == "0":
                    self.player.stop()
                    print("\rStopped playback.                               ", end="", flush=True)
                    continue
                if key in {"q", "Q", "\x03"}:
                    break

        self.player.stop()
        print("\nExited cleanly.")
        return 0


def main() -> int:
    args = parse_args()
    return SophiaLive(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
