#!/bin/bash
# Sophia Audio Routing — setup virtual mic for Google Meet demo
#
# Creates:
#   sophia_mic        — null-sink that Google Meet selects as MIC input
#   sophia_dual       — combine-sink: clips play to both speakers AND sophia_mic
#   loopback module   — your real mic also flows into sophia_mic
#
# Run once after each reboot. Idempotent (skips if modules already loaded).
# Tear down with: scripts/sophia_audio_teardown.sh
set -e

MIC_SOURCE="${MIC_SOURCE:-alsa_input.pci-0000_05_00.6.HiFi__Mic1__source}"
SPEAKER_SINK="${SPEAKER_SINK:-alsa_output.pci-0000_05_00.6.HiFi__Speaker__sink}"

# Idempotent: skip if sophia_mic already exists
if pactl list sinks short | grep -q '^[0-9]*[[:space:]]sophia_mic[[:space:]]'; then
    echo "sophia_mic already loaded — skipping null-sink"
else
    SINK_ID=$(pactl load-module module-null-sink \
        sink_name=sophia_mic \
        sink_properties="device.description=Sophia_Mic_Combined")
    echo "Loaded null-sink sophia_mic id=$SINK_ID"
fi

# Loopback real mic into sophia_mic
if pactl list modules short | grep -q "module-loopback.*source=$MIC_SOURCE.*sink=sophia_mic"; then
    echo "Mic loopback already loaded — skipping"
else
    LOOP_ID=$(pactl load-module module-loopback \
        source="$MIC_SOURCE" \
        sink=sophia_mic \
        latency_msec=20)
    echo "Loaded loopback id=$LOOP_ID  ($MIC_SOURCE → sophia_mic)"
fi

# Combined sink: speakers + sophia_mic
if pactl list sinks short | grep -q '^[0-9]*[[:space:]]sophia_dual[[:space:]]'; then
    echo "sophia_dual already loaded — skipping"
else
    COMBINE_ID=$(pactl load-module module-combine-sink \
        sink_name=sophia_dual \
        slaves="$SPEAKER_SINK,sophia_mic" \
        sink_properties="device.description=Sophia_Dual_Speakers_and_Mic")
    echo "Loaded combine-sink sophia_dual id=$COMBINE_ID"
fi

echo
echo "=== Verify ==="
pactl list sinks short | grep -E "sophia"
pactl list sources short | grep -E "sophia"
echo
echo "Next: open http://127.0.0.1:5151 (sophia_console.py)"
echo "      Google Meet → Settings → Mic → 'Monitor of Sophia_Mic_Combined'"
