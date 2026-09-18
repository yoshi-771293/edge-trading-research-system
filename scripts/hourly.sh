#!/bin/bash
# One unattended hourly cycle: champion (scored) + challenger (shadow), then dashboard.
cd "$(dirname "$0")/.." || exit 1
echo "=== $(date -u '+%Y-%m-%dT%H:%M:%SZ') hourly ==="
.venv/bin/python -m live.run hourly
