"""Regression tests for SharePoint-backed notification events."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from iam_automation.application.shared_notification_store import SharedNotificationStore


class SharedNotificationStoreTests(unittest.TestCase):
    def test_one_json_tracks_read_users(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SharedNotificationStore(Path(tmp))
            self.assertTrue(store.publish(notification_id="event-1", notification_type="TEST", title="Test", message="Hello", recipients=["Reviewer.One", "reviewer.one"]))
            self.assertEqual(len(list((Path(tmp) / "notifications").glob("*.json"))), 1)
            self.assertEqual(len(store.list_for_user("reviewer.one", unread_only=True)), 1)
            self.assertTrue(store.mark_read("event-1", "reviewer.one"))
            self.assertEqual(store.list_for_user("reviewer.one", unread_only=True), [])
            payload = json.loads((Path(tmp) / "notifications" / "event-1.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["read_by"]["reviewer.one"]["username"], "reviewer.one")

    def test_new_user_does_not_receive_old_audience_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SharedNotificationStore(Path(tmp))
            store.publish(notification_id="event-1", notification_type="TEST", title="Test", message="Hello", recipients=["reviewer.one"])
            self.assertEqual(store.list_for_user("reviewer.two"), [])

    def test_republishing_does_not_reset_read_state_or_add_new_users(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SharedNotificationStore(Path(tmp))
            store.publish(notification_id="event-1", notification_type="TEST", title="Test", message="Hello", recipients=["reviewer.one"])
            store.mark_read("event-1", "reviewer.one")
            store.publish(notification_id="event-1", notification_type="TEST", title="Updated", message="Updated", recipients=["reviewer.one", "reviewer.two"])
            self.assertEqual(store.list_for_user("reviewer.one")[0].get("status"), "READ")
            self.assertEqual(store.list_for_user("reviewer.two"), [])

    def test_listing_deduplicates_historical_files_for_one_logical_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SharedNotificationStore(Path(tmp))
            store.publish(notification_id="event-old", notification_type="IMPORT", title="Old", message="Old", recipients=["reviewer.one"], entity_type="source_file", entity_id="MASTER_ROSTER:file.xlsx", created_at_utc="2026-08-01T00:00:00+00:00")
            store.publish(notification_id="event-new", notification_type="IMPORT", title="New", message="New", recipients=["reviewer.one"], entity_type="source_file", entity_id="MASTER_ROSTER:file.xlsx", created_at_utc="2026-08-02T00:00:00+00:00")

            notifications = store.list_for_user("reviewer.one")

            self.assertEqual(len(notifications), 1)
            self.assertEqual(notifications[0]["title"], "New")

    def test_reading_one_duplicate_suppresses_the_other_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SharedNotificationStore(Path(tmp))
            store.publish(notification_id="event-old", notification_type="IMPORT", title="Old", message="Old", recipients=["reviewer.one"], entity_type="source_file", entity_id="file.xlsx", created_at_utc="2026-08-01T00:00:00+00:00")
            store.publish(notification_id="event-new", notification_type="IMPORT", title="New", message="New", recipients=["reviewer.one"], entity_type="source_file", entity_id="file.xlsx", created_at_utc="2026-08-02T00:00:00+00:00")
            store.mark_read("event-new", "reviewer.one")

            self.assertEqual(store.list_for_user("reviewer.one", unread_only=True), [])


if __name__ == "__main__":
    unittest.main()
