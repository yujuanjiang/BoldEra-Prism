import unittest

from prism_collector.reddit import _listing_url


class RedditTest(unittest.TestCase):
    def test_listing_url_uses_oauth_host_when_authenticated(self) -> None:
        url = _listing_url("programming", "q=python", authenticated=True)

        self.assertEqual(url, "https://oauth.reddit.com/r/programming/search?q=python")

    def test_listing_url_uses_json_endpoint_when_anonymous(self) -> None:
        url = _listing_url("programming", "q=python", authenticated=False)

        self.assertEqual(url, "https://www.reddit.com/r/programming/search.json?q=python")


if __name__ == "__main__":
    unittest.main()
