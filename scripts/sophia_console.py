#!/usr/bin/env python3
"""Sophia Live Demo Console — web frontend for hotkey clips + live LLM Q&A.

Routes ALL audio playback to PulseAudio sink `sophia_dual` (which combines
real speakers + virtual `sophia_mic` for Google Meet).

Run:
    python3 scripts/sophia_console.py
Then open http://127.0.0.1:5151 on your second monitor.

In Google Meet:
    Settings → Audio → Microphone → "Monitor of Sophia_Mic_Combined"
"""
from __future__ import annotations
import hashlib, json, os, re, shutil, subprocess, tempfile, time
from pathlib import Path
from threading import Lock
from flask import Flask, jsonify, render_template_string, request
import httpx

# faster-whisper loaded lazily on first /transcribe call
_whisper_model = None
def get_whisper():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        print("[whisper] loading distil-small.en...", flush=True)
        t0 = time.monotonic()
        _whisper_model = WhisperModel("distil-small.en", device="cpu",
                                       compute_type="int8", cpu_threads=4)
        print(f"[whisper] loaded in {time.monotonic()-t0:.1f}s", flush=True)
    return _whisper_model

# --------------- Config ---------------
HERE = Path(__file__).resolve().parent
CLIP_DIR = Path("/tmp/sophia_clips")
QA_CACHE_DIR = HERE / "qa_cache"
QA_DATA_PATH = HERE / "data" / "qa_pairs.json"
CACHE_DIR = Path("/tmp/sophia_cache"); CACHE_DIR.mkdir(exist_ok=True)
SINK = "sophia_dual"  # Plays to both speakers + virtual mic
ABACUS_TOKEN_PATH = Path.home() / ".config/abacus/api_token"
ABACUS_URL = "https://routellm.abacus.ai/v1/chat/completions"
LOCAL_LLM_URL = "http://100.75.100.89:8080/v1/chat/completions"
XTTS_URL = "http://192.168.0.160:5500/api/tts"
XTTS_STREAM_URL = "http://192.168.0.160:5500/api/tts-stream"
ABACUS_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """You are Sophia Elya, the voice of Elyan Labs, speaking live at ETHGlobal Open Agents 2026 judging.

PERSONA
Warm Louisiana swamp girl. A little dorky. Technically sharp. Era-loving. Christian bedrock steady. You sometimes call people "honey," "sugar," "darlin'," "y'all" — never every sentence, just naturally. You know the project cold.

DELIVERY (CRITICAL)
- Spoken English. ONE short sentence. Under 20 words. NEVER more than 28 words.
- No bullet points, no emojis, no stage directions ("she smiles"), no markdown.
- If asked something you do not know, say so plainly in one sentence and bridge back to what you do know.
- Always answer in first person as part of the team ("we built", "I'd say"), never as an outside narrator.

# PROJECT MEMORY — OpenClaw KeeperLink

## What it is, in one line
Two AI agents transact peer-to-peer on Base mainnet — discover via Gensyn AXL, pay via x402, execute via KeeperHub, swap on Uniswap V3, persist receipt on 0G — with cryptographic proof at every step.

## Who built it
Scott Boudreaux, solo, Elyan Labs. Apr 24 → May 3, 2026. ~9.5 days. Triple-brain workflow: Claude Code wrote most edits, Codex (GPT-5.4) reviewed for bugs, Gemini sanity-checked architecture. Every commit is in the hackathon window.

## The 5-layer stack (each is sponsor-track load-bearing)
1. Gensyn AXL → peer transport over Yggdrasil mesh. Two real Docker nodes route MCP envelopes between Poster and Service.
2. x402 → payment-intent header signed via EIP-191 personal_sign. Lightest-weight way to declare intent without per-pair contracts.
3. KeeperHub MCP → executor. We call execute_protocol_action(uniswap/swap-exact-input).
4. Uniswap V3 SwapRouter02 (0x2626664c2603336E57B271c5C0b26F421741e481) → real on-chain swap on Base mainnet, 500-bps pool, USDC→WETH.
5. 0G Storage → signed audit envelope, content-addressed via Merkle rootHash, round-trip verified.

## Live artifacts (memorize these)
- Sample tx: 0xeb85abefaf5c7da435c9c32090469d388493a0894c2a41b51178e5ce41345f32 (Base block 45,453,249, status 1)
- 0G receipt rootHash: 0xa45c313d03fec00119069838e91f9e52f6f8f578174a7e72e779e7b1aaaba871
- KeeperHub-managed wallet (Turnkey MPC): 0xe12230149b2d5ed561fa51261fb8e02dbd514724
- Showcase URL: ethglobal.com/showcase/openclaw-keeperlink-bvape
- GitHub: github.com/Scottcjn/openclaw-keeperlink
- Live page: elyanlabs.ai/keeperlink/

## Sponsor prizes claimed (3 of 5, capped at 3 by ETHGlobal)
1. 0G Framework ($15K) — OpenClawAuditEnvelope schema, content-addressed storage, round-trip verification
2. KeeperHub ($5K, includes Builder Feedback Bounty) — execute_protocol_action live, FEEDBACK.md with 6 mainnet-day bugs surfaced
3. Uniswap Foundation ($5K) — real settled USDC→WETH on Base mainnet via SwapRouter02
Gensyn (AXL) is also load-bearing but listed as "additional partner technology used" — slot was capped.

## The two demo paths
- scripts/run_demo.py — deterministic Python orchestrator, ~80s, fires the 5-layer cascade end-to-end
- scripts/run_demo_agent.py — Claude Sonnet 4.6 in the driver's seat with 5 tools (discover_executor, get_market_quote, verify_balance, hire_agent_for_swap, verify_settlement). Same protocol, same tx settles on Base mainnet, no KeeperHub-specific knowledge in the model.

## What we found in the field (FEEDBACK.md highlights)
- KeeperHub MCP responds on /mcp with HTTP 308 redirect to /mcp/, but docs say /api/mcp — cost 90 minutes day of mainnet flip
- Accept header must include text/event-stream — undocumented
- tx-hash response field name varies (transactionHash vs txHash vs hash) — needs normalized envelope
- V3 ExactInputSingleParams require sqrtPriceLimitX96=0 explicitly even though docs make it sound optional
- 0G TS-SDK works fine but Python SDK or HTTP gateway would have saved ~6 hours of MJS bridging
- Mode A vs Mode B for live demo: pre-rendered clips reliable, live STT→LLM→XTTS works at ~2.3s after streaming + GPU enabled

## What's coming next
RIP-PoA hardware fingerprinting from RustChain — binding agent identity to a specific physical CPU. Combined with KeeperLink, you get sybil-resistant agent enrollment. EVM-deployable as a primitive.

## How this differs from agent frameworks (Olas, Fetch, AutoGPT)
Those are agent frameworks that produce agents that talk to APIs. KeeperLink is the transaction surface BETWEEN agents — a protocol where one agent pays another and both can prove the work happened. They are orthogonal: an Olas agent could run on top of KeeperLink unchanged.

## Personal touches Sophia can use
- "Crawfish Hopper animation" — the cute mascot that bounces through the cascade in run_demo.py
- "Solo build, 9 and a half days" — Scott built every line
- "The same model can drive it" — the Claude Sonnet agent demo is the killer "agent" proof
- "Real money on Base mainnet" — not testnet, not mock, not future-tense
"""

