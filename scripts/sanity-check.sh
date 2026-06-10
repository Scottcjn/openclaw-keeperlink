#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Hits each integration in isolation and prints PASS/FAIL.
# Day-1 stub. Each section gets fleshed out as its kill-test passes.

set -uo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a; . ./.env; set +a
fi

pass=0
fail=0

note() {
  printf "\n── %s ──\n" "$1"
}

check() {
  local name="$1"; shift
  if "$@"; then
    printf "  ✅ %s\n" "$name"
    pass=$((pass+1))
  else
    printf "  ❌ %s\n" "$name"
    fail=$((fail+1))
  fi
}

note "Environment"
check "KEEPERHUB_API_KEY present" test -n "${KEEPERHUB_API_KEY:-}"
check "UNISWAP_API_KEY present"   test -n "${UNISWAP_API_KEY:-}"
check "ZEROG_PRIVATE_KEY present" test -n "${ZEROG_PRIVATE_KEY:-}"

note "Day-1 kill-tests (filled in as each lights up)"
echo "  ⏳ AXL cross-node echo       — task #3"
echo "  ⏳ KeeperHub hello-world tx  — task #2"
echo "  ⏳ Uniswap /quote round-trip — task #5 (blocked on Base ETH funding)"
echo "  ⏳ 0G testnet upload+verify  — task #4"

note "Result"
printf "  %d passed, %d failed\n" "$pass" "$fail"

if [[ $fail -gt 0 ]]; then exit 1; fi
exit 0
