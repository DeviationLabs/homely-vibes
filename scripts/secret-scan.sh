#!/bin/bash

# Simple secret scan script
# Looks for common secret patterns in git-tracked files

echo "🔍 Scanning for secrets..."

# Define patterns to search for
patterns=(
    "password\s*=\s*['\"][^'\"]+['\"]"
    "api[_-]?key\s*=\s*['\"][^'\"]+['\"]"
    "secret\s*=\s*['\"][^'\"]+['\"]"
    "token\s*=\s*['\"][^'\"]+['\"]"
    "AKIA[0-9A-Z]{16}"  # AWS Access Key
    "gh[pousr]_[A-Za-z0-9_]{36}"  # GitHub tokens
)

found_secrets=0

for pattern in "${patterns[@]}"; do
    if git grep -iE "$pattern" -- '*.py' '*.js' '*.json' '*.yaml' '*.yml' '*.sh' 2>/dev/null | grep -v ".sample" | grep -v "# nosecret"; then
        echo "⚠️  Found potential secret: $pattern"
        found_secrets=1
    fi
done

if [ $found_secrets -eq 0 ]; then
    echo "✅ No secrets found"
    exit 0
else
    echo "❌ Potential secrets detected"
    exit 1
fi