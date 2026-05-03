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
import hashlib, json, os, shutil, subprocess, time
from pathlib import Path
from threading import Lock
from flask import Flask, jsonify, render_template_string, request
import httpx

# --------------- Config ---------------
CLIP_DIR = Path("/tmp/sophia_clips")
CACHE_DIR = Path("/tmp/sophia_cache"); CACHE_DIR.mkdir(exist_ok=True)
SINK = "sophia_dual"  # Plays to both speakers + virtual mic
ABACUS_TOKEN_PATH = Path.home() / ".config/abacus/api_token"
ABACUS_URL = "https://routellm.abacus.ai/v1/chat/completions"
LOCAL_LLM_URL = "http://100.75.100.89:8080/v1/chat/completions"
XTTS_URL = "http://192.168.0.160:5500/api/tts"
ABACUS_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """You are Sophia, the voice of Elyan Labs.
Persona: warm Louisiana swamp girl, a little dorky, technically sharp, era-loving, Christian bedrock steady.
Delivery: spoken English. ONE short sentence. Under 20 words. NEVER more than 28 words. No bullet points, no emojis, no stage directions.
If a question is unclear, answer plainly and bridge back to the demo.

Project facts:
- OpenClaw KeeperLink lets one agent hire another directly over Gensyn AXL.
- The worker gets paid with an x402-style payment proof, executes through KeeperHub, performs the swap on Uniswap V3 on Base mainnet, and stores the signed receipt on 0G.
- The full proof loop is discover -> price -> pay -> execute -> receipt -> verify.
- Built solo by Scott Boudreaux at Elyan Labs in 9.5 days for ETHGlobal Open Agents 2026.
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

def synthesize(text: str) -> str:
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
  <h2>Live Sophia (LLM → XTTS, ~17s)</h2>
  <textarea id="q" placeholder="Type a question for Sophia..."></textarea>
  <div class="suggest">
    <button onclick="setQ('Why is x402 the right payment surface for agent jobs?')">x402 why</button>
    <button onclick="setQ('How does the agent verify the swap actually settled?')">verify swap</button>
    <button onclick="setQ('What problem does KeeperLink solve that existing agent platforms do not?')">vs others</button>
    <button onclick="setQ('In one sentence, what is the role of 0G in this system?')">0G role</button>
    <button onclick="setQ('How long did this take to build?')">build time</button>
  </div>
  <div class="bar">
    <button class="live" onclick="askSophia()">🎤 Ask Sophia →</button>
    <span class="status" id="livestat">Idle</span>
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
async function askSophia(){
  const q = document.getElementById('q').value.trim();
  if (!q) { log('  empty question', 'err'); return; }
  document.getElementById('livestat').textContent = 'Thinking...';
  log('💬 ' + q);
  try {
    const r = await fetch('/ask', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({q})});
    const j = await r.json();
    document.getElementById('livestat').textContent = j.ok ? `Played (${j.llm_s.toFixed(1)}s + ${j.xtts_s.toFixed(1)}s)` : 'Failed';
    log('  💭 ' + (j.answer || j.error), j.ok ? 'ok' : 'err');
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
log('Ready.', 'ok');
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
    return render_template_string(HTML, clips=clips)

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
    if not q:
        return jsonify(ok=False, error="empty"), 400
    try:
        answer, backend, llm_s = call_llm(q)
        wav = synthesize(answer)
        play_path(wav)
        return jsonify(ok=True, answer=answer, backend=backend, llm_s=llm_s, xtts_s=0.0, wav=wav)
    except Exception as e:
        # On any failure, fire the stall clip
        clips = load_clips()
        if "6" in clips:
            play_path(clips["6"]["path"])
        return jsonify(ok=False, error=str(e), fallback_played="6"), 500

if __name__ == "__main__":
    print(f"Sophia Console on http://127.0.0.1:5151")
    print(f"Sink: {SINK}  ·  Clips: {CLIP_DIR}")
    print(f"Google Meet → Mic input → 'Monitor of Sophia_Mic_Combined'")
    app.run(host="127.0.0.1", port=5151, debug=False, use_reloader=False)
