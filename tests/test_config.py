from pathlib import Path
import unittest

from prism_collector.config import find_topic, load_topics


class ConfigTest(unittest.TestCase):
    def test_load_topics(self) -> None:
        topics = load_topics(Path("config/topics.json"))

        self.assertEqual([topic["id"] for topic in topics], ["ai-programming", "investing"])

    def test_find_topic_rejects_unknown_topic(self) -> None:
        topics = load_topics(Path("config/topics.json"))

        with self.assertRaisesRegex(ValueError, "unknown topic"):
            find_topic(topics, "not-real")


if __name__ == "__main__":
    unittest.main()
