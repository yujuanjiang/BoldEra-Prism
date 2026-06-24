import os
import unittest
from unittest.mock import patch

from prism_collector.models import SourceItem
from prism_collector.supabase import (
    _headers,
    _row,
    _table_endpoint,
    active_key_kind,
    key_bypasses_rls,
    write_supabase,
)


class SupabaseTest(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_active_key_kind_detects_secret_and_publishable(self) -> None:
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "sb_secret_abc"
        self.assertEqual(active_key_kind(), "secret")
        self.assertTrue(key_bypasses_rls())

    @patch.dict(os.environ, {}, clear=True)
    def test_publishable_key_in_service_slot_does_not_bypass_rls(self) -> None:
        # A publishable key pasted into the service-role slot must NOT be reported
        # as bypassing RLS — this is the cause of "SQL shows rows, Data API shows 0".
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "sb_publishable_abc"
        self.assertEqual(active_key_kind(), "publishable")
        self.assertFalse(key_bypasses_rls())

    @patch.dict(os.environ, {}, clear=True)
    def test_active_key_kind_missing(self) -> None:
        self.assertEqual(active_key_kind(), "missing")
    def test_table_endpoint(self) -> None:
        endpoint = _table_endpoint("https://example.supabase.co/", "source_items")

        self.assertEqual(
            endpoint,
            "https://example.supabase.co/rest/v1/source_items?on_conflict=source,external_id",
        )

    def test_row_keeps_expected_columns(self) -> None:
        row = _row(
            SourceItem(
                source="reddit",
                topic_id="ai-company-building",
                external_id="abc",
                url="https://example.com",
                title="Example",
                metadata={"nested": {"value": 1}},
            )
        )

        self.assertEqual(row["source"], "reddit")
        self.assertEqual(row["metadata"], {"nested": {"value": 1}})

    def test_write_supabase_empty_items_is_noop(self) -> None:
        self.assertEqual(write_supabase([]), 0)

    def test_headers_do_not_send_new_keys_as_bearer_jwts(self) -> None:
        import os

        old_url = os.environ.get("SUPABASE_URL")
        old_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        try:
            os.environ["SUPABASE_URL"] = "https://example.supabase.co"
            os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "sb_secret_test"

            headers = _headers()

            self.assertEqual(headers["apikey"], "sb_secret_test")
            self.assertNotIn("Authorization", headers)
        finally:
            if old_url is None:
                os.environ.pop("SUPABASE_URL", None)
            else:
                os.environ["SUPABASE_URL"] = old_url
            if old_key is None:
                os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)
            else:
                os.environ["SUPABASE_SERVICE_ROLE_KEY"] = old_key

    def test_headers_send_legacy_jwt_keys_as_bearer(self) -> None:
        import os

        old_url = os.environ.get("SUPABASE_URL")
        old_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        try:
            os.environ["SUPABASE_URL"] = "https://example.supabase.co"
            os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "legacy.jwt.key"

            headers = _headers()

            self.assertEqual(headers["Authorization"], "Bearer legacy.jwt.key")
        finally:
            if old_url is None:
                os.environ.pop("SUPABASE_URL", None)
            else:
                os.environ["SUPABASE_URL"] = old_url
            if old_key is None:
                os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)
            else:
                os.environ["SUPABASE_SERVICE_ROLE_KEY"] = old_key


if __name__ == "__main__":
    unittest.main()
