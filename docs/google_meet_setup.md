# Google Meet + Sophia Console — operator setup

This is the Mon May 4 11am CT live-judging stack. Both your real voice and Sophia's voice flow through one virtual mic that Google Meet picks up.

## Diagram

```
   Your real mic ────┐
                     ├──►  sophia_mic  ──► sophia_mic.monitor ──► Google Meet (mic input)
   Sophia clips/LLM ─┴──►  sophia_dual ──┘
                          │
                          └──► your speakers (so you hear what plays)
```

## One-time per boot

```bash
cd ~/openclaw-keeperlink
./scripts/sophia_audio_setup.sh        # creates sophia_mic + sophia_dual + mic loopback
./scripts/.venv-sophia/bin/python scripts/sophia_console.py &   # web UI on :5151
```

If the venv isn't where you expect:
```bash
.venv-sophia/bin/python scripts/sophia_console.py &
```

## Browser tabs to open before judging

1. **Sophia Console**: `http://127.0.0.1:5151` (drag to second monitor)
2. **Google Meet**: the judging room URL (keep on primary monitor; this is your share screen)
3. **Demo support tabs** (the ones you'll show in the demo):
   - Showcase: `https://ethglobal.com/showcase/openclaw-keeperlink-bvape`
   - Basescan tx: `https://basescan.org/tx/0xeb85abefaf5c7da435c9c32090469d388493a0894c2a41b51178e5ce41345f32`
   - GitHub repo: `https://github.com/Scottcjn/openclaw-keeperlink`
   - Live page: `https://elyanlabs.ai/keeperlink/`

## Google Meet — Audio settings

In Meet:

1. **Settings (⚙) → Audio**
2. **Microphone** dropdown → select **"Monitor of Sophia_Mic_Combined"**
3. **Speakers** dropdown → leave on default (your headphones/speakers)
4. **Test mic level**: speak into your laptop mic → meter should bounce
5. **Test Sophia level**: in Sophia Console, click clip 1 → meter should bounce again

If Meet says "no input detected" → re-run `./scripts/sophia_audio_setup.sh` (modules might have unloaded).

## During the demo

- Press number keys `1`-`8` while focused on the Sophia Console tab → fires that hotkey clip instantly
- Type a question into the live Sophia textarea + click "Ask Sophia →" → ~17s round-trip
- Click "Stop" or hit `0` / spacebar to interrupt any playback

## Tear-down (after judging)

```bash
./scripts/sophia_audio_teardown.sh
```

## Troubleshooting

**Meet doesn't see "Sophia_Mic_Combined" as an option:**
- Re-run `./scripts/sophia_audio_setup.sh`
- In Meet, click the device dropdown to refresh, then look for "Monitor of sophia_mic" or "Monitor of Sophia_Mic_Combined"

**Mic loopback not capturing your voice (RMS = 0):**
- Find your real mic name: `pactl list sources short | grep -i input`
- Re-run setup with override: `MIC_SOURCE=alsa_input.<your-actual-mic> ./scripts/sophia_audio_setup.sh`

**Sophia's voice plays on speakers but Meet doesn't hear her:**
- Confirm console is using `paplay --device=sophia_dual` (it is — see sophia_console.py SINK constant)
- Verify `sophia_dual` slaves include `sophia_mic`: `pactl list sinks | grep -A 5 sophia_dual`

**Latency is bad on Sophia's voice in Meet (echo, lag):**
- The PipeWire chain adds ~50ms. If it's worse, lower loopback latency:
  `pactl unload-module $(pactl list modules | grep -B 2 'sink=sophia_mic' | head -1 | awk '{print $2}'); pactl load-module module-loopback source=$MIC_SOURCE sink=sophia_mic latency_msec=10`

**Sophia voice cuts off mid-sentence:**
- The console fires a new clip immediately on click — kills the previous one. Wait until current finishes before clicking next.

## Sound check 60 seconds before going live

1. Speak normally → confirm your voice reaches Meet (look at meter for other participant if there is one, or use Meet's self-preview)
2. Click clip 1 in console → confirm Sophia voice also reaches Meet
3. Click clip 6 (the stall clip) → confirm interrupt works (use this DURING demo if anything is taking too long)
4. Type a question + Ask Sophia → confirm full round-trip works (~17s)
