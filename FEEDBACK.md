# Builder Feedback — Uniswap + KeeperHub

> Honest, specific, reproducible notes from building OpenClaw KeeperLink during ETHGlobal Open Agents (Apr 24 – May 3, 2026). One file satisfies both Uniswap track qualification and the KeeperHub Builder Feedback Bounty.

**Solo builder:** Scott Boudreaux / Elyan Labs
**Build environment:** Ubuntu 25.10, Python 3.13, Node 22 (POWER8 + x86 mix)
**Time-boxed:** ~9.5 days, all integrations new to this builder

---

## Section 1 — Uniswap Trading API integration

*Filled in during build. Sections below are placeholders to be replaced with real friction notes as integration proceeds.*

### 1.1 First impressions / dashboard signup
*[TBD — will record on Day 1 when fetching API key from developers.uniswap.org/dashboard]*

### 1.2 `/quote` endpoint
*[TBD — Day 1 kill-test]*

### 1.3 `/swap` endpoint + execution path
*[TBD]*

### 1.4 SDK vs raw API
*[TBD]*

### 1.5 Documentation gaps encountered
*[TBD]*

### 1.6 What worked well
*[TBD]*

### 1.7 Suggested improvements
*[TBD]*

---

## Section 2 — KeeperHub integration

### 2.1 Account setup + API key provisioning
**Apr 18, 2026** — Signed up via GitHub OAuth (Scottcjn). Default org auto-created. Generating an API key was straightforward; key format `kh_` + 35 chars stored to `~/.config/keeperhub/keys.json` with `0600` permissions. Wallet auto-provisioned via Turnkey MPC integration with the email I supplied. Address came back within the same session.

**Friction:** None at signup.
**Suggestion:** A "you've created your first wallet — fund it on these networks" UX nudge would help newcomers know they need to top up before the API works for state-changing calls.

### 2.2 Direct Execution API
*[TBD — Day 1 hello-world will be a self-transfer or no-op contract call to validate the surface]*

### 2.3 MCP server (`https://app.keeperhub.com/mcp`)
*[TBD — will hit `tools/list` first to confirm transport, then `ai_generate_workflow` for the natural-language demo path]*

### 2.4 Native plugins (Uniswap, Aerodrome)
*[TBD]*

### 2.5 x402 integration
*[TBD]*

### 2.6 Documentation gaps encountered
*[TBD]*

### 2.7 What worked well
*[TBD]*

### 2.8 Suggested improvements
*[TBD]*

---

## Reproducibility notes

All integration tests in this build are reproducible from a fresh clone:

```bash
git clone https://github.com/Scottcjn/openclaw-keeperlink
cd openclaw-keeperlink
cp .env.example .env  # fill in real keys
./scripts/sanity-check.sh
```

`sanity-check.sh` hits each integration point in isolation and prints pass/fail. See `docs/demo.md` for the end-to-end orchestration.
