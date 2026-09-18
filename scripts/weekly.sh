#!/bin/bash
# Sunday: judge challenger vs incumbent, re-search, maybe propose ONE challenger, send digest.
cd "$(dirname "$0")/.." || exit 1
echo "=== $(date -u '+%Y-%m-%dT%H:%M:%SZ') weekly ==="
.venv/bin/python -m live.run weekly
