import json
import unittest

from prism_collector.ai import _item_content


class AiTest(unittest.TestCase):
    def test_item_content_includes_source_identity(self) -> None:
        content = _item_content(
            {
                "id": 123,
                "source": "reddit",
                "topic_id": "ai-company-building",
                "title": "Useful discussion",
                "url": "https://example.com",
                "raw_text": "A long discussion",
            },
            max_chars=1000,
        )

        payload = json.loads(content)
        self.assertEqual(payload["id"], 123)
        self.assertEqual(payload["source"], "reddit")

    def test_item_content_truncates_long_text(self) -> None:
        content = _item_content({"raw_text": "x" * 200}, max_chars=80)

        self.assertLessEqual(len(content), 80)
        self.assertTrue(content.endswith("...[truncated]"))


if __name__ == "__main__":
    unittest.main()
