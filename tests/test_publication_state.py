import tempfile
import unittest
from pathlib import Path

from iam_automation.application.publication_state import (
    clear_publication_pending,
    mark_publication_pending,
    pending_marker_path,
    publication_pending,
)


class PublicationStateTests(unittest.TestCase):
    def test_pending_marker_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime_path = Path(directory) / "runtime.sqlite"

            self.assertFalse(publication_pending(runtime_path))
            mark_publication_pending(runtime_path, actor="migue", reason="Password changed")

            self.assertTrue(publication_pending(runtime_path))
            self.assertTrue(pending_marker_path(runtime_path).is_file())

            clear_publication_pending(runtime_path)

            self.assertFalse(publication_pending(runtime_path))
            self.assertFalse(pending_marker_path(runtime_path).exists())


if __name__ == "__main__":
    unittest.main()
