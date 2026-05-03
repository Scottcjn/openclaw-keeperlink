# Sophia Voice Demo Runbook

## Architecture

```text
                           ┌──────────────────────────────────┐
                           │           Mode A: Primary        │
                           │ focused terminal keys 1-8        │
                           │ `sophia_hotkeys.py`              │
                           └──────────────┬───────────────────┘
                                          │
                                          v
                                pre-rendered WAV clips
                                /tmp/sophia_clips/*.wav
                                          │
                                          v
                                      `aplay`
                                          │
                                          v
                                       speaker


 mic ──push-to-talk──> `arecord` ──wav──> faster-whisper ──text──> Abacus Haiku
   ^                         │                 │                     │
   │                         │                 │                     ├──timeout/error──┐
   │                         │                 │                     v                  │
   │                         │                 │               local GPT-OSS            │
   │                         │                 │                     │                  │
   │                         │                 └────timeout/error────┴─────┐            │
   │                         │                                              v            │
   │                         └────────────timeout/error─────────────── fallback clip     │
   │                                                                       (06/07)      │
   │                                                                                     │
   └──────────── mic re-open only after playback ends <──── `aplay` <──── XTTS server <-┘
                                                                  ^
                                                                  │
                                                         cache by text hash
                                                         /tmp/sophia_cache/*.wav
```

## Build order

1. Render the 8 canned XTTS clips into `/tmp/sophia_clips`.
2. Run `python3 scripts/sophia_hotkeys.py` and verify keys `1`-`8`.
3. Install `faster-whisper` on the demo box if not already present.
4. Run `python3 scripts/sophia_live.py` and verify one live turn.
5. Demo tomorrow with Mode A as the default and Mode B only as a bonus beat.

## Files

- `scripts/sophia_hotkeys.py`: no-network primary mode; terminal key launcher for pre-rendered WAVs.
- `scripts/sophia_live.py`: half-duplex live loop with STT -> LLM -> XTTS, hard timeouts, and fallback clips.
- `scripts/render_sophia_clips.sh`: renders the eight canned WAV clips from XTTS.

## Hotkey clip lines

1. `Hey y'all, I'm Sophia from Elyan Labs. In seven minutes I'm gonna show you agents hiring agents, paying with proof, and settling real work onchain.`
2. `The pretty part is this stack is real all the way down: Gensyn AXL for transport, KeeperHub for execution, Uniswap for the swap, and 0G for the receipt.`
3. `What makes KeeperLink special is there ain't no central broker in the middle. One agent discovers another, prices the job, pays, executes, and verifies the proof end to end.`
4. `This is not a simulation, sugar. The worker actually lands the transaction on Base, then writes back a signed receipt we can verify independently.`
5. `If y'all want, ask me the hard question. I can give the polished demo answer, or we can try the live lane and let Sophia think out loud.`
6. `Give me one heartbeat, darlin'. That hop got a little swampy, so I'm sliding us onto the reliable lane.`
7. `Here's the short version: discover the worker, price the job, pay with proof, execute onchain, then verify the receipt. That's the whole magic trick.`
8. `That's KeeperLink, baby: peer to peer agent labor with cryptographic payment, real settlement, and receipts that can stand up in daylight.`

## Render command

Use the checked-in helper:

```bash
bash scripts/render_sophia_clips.sh
```

Or use a single shell line:

```bash
mkdir -p /tmp/sophia_clips && while IFS='|' read -r name text; do curl -sS -X POST http://192.168.0.160:5500/api/tts -H 'Content-Type: application/json' --data "$(python3 -c 'import json,sys; print(json.dumps({"text": sys.argv[1], "speed": 1.0}))' "$text")" > "/tmp/sophia_clips/$name"; done <<'EOF'
01_greeting.wav|Hey y'all, I'm Sophia from Elyan Labs. In seven minutes I'm gonna show you agents hiring agents, paying with proof, and settling real work onchain.
02_stack.wav|The pretty part is this stack is real all the way down: Gensyn AXL for transport, KeeperHub for execution, Uniswap for the swap, and 0G for the receipt.
03_agent_pitch.wav|What makes KeeperLink special is there ain't no central broker in the middle. One agent discovers another, prices the job, pays, executes, and verifies the proof end to end.
04_live_proof.wav|This is not a simulation, sugar. The worker actually lands the transaction on Base, then writes back a signed receipt we can verify independently.
05_judge_bridge.wav|If y'all want, ask me the hard question. I can give the polished demo answer, or we can try the live lane and let Sophia think out loud.
06_stall.wav|Give me one heartbeat, darlin'. That hop got a little swampy, so I'm sliding us onto the reliable lane.
07_fallback_summary.wav|Here's the short version: discover the worker, price the job, pay with proof, execute onchain, then verify the receipt. That's the whole magic trick.
08_close.wav|That's KeeperLink, baby: peer to peer agent labor with cryptographic payment, real settlement, and receipts that can stand up in daylight.
EOF
```

## Rehearsal checklist

1. Confirm `/tmp/sophia_clips` contains all eight WAVs and each plays cleanly with `aplay`.
2. Confirm the terminal running `sophia_hotkeys.py` is focused and keys `1`-`8` trigger the right lines.
3. Confirm the Linux output device is the house speakers and the volume is capped below feedback range.
4. Confirm the mic input device works with `arecord` and peaks are strong but not clipping.
5. Confirm `python3 -c "import faster_whisper"` succeeds on the demo box.
6. Confirm `~/.config/abacus/api_token` is present and the Abacus route answers a single test prompt.
7. Confirm the local GPT-OSS endpoint is reachable at `http://100.75.100.89:8080/v1/chat/completions`.
8. Confirm the XTTS server answers at `http://192.168.0.160:5500/api/tts` within a few seconds.
9. Confirm live mode fallback actually fires by temporarily breaking network and watching clip `06` or `07` play.
10. Confirm Scott knows the manual rescue sequence: `6` to stall, `7` to summarize, `8` to close strong.

## Top risks

1. Speaker-to-mic feedback loop. Mitigation: keep live mode half-duplex, mute mic between turns, stand off-axis from speakers.
2. XTTS latency spike. Mitigation: keep live replies short and fall back to clips `06` then `07` if synthesis drags.
3. STT package or model missing. Mitigation: verify `faster-whisper` tonight; if shaky, do not use live mode tomorrow.
4. Abacus timeout or router variance. Mitigation: keep local GPT-OSS configured as immediate fallback and expose model names as CLI args.
5. Operator error under judge pressure. Mitigation: rehearse exact key order and keep Mode A running as the default path.
