#!/bin/bash
# SPDX-License-Identifier: MIT
# Tear down sophia audio routing modules.
set +e
for mod in module-combine-sink module-loopback module-null-sink; do
    pactl list modules | awk -v mod="$mod" '
        $1 == "Module" { id=$2 }
        /Name: / && $2 == mod { name=$2 }
        /Argument: / { args=$0; if (name == mod && args ~ /sophia/) print id }
        /^$/ { name=""; args="" }
    ' | tr -d '#' | while read id; do
        echo "unload module #$id ($mod)"
        pactl unload-module "$id"
    done
done
echo "Done. Verify:"
pactl list sinks short | grep -E "sophia" || echo "  no sophia sinks (clean)"
