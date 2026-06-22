import json
import unittest

from prism_collector.io import write_jsonl
from prism_collector.models import SourceItem


class IoTest(unittest.TestCase):
    def test_write_jsonl(self) -> None:
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "items.jsonl"

            count = write_jsonl(
                path,
                [
                    SourceItem(
                        source="reddit",
                        topic_id="ai-company-building",
                        external_id="abc",
                        url="https://example.com",
                        title="Example",
                    )
                ],
            )

            self.assertEqual(count, 1)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["title"], "Example")


if __name__ == "__main__":
    unittest.main()
