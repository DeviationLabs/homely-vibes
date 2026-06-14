#!/usr/bin/env bash
# Wrapper invoked by launchd for the WhatsApp daily summary job.
#
# Responsibilities:
#  1. Skip-and-notify when WhatsApp isn't running (DB would be empty / stale).
#  2. Run the standalone whatsapp_summary_job.py script.
#  3. Send a Pushover ping on success or failure.

set -euo pipefail

# launchd ships a near-empty PATH; prepend Homebrew so python3, uv, etc. resolve.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

# Resolve repo root from this script's location so the wrapper is relocatable.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') run_whatsapp_summary.sh starting ==="

notify() {
    local status="$1"
    local body="${2:-}"
    if [[ -n "$body" ]]; then
        uv run python -m LaunchJobs.notify whatsapp-summary --status "$status" --body "$body" || true
    else
        uv run python -m LaunchJobs.notify whatsapp-summary --status "$status" || true
    fi
}

if ! pgrep -x WhatsApp > /dev/null; then
    echo "WhatsApp desktop is not running; skipping summary."
    notify "skipped" "WhatsApp desktop not running"
    exit 0
fi

set +e
uv run python "$SCRIPT_DIR/whatsapp_summary_job.py"
rc=$?
set -e

if [[ $rc -eq 0 ]]; then
    echo "whatsapp_summary_job.py exited 0"
    notify "ok"
else
    echo "whatsapp_summary_job.py exited $rc"
    notify "fail" "exit code $rc; check stderr log"
    exit $rc
fi
