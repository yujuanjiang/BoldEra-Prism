import unittest
from dataclasses import dataclass
from unittest.mock import patch

from prism_collector.youtube import (
    COMMENT_COLLECTION_THRESHOLD,
    _comment_thread_to_dict,
    _transcript_candidates,
    _transcript_proxy_config,
    _should_collect_comments,
    _transcript_to_text,
    collect_youtube,
)


@dataclass
class _FakeTrack:
    language_code: str
    is_generated: bool


class YouTubeTest(unittest.TestCase):
    def test_should_collect_comments_only_above_threshold(self) -> None:
        self.assertFalse(_should_collect_comments(None))
        self.assertFalse(_should_collect_comments(COMMENT_COLLECTION_THRESHOLD))
        self.assertTrue(_should_collect_comments(COMMENT_COLLECTION_THRESHOLD + 1))

    def test_transcript_to_text_flattens_segments(self) -> None:
        text = _transcript_to_text([{"text": "Hello"}, {"text": "world"}])

        self.assertEqual(text, "Hello world")

    def test_transcript_to_text_handles_object_segments(self) -> None:
        @dataclass
        class Segment:
            text: str

        text = _transcript_to_text([Segment("Hello"), Segment("objects")])

        self.assertEqual(text, "Hello objects")

    @patch.dict(
        "os.environ",
        {
            "YOUTUBE_TRANSCRIPT_PROXY_HTTP_URL": "http://proxy.example:8080",
            "YOUTUBE_TRANSCRIPT_PROXY_HTTPS_URL": "https://proxy.example:8443",
        },
        clear=False,
    )
    def test_transcript_proxy_config_supports_generic_proxy(self) -> None:
        config = _transcript_proxy_config()

        self.assertIsNotNone(config)

    def test_transcript_candidates_prefers_english_tracks(self) -> None:
        tracks = [
            _FakeTrack("es", True),
            _FakeTrack("en", False),
            _FakeTrack("en-US", True),
        ]

        candidates = _transcript_candidates(tracks)

        self.assertEqual(
            [track.language_code for track in candidates], ["en", "en-US"]
        )

    def test_transcript_candidates_falls_back_to_generated(self) -> None:
        tracks = [_FakeTrack("es", False), _FakeTrack("fr", True)]

        candidates = _transcript_candidates(tracks)

        self.assertEqual([track.language_code for track in candidates], ["fr"])

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

    @patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-key"})
    @patch("prism_collector.youtube._fetch_video_comments", return_value=[])
    @patch("prism_collector.youtube._fetch_transcript", return_value=None)
    @patch("prism_collector.youtube._fetch_video_details")
    @patch("prism_collector.youtube._get_json")
    def test_collect_youtube_stores_metadata_when_transcript_missing(
        self,
        get_json,
        fetch_video_details,
        fetch_transcript,
        fetch_video_comments,
    ) -> None:
        get_json.return_value = {
            "items": [
                {
                    "id": {"videoId": "v1"},
                    "snippet": {
                        "title": "Video",
                        "description": "Description only",
                        "channelTitle": "Channel",
                    },
                }
            ]
        }
        fetch_video_details.return_value = {
            "v1": {
                "snippet": {"title": "Video", "description": "Description only"},
                "statistics": {"commentCount": "1"},
            }
        }

        items = collect_youtube({"id": "ai-company-building", "keywords": []}, limit=1)

        # The video is now kept even without a transcript, using the description
        # as the raw_text fallback and flagged for later transcript backfill.
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].raw_text, "Description only")
        self.assertFalse(items[0].metadata["transcript_available"])
        self.assertEqual(items[0].metadata["raw_text_kind"], "description")
        self.assertEqual(items[0].metadata["transcript_char_count"], 0)

    @patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-key"})
    @patch("prism_collector.youtube._fetch_video_comments", return_value=[])
    @patch("prism_collector.youtube._fetch_transcript", return_value="Full transcript")
    @patch("prism_collector.youtube._fetch_video_details")
    @patch("prism_collector.youtube._get_json")
    def test_collect_youtube_uses_transcript_as_raw_text(
        self,
        get_json,
        fetch_video_details,
        fetch_transcript,
        fetch_video_comments,
    ) -> None:
        get_json.return_value = {
            "items": [
                {
                    "id": {"videoId": "v1"},
                    "snippet": {
                        "title": "Video",
                        "description": "Description only",
                        "channelTitle": "Channel",
                    },
                }
            ]
        }
        fetch_video_details.return_value = {
            "v1": {
                "snippet": {"title": "Video", "description": "Description only"},
                "statistics": {"commentCount": "1"},
            }
        }

        items = collect_youtube({"id": "ai-company-building", "keywords": []}, limit=1)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].raw_text, "Full transcript")
        self.assertEqual(items[0].metadata["raw_text_kind"], "transcript")
        self.assertEqual(items[0].metadata["transcript_char_count"], len("Full transcript"))
        fetch_video_comments.assert_not_called()


if __name__ == "__main__":
    unittest.main()
