from pathlib import Path
import unittest

from prism_collector.config import find_topic, load_topics, select_topics


class ConfigTest(unittest.TestCase):
    def test_select_topics_all_returns_every_topic(self) -> None:
        topics = load_topics(Path("config/topics.json"))

        selected = select_topics(topics, "all")

        self.assertEqual(len(selected), len(topics))
        self.assertEqual([t["id"] for t in selected], [t["id"] for t in topics])

    def test_select_topics_single(self) -> None:
        topics = load_topics(Path("config/topics.json"))

        selected = select_topics(topics, "ai-investing")

        self.assertEqual([t["id"] for t in selected], ["ai-investing"])

    def test_select_topics_unknown_raises(self) -> None:
        topics = load_topics(Path("config/topics.json"))

        with self.assertRaisesRegex(ValueError, "unknown topic"):
            select_topics(topics, "nope")
    def test_load_topics(self) -> None:
        topics = load_topics(Path("config/topics.json"))

        self.assertEqual(
            [topic["id"] for topic in topics],
            [
                "ai-company-building",
                "ai-investing",
                "ai-agents-skills",
                "ai-work-productivity",
                "ai-life-productivity",
                "ai-agent",
                "ai-skills",
            ],
        )

    def test_find_topic_rejects_unknown_topic(self) -> None:
        topics = load_topics(Path("config/topics.json"))

        with self.assertRaisesRegex(ValueError, "unknown topic"):
            find_topic(topics, "not-real")


if __name__ == "__main__":
    unittest.main()
