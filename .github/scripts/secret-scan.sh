#!/bin/bash

# Secret + PII scan over git-tracked files.
#
# Scope note: this scans the WORKING TREE at HEAD only. It cannot see content
# that was committed and later deleted — a deleted file stays in history and,
# on a public repo, stays cloneable. `git rm` is not redaction. Removing
# already-committed sensitive data needs a history rewrite (git filter-repo),
# not a commit.
#
# Mark an intentional match with a trailing `# nosecret` comment.

echo "🔍 Scanning for secrets and PII..."

# Credential-shaped strings.
#
# Use [[:space:]], never \s. `git grep -E` is POSIX ERE, where \s is not a
# space class and silently matches nothing — the previous version of this
# script used \s in all four assignment patterns below, so they never fired
# and the script reported "no secrets found" without having checked.
secret_patterns=(
    "password[[:space:]]*[=:][[:space:]]*['\"][^'\"]+['\"]"
    "api[_-]?key[[:space:]]*[=:][[:space:]]*['\"][^'\"]+['\"]"
    "secret[[:space:]]*[=:][[:space:]]*['\"][^'\"]+['\"]"
    "token[[:space:]]*[=:][[:space:]]*['\"][^'\"]+['\"]"
    "AKIA[0-9A-Z]{16}"                       # AWS access key
    "gh[pousr]_[A-Za-z0-9_]{36}"             # GitHub token
    "sk-[A-Za-z0-9]{32,}"                    # OpenAI-style key
    "xox[baprs]-[A-Za-z0-9-]{20,}"           # Slack token
    "AIza[0-9A-Za-z_-]{30,}"                 # Google API key
    "-----BEGIN [A-Z ]*PRIVATE KEY-----"     # PEM private key
)

# Personal data. Real inboxes, home network identifiers, and per-person
# device names have all leaked from this repo before — see the placeholder
# conventions below for what to use instead.
pii_patterns=(
    # Personal mail providers. Placeholders must use example.com/.org/.net.
    "[A-Za-z0-9._%+-]+@(gmail|yahoo|hotmail|outlook|icloud|proton(mail)?)\.[A-Za-z]{2,}"
    # Wi-Fi SSID assignments — name the concept, never the network.
    "[sS][sS][iI][dD][[:space:]]*[=:][[:space:]]*['\"][^'\"]+['\"]"
    # US phone numbers.
    "\+?1?[ .-]?\(?[0-9]{3}\)?[ .-][0-9]{3}[ .-][0-9]{4}"
)

# Machine-specific absolute paths. Nothing tracked here may pin the repo to one
# machine's layout: use the $HOMELY_VIBES placeholder (defined in CLAUDE.md), an
# angle-bracket placeholder like <prod-host>, or derive the checkout at runtime:
#   HOMELY_VIBES=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
#
# An *undefined* placeholder is a docs bug; substituting a concrete path for one
# is a regression. Never "fix" a violation that way.
#
# The leading [^A-Za-z0-9._/-] guard is load-bearing. Without it, ordinary URLs
# containing /home/ (community.tp-link.com/en/home/..., script.google.com/home/...)
# match, and a check that cries wolf is a check that gets switched off.
#
# Host dirs that are NOT the checkout -- ~/logs, ~/Code, ~/bin/Common-configs --
# are deliberately allowed; see CLAUDE.md "Scheduling & deployment".
path_patterns=(
    "(^|[^A-Za-z0-9._/-])/(Users|home)/[A-Za-z0-9_.-]+"   # absolute home path
    "~/[A-Za-z0-9_./-]*homely[-_]vibes"                   # home-anchored checkout ref
    "~/Documents/"  # Mac checkout location; literal self-matches this list # nopath
)

# Separate from $allow on purpose: a path exemption must not also exempt a
# credential that happens to sit on the same line.
path_allow='# nopath|/home/runner'

# Known-safe placeholders. Documentation IPs should use RFC 5737 ranges
# (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24).
allow='example\.(com|org|net)|yourdomain|your-email|your@|user_(from|to)|@example|\.sample|# nosecret|AA:BB:CC:DD:EE:FF|<your-|abc123|var token'

# Test fixtures are fake by construction, and asserting on a literal
# "token123" is the point of the test. Exempt them from the *assignment*
# patterns only — the high-confidence literal patterns below still scan
# every file, so a real AKIA/ghp_/sk- pasted into a test is still caught.
test_paths=(':!*test_*' ':!*_test.*' ':!*/Tests/*' ':!conftest.py' ':!*/conftest.py')

found=0

scan() {
    local label="$1" pattern="$2"; shift 2
    # -I skips binary files; no extension allowlist, so .swift/.ts/.gs/.gpx
    # are covered too — an allowlist here is how PII slipped through before.
    if git grep -InEi "$pattern" -- . "$@" 2>/dev/null | grep -vE "$allow"; then
        echo "⚠️  $label match: $pattern"
        found=1
    fi
}

# Assignment-shaped patterns: skip test fixtures.
for p in "${secret_patterns[@]:0:4}"; do scan "SECRET" "$p" "${test_paths[@]}"; done
# Literal high-confidence credentials: scan everything.
for p in "${secret_patterns[@]:4}";   do scan "SECRET" "$p"; done
for p in "${pii_patterns[@]}";        do scan "PII"    "$p"; done

# Absolute-path check: its own allowlist, so `# nopath` cannot exempt a secret.
found_path=0
for p in "${path_patterns[@]}"; do
    if git grep -InE "$p" -- . 2>/dev/null | grep -vE "$path_allow"; then
        echo "⚠️  PATH match: $p"
        found_path=1
    fi
done

if [ $found -eq 0 ] && [ $found_path -eq 0 ]; then
    echo "✅ No secrets, PII, or machine-specific paths found"
    exit 0
fi

if [ $found -ne 0 ]; then
    cat >&2 <<'EOF'
❌ Potential secrets or PII detected

Real credentials belong in config/local.yaml or config/tokens/ (both
gitignored). Real names, inboxes, SSIDs, and host names do not belong in
tracked files at all — use placeholders. If a match is a deliberate
placeholder, append `# nosecret`.
EOF
fi

if [ $found_path -ne 0 ]; then
    cat >&2 <<'EOF'
❌ Machine-specific absolute path detected

Tracked files must not hardcode one machine's layout. Use instead:
  $HOMELY_VIBES              the checkout root (defined in CLAUDE.md)
  <prod-host>, <user>        angle-bracket placeholders for hosts/users
  HOMELY_VIBES=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
                             to derive the checkout at runtime

Do NOT resolve this by substituting a concrete path for a placeholder — that is
the regression this check exists to prevent. Host dirs that are not the checkout
(~/logs, ~/Code, ~/bin/Common-configs) are already allowed. For a deliberate
exception, append `# nopath`.
EOF
fi
exit 1
