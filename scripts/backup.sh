#!/usr/bin/env bash
# Consistent online SQLite backup with rotation (keeps the last $KEEP copies).
#   ./scripts/backup.sh [backup_dir]
source "$(dirname "$0")/_common.sh"
require_uv
DEST="${1:-backups}"
KEEP="${BACKUP_KEEP:-14}"
mkdir -p "$DEST"

uv run --frozen --no-dev python - "$DEST" <<'PY'
import sqlite3, sys
from datetime import datetime, UTC
from pathlib import Path
from tension_index.config import get_settings

src = get_settings().database_path
if not src.exists():
    sys.exit(f"no database at {src}")
out = Path(sys.argv[1]) / f"tension-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.sqlite3"
with sqlite3.connect(src) as s, sqlite3.connect(out) as d:
    s.backup(d)
print(f"backup: {out}")
PY

ls -1t "$DEST"/tension-*.sqlite3 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f
