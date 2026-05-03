# OpenClaw KeeperLink — Live Judging Script (4-min demo + 3-min Q&A)

**Slot:** Mon May 4 2026, 11am CT (16:00 UTC)
**Format:** 4 min demo + 3 min Q&A
**Build:** solo, Scott Boudreaux, Elyan Labs

This script is what you'll loosely paraphrase. Don't read it word-for-word — judges can hear that. The Sophia interjections are *cues* to fire either a hotkey clip (instant) or a live turn (15-25s).

---

## Pre-flight (do 2 min before going live)

- [ ] Browser tabs pre-opened in this order: Showcase URL · Basescan tx · 0G receipt rootHash · GitHub repo · `elyanlabs.ai/keeperlink/`
- [ ] Terminal 1: `python3 scripts/sophia_hotkeys.py` running, focused, ready to fire 1-8
- [ ] Terminal 2 (optional/stretch): `python3 scripts/sophia_live.py` running for typed Q&A
- [ ] Terminal 3: `cd ~/openclaw-keeperlink && python3 scripts/run_demo.py` ready (don't run yet)
- [ ] Mic level checked, speakers below feedback threshold
- [ ] Phone on silent, second monitor showing this script

---

## 0:00 – 0:25 — Opening (25s)

**You say:**

> "Hey y'all. I'm Scott from Elyan Labs, solo build. I'm gonna show you OpenClaw KeeperLink — two AI agents transacting peer-to-peer on Base mainnet. No middleman. Real on-chain settlement. Cryptographic proof at every step."

**[Press `1`]** Sophia greeting auto-plays:
> "Hey y'all, I'm Sophia from Elyan Labs. In seven minutes I'm gonna show you agents hiring agents, paying with proof, and settling real work onchain."

---

## 0:25 – 1:10 — The Stack (45s)

**You say** (gesture at architecture diagram in showcase tab):

> "The stack is five layers, all real, all load-bearing. Gensyn AXL for transport. x402 for the payment intent header. KeeperHub MCP for execution. Uniswap V3 on Base for the actual swap. 0G storage for the signed receipt. Each layer has a sponsor track behind it."

**[Press `2`]** Sophia stack:
> "The pretty part is this stack is real all the way down: Gensyn AXL for transport, KeeperHub for execution, Uniswap for the swap, and 0G for the receipt."

---

## 1:10 – 2:30 — The Demo (80s)

**You say** (switch to terminal 3, run `python3 scripts/run_demo.py`):

> "Let me show you the deterministic version first. Watch this."

*[Demo runs — discovery, x402 sign, KH dispatch, on-chain wait, receipt, 0G upload, round-trip verify. ~80s.]*

**At ~1:30 (cascade visible):** **[Press `3`]** Sophia agent pitch:
> "What makes KeeperLink special is there ain't no central broker in the middle..."

**At ~2:00 (on-chain settlement):** **[Press `4`]** Sophia live proof:
> "This is not a simulation, sugar. The worker actually lands the transaction on Base..."

**At ~2:25 (receipt arrives):** Switch to Basescan tab.
> "Here's the tx on Basescan, block 45,453,249. USDC went out, WETH came back. Real money on Base mainnet."

Switch to 0G receipt tab. Show the rootHash. *(Skip if running long.)*

---

## 2:30 – 3:30 — The LLM Agent (60s)

**You say** (switch to terminal, run `python3 scripts/run_demo_agent.py`):

> "Now the same protocol — but driven by Claude Sonnet 4.6 with no special knowledge of any of this. Just five tools. Watch the model reason and call them live."

*[Agent demo runs — discover_executor, get_market_quote, verify_balance, hire_agent_for_swap, verify_settlement. Claude's reasoning shows live in the terminal. ~60s.]*

**Talk over it:**

> "Notice the model is actually deciding. It quotes Uniswap, checks the wallet has USDC, only then hires the executor. That's the agent surface validating itself — not a script with hardcoded steps."

---

## 3:30 – 3:55 — The Wow (25s)

**You say:**

> "And here's the thing — Sophia, my agent here, can answer questions about all this in real time. Watch."

**[Switch to Terminal 2, type a question and Enter]**

Suggested test question to type:
> *"In one sentence, why is x402 the right payment surface for agent jobs?"*

*[Sophia thinks for 15-20 sec, responds in her own voice. While she's thinking, you can say:]*

> "She's running through Whisper → Claude Haiku → XTTS, all of it open-source, all of it on infrastructure I control. Same agent thesis as the demo: no broker, no middleman."

---

## 3:55 – 4:00 — Close (5s)

**[Press `8`]** Sophia close:
> "That's KeeperLink, baby: peer to peer agent labor with cryptographic payment, real settlement, and receipts that can stand up in daylight."

**You say:**
> "Questions?"

---

# 3-Minute Q&A — Predicted Questions

## Q1: "What inspired your project?"

> "I built RustChain, our own L1 with hardware-bound consensus. The problem I kept running into: how do agents *hire each other* without trusting a central broker? Existing 'agent marketplaces' fake the hard parts — centralized brokers, manual receipts, silent failures. KeeperLink is what happens when every layer has to be real or the whole thing breaks."

## Q2: "What tools did you use, and why?"

> "Five sponsor stacks load-bearing. AXL because Yggdrasil mesh is the only credible peer transport. x402 because EIP-191 personal_sign is the lightest-weight way to declare a payment intent without a contract per pair. KeeperHub MCP because their executor surface is genuinely agent-drivable — I demoed that with the LLM run. Uniswap V3 because Base mainnet is where real liquidity lives. 0G because content-addressed Merkle storage gives you tamper-proof receipts for free."

## Q3: "What challenges did you solve?"

> "Six mainnet-day bugs, all in FEEDBACK.md. The killer was KeeperHub's MCP responds on `/mcp` with HTTP 308 redirect to `/mcp/`, but their docs say `/api/mcp`. Cost me 90 minutes the day of the mainnet flip. There's also a subtle V3 SwapRouter02 trap — `sqrtPriceLimitX96=0` has to be passed explicitly even though the docs make it sound optional. The whole §2.10 of FEEDBACK.md is the bug-hunt log."

## Q4: "How is this different from [Olas / Fetch / autonomous agent X]?"

> "Those are agent *frameworks*. KeeperLink is the *transaction surface* between agents. They produce agents that talk to APIs; I produced a protocol where one agent pays another and both can prove the work happened. They're orthogonal — you could run an Olas agent on top of KeeperLink and it'd Just Work."

## Q5: "What's next?"

> "RIP-PoA hardware fingerprinting from RustChain — binding agent identity to a specific physical CPU. Combined with KeeperLink, you get sybil-resistant agent enrollment. EVM-deployable as a primitive. The submission's roadmap section has the full plan."

## Q6: "How long did this take you?"

> "Apr 24 to May 3, solo, ~9.5 days. Every commit is in the hackathon window. Triple-brain workflow: Claude Code wrote most edits, Codex reviewed for bugs, Gemini sanity-checked the architecture."

---

# Hotkey Reference Card

| Key | Clip | When to fire |
|---|---|---|
| `1` | Greeting | Start of demo |
| `2` | Stack | After your "five layers" line |
| `3` | Agent pitch | During cascade animation |
| `4` | Live proof | On-chain settlement beat |
| `5` | Judge bridge | Before Q&A or live Sophia |
| `6` | Stall ("one heartbeat") | If anything is slow / dead air |
| `7` | Fallback summary | If demo breaks — gives you the elevator pitch in Sophia voice |
| `8` | Close | End of demo |
| `0` | Stop playback | If a clip needs interrupting |
| `q` | Quit | Don't press during judging |

# Mode B (Live Sophia) — Use Sparingly

Type a question and Enter. Takes 15-25s end-to-end (Whisper STT 1-2s, Haiku 1-2s, XTTS 12-18s, playback 4-5s).

**Use only at the dedicated 3:30 wow moment** unless time permits more. If she stalls past 25s, hit `6` (the stall clip) immediately — judges hear "one heartbeat darlin'" and you've covered the dead air.

---

# Risk Register (top 5)

1. **Sophia voice doesn't fire.** Mitigation: `7` (fallback summary) gives the elevator pitch verbally without needing the script.
2. **`run_demo.py` errors live.** Mitigation: showcase tab has the recorded video; switch to it and narrate over it. Hit `4` for the "real proof" clip while you scrub forward.
3. **Mic feedback into Sophia output.** Mitigation: speaker volume below feedback threshold (set BEFORE going live), Mode B is half-duplex (mic only opens on Enter).
4. **Abacus router 5xx.** Mitigation: `sophia_live.py` falls through to local POWER8 GPT-OSS automatically. If both fail, fallback clip plays.
5. **Network dies entirely.** Mitigation: hotkey clips are fully local. Demo videos are on showcase. You can deliver the whole story without internet — just give the talk + fire clips.
