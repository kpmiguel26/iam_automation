from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from iam_automation.application.bug_report_service import BugReportService


class BugReportServiceTests(unittest.TestCase):
    def test_create_writes_sharepoint_json_and_filters_for_reporter(self):
        with tempfile.TemporaryDirectory() as directory:
            service = BugReportService(Path(directory))

            bug = service.create(
                title="Approval button is unclear",
                description="The reviewer cannot tell which action is primary.",
                severity="medium",
                page="Approval queue",
                reporter="tester.one",
                computer="VDI-01",
            )
            files = list((Path(directory) / "bug_reports" / "open").glob("*.json"))
            self.assertEqual(len(files), 1)
            self.assertIn(bug.bug_id, files[0].read_text(encoding="utf-8"))
            self.assertEqual(len(service.list_for_user("tester.one", is_admin=False)), 1)
            self.assertEqual(service.list_for_user("tester.two", is_admin=False), [])
            self.assertEqual(len(service.list_for_user("tester.two", is_admin=True)), 1)

    def test_update_moves_report_between_status_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = BugReportService(root)
            bug = service.create(
                title="Import warning",
                description="A warning remains after validation.",
                severity="high",
                page="Imports",
                reporter="tester.one",
                computer="VDI-01",
            )
            open_files = list((root / "bug_reports" / "open").glob("*.json"))
            self.assertEqual(len(open_files), 1)

            updated = service.update(
                bug.bug_id,
                status="in_progress",
                assigned_to="migue",
                resolution="Investigating with the testing team.",
            )

            self.assertEqual(updated.status, "IN_PROGRESS")
            self.assertEqual(updated.assigned_to, "migue")
            self.assertFalse(open_files[0].exists())
            self.assertEqual(len(list((root / "bug_reports" / "open").glob("*.json"))), 0)
            self.assertEqual(len(list((root / "bug_reports" / "in_progress").glob("*.json"))), 1)
            self.assertEqual(service.list_for_user("tester.one", is_admin=False)[0].resolution, updated.resolution)

    def test_comments_are_persisted_on_shared_report(self):
        with tempfile.TemporaryDirectory() as directory:
            service = BugReportService(Path(directory))
            bug = service.create(title="Login issue", description="The page shows an error.", severity="low", page="Login", reporter="tester.one", computer="VDI-01")
            updated = service.add_comment(bug.bug_id, author="admin", message="Please retest after the next build.")
            self.assertEqual(len(updated.comments), 1)
            reloaded = service.list_for_user("tester.one", is_admin=False)[0]
            self.assertEqual(reloaded.comments[0]["author"], "admin")
            self.assertEqual(reloaded.comments[0]["message"], "Please retest after the next build.")

    def test_issue_type_filters_and_priority_order(self):
        with tempfile.TemporaryDirectory() as directory:
            service = BugReportService(Path(directory))
            service.create(title="Small enhancement", description="Add a shortcut.", severity="low", issue_type="feature", page="Overview", reporter="tester.one", computer="VDI-01")
            critical = service.create(title="Blocking failure", description="The workflow cannot continue.", severity="critical", issue_type="bug", page="Approval queue", reporter="tester.one", computer="VDI-01")
            ordered = service.list_for_user("tester.one", is_admin=False)
            self.assertEqual(ordered[0].bug_id, critical.bug_id)
            self.assertEqual([item.issue_type for item in service.list_for_user("tester.one", is_admin=False, issue_type="FEATURE")], ["FEATURE"])

    def test_closed_reports_leave_the_default_queue_but_remain_filterable(self):
        with tempfile.TemporaryDirectory() as directory:
            service = BugReportService(Path(directory))
            bug = service.create(title="Resolved issue", description="No longer reproducible.", severity="low", page="Overview", reporter="tester.one", computer="VDI-01")
            service.update(bug.bug_id, status="closed", assigned_to="admin", resolution="Fixed in the current build.")
            self.assertEqual(service.list_for_user("tester.one", is_admin=False), [])
            closed = service.list_for_user("tester.one", is_admin=False, status="CLOSED")
            self.assertEqual(len(closed), 1)
            self.assertEqual(closed[0].status, "CLOSED")


if __name__ == "__main__":
    unittest.main()
