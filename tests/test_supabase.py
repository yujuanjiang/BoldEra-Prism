import unittest

from prism_collector.models import SourceItem
from prism_collector.supabase import _row, _table_endpoint, write_supabase


class SupabaseTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