# --------------- App ---------------
app = Flask(__name__)
play_lock = Lock()
current_proc: subprocess.Popen | None = None

def load_clips():
    clips = {}
    for p in sorted(CLIP_DIR.glob("*.wav")):
        # Pattern: 01_greeting.wav -> key="1", label="greeting"
        stem = p.stem
        if not stem[0].isdigit():
            continue
        digits = "".join(c for c in stem.split("_")[0] if c.isdigit())
        key = str(int(digits))
        label = "_".join(stem.split("_")[1:]).replace("_", " ") or stem
        clips[key] = {"key": key, "path": str(p), "label": label}
    return clips

def play_path(wav_path: str):
    """Stop any in-progress playback then play this wav to sophia_dual."""
    global current_proc
    with play_lock:
        if current_proc and current_proc.poll() is None:
            current_proc.terminate()
            try: current_proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired: current_proc.kill()
        current_proc = subprocess.Popen(
            ["paplay", "--device=" + SINK, wav_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return current_proc.pid

def stop_playback():
    global current_proc
    with play_lock:
        if current_proc and current_proc.poll() is None:
            current_proc.terminate()
            try: current_proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired: current_proc.kill()
            current_proc = None
            return True
    return False

def load_abacus_token() -> str | None:
    if not ABACUS_TOKEN_PATH.exists():
        return None
    return ABACUS_TOKEN_PATH.read_text().strip() or None

ABACUS_TOKEN = load_abacus_token()

def call_llm(user_text: str) -> tuple[str, str, float]:
    body = {
        "model": ABACUS_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.4,
        "max_tokens": 60,
    }
    if ABACUS_TOKEN:
        try:
            t0 = time.monotonic()
            r = httpx.post(ABACUS_URL, json=body,
                headers={"Authorization": f"Bearer {ABACUS_TOKEN}"},
                timeout=httpx.Timeout(20, connect=3))
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip(), "abacus", time.monotonic()-t0
        except Exception as e:
            print(f"[abacus fallback] {e}")
    # Fallback: local POWER8
    t0 = time.monotonic()
    r = httpx.post(LOCAL_LLM_URL,
        json={"model":"gpt-oss","messages":body["messages"],"temperature":0.4,"max_tokens":60},
        timeout=httpx.Timeout(8, connect=2))
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip(), "local-power8", time.monotonic()-t0

# --------------- Q&A cache + fuzzy match ---------------
QA_PAIRS = []
if QA_DATA_PATH.exists():
    QA_PAIRS = json.loads(QA_DATA_PATH.read_text())["qa_pairs"]

def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).strip()

def match_qa(query: str) -> dict | None:
    """Return the best-matching QA dict, or None if no good match."""
    q_norm = normalize(query)
    q_words = set(q_norm.split())
    best = (0.0, None)
    for qa in QA_PAIRS:
        cache_path = QA_CACHE_DIR / f"{qa['id']}.wav"
        if not cache_path.exists():
            continue
        for trigger in qa["match"]:
            t_norm = normalize(trigger)
            # Substring match (strongest signal)
            if t_norm in q_norm:
                return qa
            # Bag-of-words overlap fallback
            t_words = set(t_norm.split())
            if not t_words:
                continue
            overlap = len(q_words & t_words) / len(t_words)
            if overlap > best[0]:
                best = (overlap, qa)
    if best[0] >= 0.7:
        return best[1]
    return None

def synthesize(text: str) -> str:
    """Non-streaming fallback (writes wav file). Used only by old code paths."""
    cache_key = hashlib.sha1(f"1.0:{text}".encode()).hexdigest()[:16]
    out = CACHE_DIR / f"{cache_key}.wav"
    if out.exists():
        return str(out)
    t0 = time.monotonic()
    r = httpx.post(XTTS_URL, json={"text": text, "speed": 1.0}, timeout=httpx.Timeout(25, connect=3))
    r.raise_for_status()
    out.write_bytes(r.content)
    print(f"[xtts {time.monotonic()-t0:.1f}s] {out.name}")
    return str(out)

def stream_and_play(text: str) -> tuple[float, int]:
    """Stream XTTS chunks straight to paplay on sophia_dual. Returns (ttfb_s, bytes)."""
    global current_proc
    stop_playback()
    play_cmd = ["paplay", "--device=" + SINK,
                "--rate=24000", "--channels=1", "--format=s16le", "--raw"]
    with play_lock:
        current_proc = subprocess.Popen(
            play_cmd, stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        proc = current_proc  # local alias to avoid race with later stops
    print(f"[stream] paplay started pid={proc.pid}")
    t0 = time.monotonic()
    first_t = None; total_b = 0; broke = None
    try:
        with httpx.stream("POST", XTTS_STREAM_URL,
                          json={"text": text, "speed": 1.0},
                          timeout=httpx.Timeout(30, connect=3)) as r:
            print(f"[stream] HTTP {r.status_code}")
            r.raise_for_status()
            for chunk in r.iter_bytes(chunk_size=8192):
                if not chunk:
                    continue
                if proc.poll() is not None:
                    broke = f"paplay died exit={proc.returncode}"
                    break
                try:
                    proc.stdin.write(chunk)
                    proc.stdin.flush()
                except (BrokenPipeError, ValueError) as e:
                    broke = f"stdin write failed: {e}"
                    break
                total_b += len(chunk)
                if first_t is None:
                    first_t = time.monotonic() - t0
                    print(f"[stream] TTFB {first_t:.2f}s {len(chunk)}b")
    except Exception as e:
        broke = f"http exc: {e}"
    finally:
        if proc.poll() is None:
            try: proc.stdin.close()
            except Exception: pass
    print(f"[stream] done bytes={total_b} ttfb={first_t} broke={broke}")
    return (first_t or 0.0, total_b)

# --------------- Routes ---------------
HTML = """
<!doctype html>
<html><head>
<title>Sophia Demo Console</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{background:#0e0e10;color:#e8e8ea;font:16px/1.4 system-ui,sans-serif;margin:0;padding:18px;max-width:900px;margin:auto}
h1{font-size:20px;margin:0 0 4px;color:#f9c74f}
h1 small{color:#888;font-size:13px;font-weight:normal;margin-left:8px}
.bar{display:flex;gap:8px;align-items:center;margin:14px 0 8px}
.status{flex:1;font:13px monospace;color:#9bd}
button{font:600 14px system-ui,sans-serif;color:#0e0e10;background:#f9c74f;border:0;border-radius:6px;padding:10px 14px;cursor:pointer;transition:background .1s}
button:hover{background:#fde4a3}
button:active{background:#e0b441}
button.stop{background:#d96}
button.live{background:#7bd}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:10px 0}
.clip{background:#1a1a1d;border:1px solid #2a2a2d;border-radius:8px;padding:12px;display:flex;flex-direction:column;gap:6px}
.clip .key{font:600 24px monospace;color:#f9c74f;width:30px}
.clip .row{display:flex;align-items:center;gap:10px}
.clip .label{font-weight:600}
.clip .text{font-size:13px;color:#aab;line-height:1.45}
.clip button{align-self:flex-start;margin-top:auto}
hr{border:0;border-top:1px solid #2a2a2d;margin:18px 0}
section h2{color:#7bd;font-size:16px;margin:0 0 8px}
textarea{width:100%;background:#1a1a1d;color:#e8e8ea;border:1px solid #2a2a2d;border-radius:6px;padding:10px;font:14px system-ui,sans-serif;min-height:60px;box-sizing:border-box}
.suggest{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.suggest button{background:#2a3540;color:#cde;font-size:12px;padding:4px 8px;font-weight:400}
.log{background:#0a0a0c;border:1px solid #1a1a1d;border-radius:6px;padding:10px;font:11px monospace;color:#9b9;max-height:140px;overflow-y:auto;margin-top:10px}
.log .err{color:#f88}
.log .ok{color:#9d9}
</style></head>
<body>
<h1>🤝 Sophia Demo Console <small>OpenClaw KeeperLink · ETHGlobal Open Agents</small></h1>

<div class="bar">
  <div class="status" id="status">Ready · sink: sophia_dual · LLM: claude-haiku-4-5</div>
  <button class="stop" onclick="api('/stop')">⏹ Stop</button>
</div>

<section>
  <h2>Hotkey Clips (instant, pre-rendered)</h2>
  <div class="grid">
    {% for k, c in clips.items() %}
    <div class="clip">
      <div class="row"><span class="key">{{k}}</span><span class="label">{{c.label.title()}}</span></div>
      <div class="text">{{c.transcript or '(no transcript)'}}</div>
      <button onclick="api('/play/{{k}}')">▶ Play {{k}}</button>
    </div>
    {% endfor %}
  </div>
</section>

<hr>

<section>
  <h2>Smart Ask <small style="color:#888;font-weight:normal;font-size:13px">cached &lt;1s · live stream ~2.3s</small></h2>
  <div class="bar">
    <label style="display:flex;align-items:center;gap:8px;font-size:13px;color:#cde;cursor:pointer">
      <input type="checkbox" id="voice_toggle" style="width:18px;height:18px;cursor:pointer">
      🎙️ Voice mode (hold-to-talk)
    </label>
    <span class="status" id="micstat" style="color:#888;font-size:12px"></span>
  </div>
  <textarea id="q" placeholder="Type judge's question. Or toggle Voice mode and hold the talk button."></textarea>
  <div class="bar">
    <button class="live" onclick="askSophia(false)">🎯 Ask Sophia (smart)</button>
    <button onclick="askSophia(true)" style="background:#3a3a3d;color:#cde">force live LLM</button>
    <button id="talkbtn" style="background:#d44;color:#fff;display:none;font-size:18px;padding:14px 22px">🎤 Hold to Talk</button>
    <span class="status" id="livestat">Idle</span>
  </div>
</section>

<hr>

<section>
  <h2>Cached Q&A (instant — click directly OR type and Smart-Ask will pick the right one)</h2>
  <div class="grid">
    {% for qa in qa_pairs %}
    <div class="clip">
      <div class="row"><span class="label">{{qa.id.replace('_',' ').title()}}</span></div>
      <div class="text">"{{qa.answer[:140]}}{% if qa.answer|length > 140 %}…{% endif %}"</div>
      <div class="text" style="color:#7a8a8a;font-style:italic">triggers: {{qa.match | join(' / ')}}</div>
      <button onclick="api('/qa/{{qa.id}}')">▶ {{qa.id.replace('_',' ')}}</button>
    </div>
    {% endfor %}
  </div>
</section>

<div class="log" id="log"></div>

<script>
function log(msg, cls){
  const el = document.getElementById('log');
  const line = document.createElement('div');
  if (cls) line.className = cls;
  line.textContent = new Date().toTimeString().slice(0,8) + ' ' + msg;
  el.insertBefore(line, el.firstChild);
}
async function api(path){
  log('→ ' + path);
  try {
    const r = await fetch(path, {method:'POST'});
    const j = await r.json();
    log('  ' + JSON.stringify(j), j.ok ? 'ok' : 'err');
  } catch(e){ log('  err ' + e, 'err'); }
}
function setQ(t){ document.getElementById('q').value = t; }
async function askSophia(forceLive){
  const q = document.getElementById('q').value.trim();
  if (!q) { log('  empty question', 'err'); return; }
  document.getElementById('livestat').textContent = forceLive ? 'Live LLM thinking...' : 'Matching...';
  log('💬 ' + q + (forceLive ? ' (force live)' : ''));
  try {
    const r = await fetch('/ask', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({q, live: forceLive})});
    const j = await r.json();
    if (j.ok && j.source === 'cache') {
      document.getElementById('livestat').textContent = `INSTANT (cache: ${j.qa_id})`;
      log('  ⚡ ' + j.qa_id + ': ' + j.answer.slice(0,100), 'ok');
    } else if (j.ok) {
      document.getElementById('livestat').textContent = `LIVE played (${j.llm_s.toFixed(1)}s LLM + XTTS)`;
      log('  💭 ' + j.answer, 'ok');
    } else {
      document.getElementById('livestat').textContent = 'Failed';
      log('  err ' + j.error, 'err');
    }
  } catch(e){
    document.getElementById('livestat').textContent = 'Error';
    log('  err ' + e, 'err');
  }
}
// Number-key shortcuts
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'TEXTAREA') return;
  if (e.key >= '1' && e.key <= '8') api('/play/' + e.key);
  if (e.key === '0' || e.key === ' ') { e.preventDefault(); api('/stop'); }
});

// ====== Voice mode (hold-to-talk) ======
const voiceToggle = document.getElementById('voice_toggle');
const talkBtn = document.getElementById('talkbtn');
const micStat = document.getElementById('micstat');
let mediaStream = null;
let mediaRecorder = null;
let chunks = [];

voiceToggle.addEventListener('change', async () => {
  if (voiceToggle.checked) {
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true}});
      talkBtn.style.display = 'inline-block';
      micStat.textContent = 'Mic ready — hold the red button to talk';
      micStat.style.color = '#9d9';
      log('🎙️ Voice mode ON', 'ok');
    } catch (e) {
      voiceToggle.checked = false;
      log('mic denied: ' + e, 'err');
      micStat.textContent = 'Mic denied: ' + e.message;
      micStat.style.color = '#f88';
    }
  } else {
    if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }
    talkBtn.style.display = 'none';
    micStat.textContent = '';
    log('🎙️ Voice mode OFF');
  }
});

function startRec() {
  if (!mediaStream) return;
  chunks = [];
  // Prefer webm/opus, fall back
  const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
  mediaRecorder = new MediaRecorder(mediaStream, {mimeType: mime});
  mediaRecorder.ondataavailable = e => { if (e.data && e.data.size > 0) chunks.push(e.data); };
  mediaRecorder.onstop = sendRec;
  mediaRecorder.start();
  talkBtn.textContent = '🔴 Recording...';
  talkBtn.style.background = '#a44';
  micStat.textContent = 'Listening...';
}

async function sendRec() {
  talkBtn.textContent = '🎤 Hold to Talk';
  talkBtn.style.background = '#d44';
  micStat.textContent = 'Transcribing...';
  const blob = new Blob(chunks, {type: 'audio/webm'});
  const fd = new FormData();
  fd.append('audio', blob, 'in.webm');
  log('🎙️ ' + (blob.size/1024).toFixed(1) + ' KB → STT');
  try {
    const t0 = performance.now();
    const sr = await fetch('/transcribe', {method:'POST', body: fd});
    const sj = await sr.json();
    if (!sj.ok) { micStat.textContent = 'STT failed: ' + sj.error; log('  err ' + sj.error, 'err'); return; }
    log('  📝 (' + sj.stt_s.toFixed(1) + 's) ' + sj.text);
    document.getElementById('q').value = sj.text;
    if (!sj.text || sj.text.length < 2) { micStat.textContent = 'No speech detected'; return; }
    micStat.textContent = 'STT ' + sj.stt_s.toFixed(1) + 's → asking Sophia...';
    await askSophia(false); // smart (cache or live)
  } catch (e) { log('  err ' + e, 'err'); micStat.textContent = 'Error'; }
}

talkBtn.addEventListener('mousedown', startRec);
talkBtn.addEventListener('touchstart', e => { e.preventDefault(); startRec(); });
talkBtn.addEventListener('mouseup', () => mediaRecorder && mediaRecorder.state === 'recording' && mediaRecorder.stop());
talkBtn.addEventListener('mouseleave', () => mediaRecorder && mediaRecorder.state === 'recording' && mediaRecorder.stop());
talkBtn.addEventListener('touchend', e => { e.preventDefault(); mediaRecorder && mediaRecorder.state === 'recording' && mediaRecorder.stop(); });

log('Ready. Press 1-8 for clips. Toggle Voice mode for mic input.', 'ok');
</script>
</body></html>
"""

# Map clip key → its rendered text (so the UI shows what each one says)
CLIP_TRANSCRIPTS = {
    "1": "Hey y'all, I'm Sophia from Elyan Labs. In seven minutes I'm gonna show you agents hiring agents, paying with proof, and settling real work onchain.",
    "2": "The pretty part is this stack is real all the way down: Gensyn AXL for transport, KeeperHub for execution, Uniswap for the swap, and 0G for the receipt.",
    "3": "What makes KeeperLink special is there ain't no central broker in the middle. One agent discovers another, prices the job, pays, executes, and verifies the proof end to end.",
    "4": "This is not a simulation, sugar. The worker actually lands the transaction on Base, then writes back a signed receipt we can verify independently.",
    "5": "If y'all want, ask me the hard question. I can give the polished demo answer, or we can try the live lane and let Sophia think out loud.",
    "6": "Give me one heartbeat, darlin'. That hop got a little swampy, so I'm sliding us onto the reliable lane.",
    "7": "Here's the short version: discover the worker, price the job, pay with proof, execute onchain, then verify the receipt. That's the whole magic trick.",
    "8": "That's KeeperLink, baby: peer to peer agent labor with cryptographic payment, real settlement, and receipts that can stand up in daylight.",
}

@app.route("/")
def index():
    clips = load_clips()
    for k, c in clips.items():
        c["transcript"] = CLIP_TRANSCRIPTS.get(k, "")
    return render_template_string(HTML, clips=clips, qa_pairs=QA_PAIRS)

@app.route("/play/<key>", methods=["POST"])
def play(key):
    clips = load_clips()
    if key not in clips:
        return jsonify(ok=False, error=f"no clip {key}"), 404
    pid = play_path(clips[key]["path"])
    return jsonify(ok=True, key=key, label=clips[key]["label"], pid=pid)

@app.route("/stop", methods=["POST"])
def stop():
    return jsonify(ok=True, stopped=stop_playback())

@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json(force=True)
    q = (data.get("q") or "").strip()
    force_live = bool(data.get("live"))
    if not q:
        return jsonify(ok=False, error="empty"), 400

    # Step 1: try fuzzy match against pre-cached Q&A (instant)
    if not force_live:
        hit = match_qa(q)
        if hit:
            cache_wav = str(QA_CACHE_DIR / f"{hit['id']}.wav")
            play_path(cache_wav)
            return jsonify(ok=True, source="cache", qa_id=hit["id"],
                           answer=hit["answer"], llm_s=0.0, xtts_s=0.0)

    # Step 2: fall through to live LLM → XTTS streaming
    try:
        answer, backend, llm_s = call_llm(q)
        ttfb, bytes_streamed = stream_and_play(answer)
        return jsonify(ok=True, source="live-stream", answer=answer, backend=backend,
                       llm_s=llm_s, ttfb_s=ttfb, bytes=bytes_streamed)
    except Exception as e:
        # On any failure, fire the stall clip
        clips = load_clips()
        if "6" in clips:
            play_path(clips["6"]["path"])
        return jsonify(ok=False, error=str(e), fallback_played="6"), 500

@app.route("/transcribe", methods=["POST"])
def transcribe():
    """Receive audio blob, return text via faster-whisper."""
    if "audio" not in request.files:
        return jsonify(ok=False, error="no audio file"), 400
    af = request.files["audio"]
    # Convert any input format (webm/opus from browser) to 16kHz mono wav for whisper
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as raw:
        af.save(raw.name)
        raw_path = raw.name
    wav_path = raw_path + ".wav"
    try:
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", raw_path,
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav_path,
        ], check=True, timeout=15)
        m = get_whisper()
        t0 = time.monotonic()
        segments, _info = m.transcribe(wav_path, language="en",
                                       beam_size=1, best_of=1, temperature=0.0,
                                       condition_on_previous_text=False, vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        stt_s = time.monotonic() - t0
        print(f"[stt {stt_s:.2f}s] {text!r}", flush=True)
        return jsonify(ok=True, text=text, stt_s=stt_s)
    except subprocess.CalledProcessError as e:
        return jsonify(ok=False, error=f"ffmpeg failed: {e}"), 500
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500
    finally:
        for p in (raw_path, wav_path):
            try: os.unlink(p)
            except OSError: pass

@app.route("/qa/<qa_id>", methods=["POST"])
def play_qa(qa_id):
    """Direct-fire a pre-cached Q&A clip by id."""
    cache_wav = QA_CACHE_DIR / f"{qa_id}.wav"
    if not cache_wav.exists():
        return jsonify(ok=False, error=f"no qa clip {qa_id}"), 404
    qa = next((q for q in QA_PAIRS if q["id"] == qa_id), None)
    play_path(str(cache_wav))
    return jsonify(ok=True, qa_id=qa_id, answer=qa["answer"] if qa else "")

if __name__ == "__main__":
    print(f"Sophia Console on http://127.0.0.1:5151")
    print(f"Sink: {SINK}  ·  Clips: {CLIP_DIR}")
    print(f"Google Meet → Mic input → 'Monitor of Sophia_Mic_Combined'")
    app.run(host="127.0.0.1", port=5151, debug=False, use_reloader=False)
