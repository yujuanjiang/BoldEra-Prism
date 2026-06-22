import unittest

from prism_collector.youtube import (
    COMMENT_COLLECTION_THRESHOLD,
    _comment_thread_to_dict,
    _should_collect_comments,
    _transcript_to_text,
)


class YouTubeTest(unittest.TestCase):
    def test_should_collect_comments_only_above_threshold(self) -> None:
        self.assertFalse(_should_collect_comments(None))
        self.assertFalse(_should_collect_comments(COMMENT_COLLECTION_THRESHOLD))
        self.assertTrue(_should_collect_comments(COMMENT_COLLECTION_THRESHOLD + 1))

    def test_transcript_to_text_flattens_segments(self) -> None:
        text = _transcript_to_text([{"text": "Hello"}, {"text": "world"}])

        self.assertEqual(text, "Hello world")

    def test_comment_thread_to_dict(self) -> None:
        comment = _comment_thread_to_dict(
            {
                "id": "abc",
                "snippet": {
                    "totalReplyCount": 2,
                    "topLevelComment": {
                        "snippet": {
                            "authorDisplayName": "Someone",
                            "textDisplay": "Useful point",
                            "likeCount": "7",
                            "publishedAt": "2026-01-01T00:00:00Z",
                        }
                    },
                },
            }
        )

        self.assertEqual(comment["text"], "Useful point")
        self.assertEqual(comment["like_count"], 7)
        self.assertEqual(comment["reply_count"], 2)


if __name__ == "__main__":
    unittest.main()
