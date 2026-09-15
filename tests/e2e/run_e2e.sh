#!/usr/bin/env bash
# End-to-end voice runs against real GPT-Live and real Claude (haiku) in a throwaway sandbox.
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT=tests/e2e/out
ROOT=$(mktemp -d)/projects
mkdir -p "$OUT" "$ROOT/jarvis-sandbox"
git init -q -b main "$ROOT/jarvis-sandbox"
git -C "$ROOT/jarvis-sandbox" commit -q --allow-empty -m init
git init -q --bare "$ROOT/remote.git"
git -C "$ROOT/jarvis-sandbox" remote add origin "$ROOT/remote.git"
git -C "$ROOT/jarvis-sandbox" push -q origin main
[ -f "$OUT/clips/en_time.wav" ] || uv run python tests/e2e/make_clips.py "$OUT/clips"
C=$OUT/clips
export JARVIS_HOME="$(mktemp -d)"
cp ~/.jarvis/.env "$JARVIS_HOME/.env"
SIM="uv run jarvis simulate --model haiku --projects-root $ROOT"

case "${1:-all}" in
  1|all)
    echo "== 1. spoken question -> home job -> spoken report"
    $SIM "$C/en_time.wav" --gap 5 --tail 150 --out "$OUT/1.wav" ;;
esac
case "${1:-all}" in
  2|all)
    echo "== 2. English + Turkish file creation in sandbox project"
    $SIM "$C/en_sandbox_file.wav" "$C/tr_sandbox_file.wav" --gap 30 --tail 180 --out "$OUT/2.wav"
    ls "$ROOT/jarvis-sandbox" ;;
esac
case "${1:-all}" in
  3|all)
    echo "== 3. push to main -> confirmation -> spoken yes -> pushed"
    echo change > "$ROOT/jarvis-sandbox/change.txt"
    $SIM "$C/en_push_main.wav" "$C/en_yes.wav" --gap 35 --tail 180 --out "$OUT/3.wav"
    echo "remote log:"; git -C "$ROOT/remote.git" log --oneline main | head -3 ;;
esac
