import unittest
from dataclasses import dataclass
from unittest.mock import patch

from prism_collector.youtube import (
    COMMENT_COLLECTION_THRESHOLD,
    _comment_thread_to_dict,
    _passes_quality_filters,
    _transcript_candidates,
    _transcript_proxy_config,
    _should_collect_comments,
    _transcript_to_text,
    collect_youtube,
)

_OLD = "2020-01-01T00:00:00Z"
_NOW = "2099-01-01T00:00:00Z"


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

    def test_quality_filter_requires_min_comments(self) -> None:
        self.assertTrue(
            _passes_quality_filters(60, _OLD, min_comments=50, min_age_days=7)
        )
        self.assertFalse(
            _passes_quality_filters(10, _OLD, min_comments=50, min_age_days=7)
        )
        # Comments disabled -> no count -> excluded.
        self.assertFalse(
            _passes_quality_filters(None, _OLD, min_comments=50, min_age_days=7)
        )

    def test_quality_filter_requires_min_age(self) -> None:
        # Published in the far future (effectively "too new") fails the age gate.
        self.assertFalse(
            _passes_quality_filters(100, _NOW, min_comments=50, min_age_days=7)
        )
        self.assertTrue(
            _passes_quality_filters(100, _OLD, min_comments=50, min_age_days=7)
        )

    @patch.dict("os.environ", {"YOUTUBE_API_KEY": "test-key"})
    @patch("prism_collector.youtube._fetch_video_comments", return_value=[])
    @patch("prism_collector.youtube._fetch_transcript", return_value="Full transcript")
    @patch("prism_collector.youtube._fetch_video_details")
    @patch("prism_collector.youtube._get_json")
    def test_collect_youtube_drops_videos_below_comment_floor(
        self,
        get_json,
        fetch_video_details,
        fetch_transcript,
        fetch_video_comments,
    ) -> None:
        get_json.return_value = {
            "items": [
                {"id": {"videoId": "keep"}, "snippet": {"title": "Keep", "channelTitle": "C"}},
                {"id": {"videoId": "drop"}, "snippet": {"title": "Drop", "channelTitle": "C"}},
            ]
        }
        fetch_video_details.return_value = {
            "keep": {
                "snippet": {"title": "Keep", "publishedAt": _OLD},
                "statistics": {"commentCount": "60"},
            },
            "drop": {
                "snippet": {"title": "Drop", "publishedAt": _OLD},
                "statistics": {"commentCount": "10"},
            },
        }

        items = collect_youtube({"id": "ai-company-building", "keywords": []}, limit=10)

        self.assertEqual([item.external_id for item in items], ["keep"])

    @patch.dict(
        "os.environ",
        {"YOUTUBE_API_KEY": "test-key", "YOUTUBE_MIN_COMMENTS": "0", "YOUTUBE_MIN_AGE_DAYS": "0"},
    )
    @patch("prism_collector.youtube._fetch_video_comments", return_value=[])
    @patch("prism_collector.youtube._fetch_transcript", return_value="t")
    @patch("prism_collector.youtube._fetch_video_details")
    @patch("prism_collector.youtube._get_json")
    def test_collect_youtube_paginates_until_target_reached(
        self,
        get_json,
        fetch_video_details,
        fetch_transcript,
        fetch_video_comments,
    ) -> None:
        # Page 1 yields one video and a next-page token; page 2 yields the second.
        get_json.side_effect = [
            {
                "items": [{"id": {"videoId": "v1"}, "snippet": {"title": "1", "channelTitle": "C"}}],
                "nextPageToken": "PAGE2",
            },
            {
                "items": [{"id": {"videoId": "v2"}, "snippet": {"title": "2", "channelTitle": "C"}}],
            },
        ]
        fetch_video_details.return_value = {
            "v1": {"snippet": {"title": "1", "publishedAt": _OLD}, "statistics": {"commentCount": "1"}},
            "v2": {"snippet": {"title": "2", "publishedAt": _OLD}, "statistics": {"commentCount": "1"}},
        }

        items = collect_youtube({"id": "ai-company-building", "keywords": []}, limit=2)

        self.assertEqual([item.external_id for item in items], ["v1", "v2"])
        self.assertEqual(get_json.call_count, 2)  # had to fetch a second page

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

    @patch.dict(
        "os.environ",
        {"YOUTUBE_API_KEY": "test-key", "YOUTUBE_MIN_COMMENTS": "0", "YOUTUBE_MIN_AGE_DAYS": "0"},
    )
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

    @patch.dict(
        "os.environ",
        {"YOUTUBE_API_KEY": "test-key", "YOUTUBE_MIN_COMMENTS": "0", "YOUTUBE_MIN_AGE_DAYS": "0"},
    )
    @patch("prism_collector.youtube._fetch_video_comments", return_value=[])
    @patch("prism_collector.youtube._fetch_transcript", return_value="Full transcript")
    @patch("prism_collector.youtube._fetch_video_details")
    @patch("prism_collector.youtube._get_json")
    def test_collect_youtube_skips_existing_videos_before_transcript_fetch(
        self,
        get_json,
        fetch_video_details,
        fetch_transcript,
        fetch_video_comments,
    ) -> None:
        get_json.return_value = {
            "items": [
                {"id": {"videoId": "old1"}, "snippet": {"title": "Old", "channelTitle": "C"}},
                {"id": {"videoId": "new1"}, "snippet": {"title": "New", "channelTitle": "C"}},
            ]
        }
        fetch_video_details.return_value = {
            "new1": {"snippet": {"title": "New"}, "statistics": {"commentCount": "1"}}
        }

        items = collect_youtube(
            {"id": "ai-company-building", "keywords": []},
            limit=2,
            skip_existing=lambda ids: {"old1"},
        )

        # Only the new video is processed; the existing one never hits the transcript fetch.
        self.assertEqual([item.external_id for item in items], ["new1"])
        fetch_transcript.assert_called_once_with("new1")

    @patch.dict(
        "os.environ",
        {"YOUTUBE_API_KEY": "test-key", "YOUTUBE_MIN_COMMENTS": "0", "YOUTUBE_MIN_AGE_DAYS": "0"},
    )
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
