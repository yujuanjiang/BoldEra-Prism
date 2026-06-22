from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_local_env(root: Path) -> None:
    load_env_file(root / ".env")
    load_env_file(root / ".env.local")

    aliases = {
        "NEXT_PUBLIC_SUPABASE_URL": "SUPABASE_URL",
        "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY": "SUPABASE_ANON_KEY",
        "SUPABASE_PUBLISHABLE_KEY": "SUPABASE_ANON_KEY",
        "POSTGRES_URL": "SUPABASE_DB_URL",
        "DATABASE_URL": "SUPABASE_DB_URL",
    }
    for source, target in aliases.items():
        if os.getenv(source) and not os.getenv(target):
            os.environ[target] = os.environ[source]
