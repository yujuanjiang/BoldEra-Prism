import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from prism_collector.env import load_local_env


class EnvTest(unittest.TestCase):
    def test_load_local_env_maps_next_public_supabase_names(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env.local").write_text(
                "\n".join(
                    [
                        "NEXT_PUBLIC_SUPABASE_URL=https://example.supabase.co",
                        "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_test",
                    ]
                ),
                encoding="utf-8",
            )

            old_values = {key: os.environ.get(key) for key in _ENV_KEYS}
            try:
                for key in _ENV_KEYS:
                    os.environ.pop(key, None)

                load_local_env(root)

                self.assertEqual(os.environ["SUPABASE_URL"], "https://example.supabase.co")
                self.assertEqual(os.environ["SUPABASE_ANON_KEY"], "sb_publishable_test")
            finally:
                for key, value in old_values.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


_ENV_KEYS = [
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "NEXT_PUBLIC_SUPABASE_URL",
    "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY",
]


if __name__ == "__main__":
    unittest.main()
