import json
import unittest
from unittest.mock import patch

from prism_collector import ai
from prism_collector.ai import _chunk_text, _item_content


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


    def test_chunk_text_covers_entire_text(self) -> None:
        text = " ".join(f"word{i}" for i in range(2000))

        chunks = _chunk_text(text, 100)

        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 100)
        # Reassembling the chunks must recover every word, in order.
        self.assertEqual(" ".join(chunks).split(), text.split())

    def test_chunk_text_single_chunk_when_short(self) -> None:
        self.assertEqual(_chunk_text("short text", 100), ["short text"])
        self.assertEqual(_chunk_text("   ", 100), [])

    def test_analyze_item_short_text_single_call(self) -> None:
        analysis = {
            "summary": "s",
            "highlights": [],
            "claims": [],
            "tools_mentioned": [],
            "tags": [],
            "difficulty": "beginner",
            "learning_value": 5,
            "follow_up_questions": [],
        }
        row = {"id": 1, "topic_id": "t", "raw_text": "a short transcript"}

        with patch.object(ai, "openai_json", return_value=analysis) as mock_json:
            result = ai._analyze_item(row, model="m")

        self.assertEqual(mock_json.call_count, 1)
        self.assertEqual(result["summary"], "s")

    def test_analyze_item_long_text_maps_every_chunk_then_reduces(self) -> None:
        analysis = {
            "summary": "s",
            "highlights": [],
            "claims": [],
            "tools_mentioned": [],
            "tags": [],
            "difficulty": "beginner",
            "learning_value": 5,
            "follow_up_questions": [],
        }
        long_text = " ".join(f"word{i}" for i in range(5000))
        row = {"id": 1, "topic_id": "t", "raw_text": long_text}

        with patch.object(ai, "ITEM_TEXT_CHUNK_CHARS", 500), patch.object(
            ai, "openai_json", return_value=analysis
        ) as mock_json:
            ai._analyze_item(row, model="m")

        expected_chunks = len(_chunk_text(long_text, 500))
        # One call per chunk (map) plus one consolidation call (reduce).
        self.assertEqual(mock_json.call_count, expected_chunks + 1)


if __name__ == "__main__":
    unittest.main()
