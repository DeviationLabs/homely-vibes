#!/usr/bin/env bash
# remote-test.sh — pull prod DB from a remote test host, replay locally.
#
# Usage (run from repo root on a feature branch):
#   TEST_HOST=my-host ./RachioFlume/scripts/remote-test.sh                       # scp DB + 24h replay
#   TEST_HOST=my-host ./RachioFlume/scripts/remote-test.sh --replay-hours 168     # replay last 7 days
#
# Requires:
#   - TEST_HOST env var set to an ssh-reachable target
#   - Config with alert rules (config/default.yaml or config/local.yaml)

set -euo pipefail

: "${TEST_HOST:?TEST_HOST env var not set — e.g. export TEST_HOST=my-test-machine}"

REPLAY_HOURS=24
DB_REMOTE="$HOME/logs/water_tracking.db"
DB_LOCAL="/tmp/rachioflume_replay.db"

while [[ $# -gt 0 ]]; do
    case $1 in
        --replay-hours) REPLAY_HOURS="$2"; shift 2 ;;
        --db-remote)    DB_REMOTE="$2";   shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

echo "==================================================================="
echo "Remote test: pulling DB from ${TEST_HOST}, replaying ${REPLAY_HOURS}h locally"
echo "==================================================================="

echo ""
echo "--- Copying production DB from ${TEST_HOST} ---"
scp "${TEST_HOST}:${DB_REMOTE}" "$DB_LOCAL"
DB_SIZE=$(du -h "$DB_LOCAL" | cut -f1)
echo "  Downloaded (${DB_SIZE})"

echo ""
echo "--- Running replay against local copy ---"
uv run python -m RachioFlume.rfmanager alerts replay \
    --db "$DB_LOCAL" \
    --hours "$REPLAY_HOURS"

rm -f "$DB_LOCAL"
echo ""
echo "==================================================================="
echo "Done. Temp DB cleaned up."
echo "==================================================================="
