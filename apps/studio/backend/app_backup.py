#!/usr/bin/env python3
"""Deprecated insecure Studio backend stub.

This file previously shipped a wide-open CORS app that treated any
Authorization header (or EDITOR_MODE=true) as authenticated. It must not be
run. Use ``app.py`` instead.
"""

raise SystemExit(
    'apps/studio/backend/app_backup.py is disabled. '
    'Start Studio with apps/studio/backend/app.py.'
)
