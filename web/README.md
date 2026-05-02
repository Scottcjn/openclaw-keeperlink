# OpenClaw KeeperLink — frontend

Single-page polished landing for the project. No build step, no JS framework, no asset directory — just one HTML file that pulls Tailwind via CDN and embeds the YouTube videos.

## View it

```bash
# Locally (any static server)
cd web && python3 -m http.server 8765
# → http://localhost:8765/index.html

# Or push to GitHub Pages: enable Pages on the gh-pages branch with web/ as the source.
```

## What's in it

- Hero with project tagline + 5 sponsor-track badges
- Embedded canonical demo video (38s, Sophia narration)
- Inline SVG architecture diagram showing all 5 layers
- Embedded live LLM agent addendum (40s, Claude tool-use trace)
- Live artifacts grid: Base mainnet tx, 0G rootHash, KH wallet, Node B identity (click any value to copy)
- "Run it yourself" 3-step
- "Why this matters" pitch
- Links to PROTOCOL.md / ARCHITECTURE.md / FEEDBACK.md

## Design

- Dark mode, serif body type, mono for hashes/code
- Amber (`#FFB347`) for headings, teal (`#5EEAD4`) for live artifacts
- Grid background, subtle box-shadow glows, no images required

## Hosting

Currently no live URL — file is static and self-contained. Could ship to:
- GitHub Pages (`gh-pages` branch, web/ as source)
- Cloudflare Pages / Vercel / Netlify (drop the `web/` folder)
- Or just `python3 -m http.server` for the demo
