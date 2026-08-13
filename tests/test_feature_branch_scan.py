import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "lib" / "feature_branch_scan.py"
SPEC = importlib.util.spec_from_file_location("feature_branch_scan", MODULE_PATH)
scanner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = scanner
SPEC.loader.exec_module(scanner)


class FakeTTY(io.StringIO):
    def isatty(self):
        return True

    def fileno(self):
        return 10


class FeatureBranchScanTests(unittest.TestCase):
    def test_extract_ticket_accepts_expected_names(self):
        self.assertEqual(scanner.extract_ticket("feature/SERU-1234"), "SERU-1234")
        self.assertEqual(scanner.extract_ticket("feature/SERU-1234-description"), "SERU-1234")
        self.assertEqual(scanner.extract_ticket("feature/seru-99/foo"), "SERU-99")

    def test_extract_ticket_rejects_unrelated_names(self):
        self.assertIsNone(scanner.extract_ticket("bugfix/SERU-1234"))
        self.assertIsNone(scanner.extract_ticket("feature/OTHER-1234"))
        self.assertIsNone(scanner.extract_ticket("feature/SERU-1234description"))

    def test_jira_done_category_is_closed(self):
        self.assertTrue(scanner.JiraStatus("SERU-1", "Closed", "done").is_closed)
        self.assertFalse(scanner.JiraStatus("SERU-2", "In Progress", "indeterminate").is_closed)
        self.assertFalse(scanner.JiraStatus("SERU-3", "Closed", "done", "failed").is_closed)

    @patch.object(scanner, "urlopen")
    def test_jira_status_includes_assignee(self, urlopen):
        response = MagicMock()
        response.read.return_value = json.dumps(
            {
                "fields": {
                    "status": {
                        "name": "Done",
                        "statusCategory": {"key": "done"},
                    },
                    "assignee": {"displayName": "王小明"},
                }
            }
        ).encode("utf-8")
        urlopen.return_value.__enter__.return_value = response

        result = scanner.fetch_jira_status(
            "SERU-42",
            "https://jira.example",
            "user@example.com",
            "token",
        )

        self.assertEqual(result.assignee, "王小明")
        self.assertTrue(result.is_closed)
        request = urlopen.call_args.args[0]
        self.assertIn("fields=status,assignee", request.full_url)

    @patch.object(scanner, "urlopen")
    def test_jira_status_marks_empty_assignee_as_unassigned(self, urlopen):
        response = MagicMock()
        response.read.return_value = json.dumps(
            {
                "fields": {
                    "status": {
                        "name": "Done",
                        "statusCategory": {"key": "done"},
                    },
                    "assignee": None,
                }
            }
        ).encode("utf-8")
        urlopen.return_value.__enter__.return_value = response

        result = scanner.fetch_jira_status(
            "SERU-42",
            "https://jira.example",
            "user@example.com",
            "token",
        )

        self.assertEqual(result.assignee, "未指派")

    def test_env_file_does_not_execute_shell_and_does_not_override_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "should-not-exist"
            env_path = Path(directory) / "jira.env"
            env_path.write_text(
                "JIRA_URL='https://jira.example'\n"
                "export JIRA_USERNAME=from-file\n"
                "JIRA_API_TOKEN=$(touch %s)\n" % marker,
                encoding="utf-8",
            )
            environ = {"JIRA_USERNAME": "from-environment"}
            scanner.load_env_file(env_path, environ)
            self.assertEqual(environ["JIRA_URL"], "https://jira.example")
            self.assertEqual(environ["JIRA_USERNAME"], "from-environment")
            self.assertFalse(marker.exists())

    @patch.object(scanner.subprocess, "run")
    def test_github_scan_is_get_only_and_matches_candidates(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="main\nfeature/SERU-42-test\nfeature/NOPE-1\n", stderr=""
        )
        candidates, count = scanner.scan_repo_branches("104corp/example")
        self.assertEqual(count, 3)
        self.assertEqual([item.ticket for item in candidates], ["SERU-42"])
        command = run.call_args.args[0]
        self.assertIn("GET", command)
        self.assertNotIn("DELETE", command)

    def test_read_repos_deduplicates_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text(
                json.dumps({"tracked_repos": ["104corp/a", "104corp/a", "104corp/b"]}),
                encoding="utf-8",
            )
            self.assertEqual(scanner.read_repos(config), ["104corp/a", "104corp/b"])

    @patch.object(scanner.tty, "setcbreak")
    @patch.object(scanner.termios, "tcsetattr")
    @patch.object(scanner.termios, "tcgetattr", return_value=["original"])
    def test_interactive_menu_uses_cbreak_and_submits_checked_item(
        self, _tcgetattr, _tcsetattr, setcbreak
    ):
        candidate = scanner.BranchCandidate(
            "104corp/example", "feature/SERU-42", "SERU-42"
        )
        statuses = {
            "SERU-42": scanner.JiraStatus(
                "SERU-42", "Done", "done", assignee="王小明"
            )
        }

        with patch("sys.stdin", FakeTTY(" \r")), patch("sys.stdout", FakeTTY()):
            selected = scanner.select_branches_interactively([candidate], statuses)

        self.assertEqual(selected, [candidate])
        setcbreak.assert_called_once_with(10)

    @patch.object(
        scanner.shutil,
        "get_terminal_size",
        return_value=scanner.os.terminal_size((140, 24)),
    )
    def test_selection_menu_uses_single_line_columns(self, _terminal_size):
        candidate = scanner.BranchCandidate(
            "104corp/example", "feature/SERU-42-description", "SERU-42"
        )
        statuses = {
            "SERU-42": scanner.JiraStatus(
                "SERU-42", "Closed", "done", assignee="王小明"
            )
        }

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            scanner._render_selection_menu([candidate], statuses, 0, [False])

        output = stdout.getvalue()
        self.assertIn("Repository", output)
        self.assertIn("Branch", output)
        self.assertIn("Assignee", output)
        self.assertNotIn("經辦人", output)
        candidate_lines = [
            line for line in output.splitlines() if "feature/SERU-42-description" in line
        ]
        self.assertEqual(len(candidate_lines), 1)
        self.assertIn("104corp/example", candidate_lines[0])
        self.assertIn("SERU-42", candidate_lines[0])
        self.assertIn("Closed", candidate_lines[0])
        self.assertIn("王小明", candidate_lines[0])
        self.assertGreaterEqual(candidate_lines[0].count("│"), 5)

    def test_keyboard_interrupt_cancels_and_restores_terminal(self):
        candidate = scanner.BranchCandidate(
            "104corp/example", "feature/SERU-42", "SERU-42"
        )
        statuses = {
            "SERU-42": scanner.JiraStatus("SERU-42", "Closed", "done")
        }
        stdin = FakeTTY()

        with (
            patch("sys.stdin", stdin),
            patch("sys.stdout", FakeTTY()),
            patch.object(stdin, "read", side_effect=KeyboardInterrupt),
            patch.object(scanner.tty, "setcbreak"),
            patch.object(scanner.termios, "tcgetattr", return_value=["original"]),
            patch.object(scanner.termios, "tcsetattr") as tcsetattr,
        ):
            selected = scanner.select_branches_interactively([candidate], statuses)

        self.assertIsNone(selected)
        tcsetattr.assert_called_once_with(10, scanner.termios.TCSADRAIN, ["original"])

    def test_simple_branch_list_is_headerless_and_aligned(self):
        candidates = [
            scanner.BranchCandidate(
                "104corp/104crm-b",
                "feature/SERU-12487_accounting-remarks-yii-eol",
                "SERU-12487",
            ),
            scanner.BranchCandidate(
                "104corp/104crm-c", "feature/SERU-12687", "SERU-12687"
            ),
        ]
        statuses = {
            "SERU-12487": scanner.JiraStatus(
                "SERU-12487", "Closed", "done", assignee="Tuna Yu 余瑋傑"
            ),
            "SERU-12687": scanner.JiraStatus(
                "SERU-12687", "Closed", "done", assignee="Shane Zeng 曾祥豪"
            ),
        }

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            scanner.print_simple_branch_list(candidates, statuses)

        output = stdout.getvalue()
        self.assertNotIn("Repository", output)
        self.assertIn(
            "104corp/104crm-b  feature/SERU-12487_accounting-remarks-yii-eol  "
            "SERU-12487  Closed  Tuna Yu 余瑋傑",
            output,
        )
        self.assertIn("104corp/104crm-c", output)
        self.assertIn("SERU-12687  Closed  Shane Zeng 曾祥豪", output)

    @patch.object(scanner.subprocess, "run")
    def test_delete_remote_branch_uses_explicit_delete_api(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        candidate = scanner.BranchCandidate(
            "104corp/example", "feature/SERU-42-description", "SERU-42"
        )

        self.assertIsNone(scanner.delete_remote_branch(candidate))

        command = run.call_args.args[0]
        self.assertEqual(command[0:4], ["gh", "api", "--method", "DELETE"])
        self.assertIn(
            "repos/104corp/example/git/refs/heads/feature%2FSERU-42-description",
            command,
        )

    @patch.object(scanner, "delete_remote_branch")
    @patch.object(scanner, "select_branches_interactively")
    @patch.object(scanner, "fetch_all_jira_statuses")
    @patch.object(scanner, "scan_repo_branches")
    @patch.object(scanner.shutil, "which", return_value="/usr/bin/gh")
    def test_json_mode_is_read_only_and_includes_assignee(
        self, _which, scan, fetch_statuses, select, delete
    ):
        candidate = scanner.BranchCandidate(
            "104corp/example", "feature/SERU-42", "SERU-42"
        )
        scan.return_value = ([candidate], 3)
        fetch_statuses.return_value = {
            "SERU-42": scanner.JiraStatus(
                "SERU-42", "Done", "done", assignee="王小明"
            )
        }
        environ = {
            "JIRA_URL": "https://jira.example",
            "JIRA_USERNAME": "user@example.com",
            "JIRA_API_TOKEN": "token",
        }

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            result = scanner.main(
                ["--repo", "104corp/example", "--json"],
                project_root=Path("/tmp"),
                environ=environ,
            )

        self.assertEqual(result, 0)
        self.assertEqual(json.loads(stdout.getvalue())["branches"][0]["jira_assignee"], "王小明")
        select.assert_not_called()
        delete.assert_not_called()

    @patch.object(scanner, "delete_remote_branch", return_value=None)
    @patch.object(scanner, "select_branches_interactively")
    @patch.object(scanner, "fetch_all_jira_statuses")
    @patch.object(scanner, "scan_repo_branches")
    @patch.object(scanner.shutil, "which", return_value="/usr/bin/gh")
    def test_only_submitted_branch_is_deleted(
        self, _which, scan, fetch_statuses, select, delete
    ):
        first = scanner.BranchCandidate(
            "104corp/example", "feature/SERU-42", "SERU-42"
        )
        second = scanner.BranchCandidate(
            "104corp/example", "feature/SERU-43", "SERU-43"
        )
        scan.return_value = ([first, second], 2)
        fetch_statuses.return_value = {
            "SERU-42": scanner.JiraStatus("SERU-42", "Done", "done"),
            "SERU-43": scanner.JiraStatus("SERU-43", "Done", "done"),
        }
        select.return_value = [second]
        environ = {
            "JIRA_URL": "https://jira.example",
            "JIRA_USERNAME": "user@example.com",
            "JIRA_API_TOKEN": "token",
        }

        with patch("sys.stdout", new_callable=io.StringIO):
            result = scanner.main(
                ["--repo", "104corp/example"],
                project_root=Path("/tmp"),
                environ=environ,
            )

        self.assertEqual(result, 0)
        delete.assert_called_once_with(second)

    @patch.object(scanner, "delete_remote_branch")
    @patch.object(scanner, "select_branches_interactively", return_value=None)
    @patch.object(scanner, "fetch_all_jira_statuses")
    @patch.object(scanner, "scan_repo_branches")
    @patch.object(scanner.shutil, "which", return_value="/usr/bin/gh")
    def test_cancel_prints_compact_scanned_list_without_deleting(
        self, _which, scan, fetch_statuses, _select, delete
    ):
        candidate = scanner.BranchCandidate(
            "104corp/104crm-b", "feature/SERU-12687", "SERU-12687"
        )
        scan.return_value = ([candidate], 1)
        fetch_statuses.return_value = {
            "SERU-12687": scanner.JiraStatus(
                "SERU-12687", "Closed", "done", assignee="Shane Zeng 曾祥豪"
            )
        }
        environ = {
            "JIRA_URL": "https://jira.example",
            "JIRA_USERNAME": "user@example.com",
            "JIRA_API_TOKEN": "token",
        }
        stdout = FakeTTY()

        with patch("sys.stdin", FakeTTY()), patch("sys.stdout", stdout):
            result = scanner.main(
                ["--repo", "104corp/104crm-b"],
                project_root=Path("/tmp"),
                environ=environ,
            )

        self.assertEqual(result, 0)
        self.assertIn("本次掃描清單：", stdout.getvalue())
        self.assertIn(
            "104corp/104crm-b  feature/SERU-12687  SERU-12687  Closed  "
            "Shane Zeng 曾祥豪",
            stdout.getvalue(),
        )
        delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
