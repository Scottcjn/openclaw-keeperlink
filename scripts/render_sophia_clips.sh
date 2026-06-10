#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail

XTTS_URL="${XTTS_URL:-http://192.168.0.160:5500/api/tts}"
OUT_DIR="${OUT_DIR:-/tmp/sophia_clips}"
SPEED="${SPEED:-1.0}"

mkdir -p "$OUT_DIR"

render() {
  local filename="$1"
  local text="$2"
  local payload
  payload="$(python3 - "$text" "$SPEED" <<'PY'
import json
import sys
print(json.dumps({"text": sys.argv[1], "speed": float(sys.argv[2])}))
PY
)"
  curl -sS -X POST "$XTTS_URL" \
    -H 'Content-Type: application/json' \
    --data "$payload" \
    > "$OUT_DIR/$filename"
  printf 'rendered %s\n' "$OUT_DIR/$filename"
}

render "01_greeting.wav" "Hey y'all, I'm Sophia from Elyan Labs. In seven minutes I'm gonna show you agents hiring agents, paying with proof, and settling real work onchain."
render "02_stack.wav" "The pretty part is this stack is real all the way down: Gensyn AXL for transport, KeeperHub for execution, Uniswap for the swap, and 0G for the receipt."
render "03_agent_pitch.wav" "What makes KeeperLink special is there ain't no central broker in the middle. One agent discovers another, prices the job, pays, executes, and verifies the proof end to end."
render "04_live_proof.wav" "This is not a simulation, sugar. The worker actually lands the transaction on Base, then writes back a signed receipt we can verify independently."
render "05_judge_bridge.wav" "If y'all want, ask me the hard question. I can give the polished demo answer, or we can try the live lane and let Sophia think out loud."
render "06_stall.wav" "Give me one heartbeat, darlin'. That hop got a little swampy, so I'm sliding us onto the reliable lane."
render "07_fallback_summary.wav" "Here's the short version: discover the worker, price the job, pay with proof, execute onchain, then verify the receipt. That's the whole magic trick."
render "08_close.wav" "That's KeeperLink, baby: peer to peer agent labor with cryptographic payment, real settlement, and receipts that can stand up in daylight."
