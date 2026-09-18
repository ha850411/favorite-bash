import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "lib" / "release_pr.py"
SPEC = importlib.util.spec_from_file_location("release_pr", MODULE_PATH)
release_pr = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = release_pr
SPEC.loader.exec_module(release_pr)


class ReleasePrTests(unittest.TestCase):
    def test_normalize_target_env(self):
        self.assertEqual(release_pr.normalize_target_env("staging"), ("staging", "STG"))
        self.assertEqual(release_pr.normalize_target_env("stg"), ("staging", "STG"))
        self.assertEqual(release_pr.normalize_target_env("prod"), ("prod", "PROD"))
        self.assertEqual(release_pr.normalize_target_env("production"), ("prod", "PROD"))
        self.assertEqual(release_pr.normalize_target_env("develop"), ("develop", "Develop"))
        self.assertEqual(release_pr.normalize_target_env("dev"), ("develop", "Develop"))

    def test_get_today_date_label(self):
        # prod/develop extracts 4-digit suffix from branch if present
        self.assertEqual(
            release_pr.get_today_date_label("release/SERVICE-0324", "prod"), "0324"
        )
        self.assertEqual(
            release_pr.get_today_date_label("release/SERVICE-0922", "develop"), "0922"
        )
        # staging uses today's date
        self.assertRegex(
            release_pr.get_today_date_label("release/SERVICE-0922", "staging"),
            r"^\d{4}$",
        )

    def test_get_repo_target_branch_static_and_project(self):
        # 104crm-b
        self.assertEqual(
            release_pr.get_repo_target_branch("104corp/104crm-b", "staging", is_static=False),
            "staging/project",
        )
        self.assertEqual(
            release_pr.get_repo_target_branch("104corp/104crm-b", "staging", is_static=True),
            "staging/static",
        )
        self.assertEqual(
            release_pr.get_repo_target_branch("104corp/104crm-b", "prod", is_static=False),
            "prod/project",
        )
        self.assertEqual(
            release_pr.get_repo_target_branch("104corp/104crm-b", "prod", is_static=True),
            "prod/static",
        )
        self.assertEqual(
            release_pr.get_repo_target_branch("104corp/104crm-b", "develop", is_static=False),
            "develop",
        )
        self.assertEqual(
            release_pr.get_repo_target_branch("104corp/104crm-b", "develop", is_static=True),
            "develop_static",
        )

        # 104crm-wsp-jb-b
        self.assertEqual(
            release_pr.get_repo_target_branch("104corp/104crm-wsp-jb-b", "staging"),
            "staging/project",
        )

        # 104crm-lib
        self.assertEqual(
            release_pr.get_repo_target_branch("104corp/104crm-lib", "staging"),
            "staging/lib",
        )
        self.assertEqual(
            release_pr.get_repo_target_branch("104corp/104crm-lib", "prod"),
            "prod/lib",
        )

        # 104crm-laravel-api
        self.assertEqual(
            release_pr.get_repo_target_branch("104corp/104crm-laravel-api", "staging"),
            "staging-k8s",
        )
        self.assertEqual(
            release_pr.get_repo_target_branch("104corp/104crm-laravel-api", "prod"),
            "master-k8s",
        )

        # 104-service-km
        self.assertEqual(
            release_pr.get_repo_target_branch("104corp/104-service-km", "prod"),
            "prod",
        )

        # default repos
        self.assertEqual(
            release_pr.get_repo_target_branch("104corp/104crm-laravel", "staging"),
            "staging",
        )
        self.assertEqual(
            release_pr.get_repo_target_branch("104corp/104crm-laravel", "prod"),
            "master",
        )

    def test_extract_jira_issues_from_text(self):
        sample_text = """
        feat(order): update logic [SERU-12484]
        Merge pull request #1993 from 104corp/feature/SERU-12827
        Merge branch 'feature/SERU-9999_fix-something' into release/SERVICE-0922
        Release ticket: PMOJBVIP-30282
        HTTP-500 error handling
        """
        extracted = release_pr.extract_jira_issues_from_text(
            text=sample_text,
            ticket_id="PMOJBVIP-30282",
            branch_name="release/SERVICE-0922",
        )

        self.assertIn("SERU-12484", extracted)
        self.assertIn("SERU-12827", extracted)
        self.assertIn("SERU-9999", extracted)
        # Must exclude release ticket
        self.assertNotIn("PMOJBVIP-30282", extracted)
        # Must exclude release branch
        self.assertNotIn("SERVICE-0922", extracted)
        # Must exclude excluded prefixes
        self.assertNotIn("HTTP-500", extracted)

    def test_sort_jira_keys(self):
        keys = ["SERU-12827", "SERU-99", "SERU-12484"]
        sorted_keys = release_pr.sort_jira_keys(keys)
        self.assertEqual(sorted_keys, ["SERU-99", "SERU-12484", "SERU-12827"])

    def test_format_output_message(self):
        task1 = release_pr.RepoTask(
            repo="104corp/104crm-b",
            is_static=False,
            head_branch="release/SERVICE-0922",
            target_branch="staging/project",
            display_name="104crm-b",
        )
        task2 = release_pr.RepoTask(
            repo="104corp/104crm-b",
            is_static=True,
            head_branch="release/SERVICE-0922_static",
            target_branch="staging/static",
            display_name="104crm-b-static",
        )
        task3 = release_pr.RepoTask(
            repo="104corp/104crm-laravel",
            is_static=False,
            head_branch="release/SERVICE-0922",
            target_branch="staging",
            display_name="104crm-laravel",
        )

        pr_results = [
            release_pr.RepoScanResult(
                task=task1,
                branch_exists=True,
                pr_url="https://github.com/104corp/104crm-b/pull/2015",
            ),
            release_pr.RepoScanResult(
                task=task2,
                branch_exists=True,
                pr_url="https://github.com/104corp/104crm-b/pull/2016",
            ),
            release_pr.RepoScanResult(
                task=task3,
                branch_exists=True,
                pr_url="https://github.com/104corp/104crm-laravel/pull/6483",
            ),
        ]

        output = release_pr.format_output_message(
            pr_results=pr_results,
            env_label="STG",
            all_issues=["SERU-12827", "SERU-12484"],
            ticket_id="PMOJBVIP-30282",
            jira_base_url="https://104corp.atlassian.net",
        )

        expected = "\n".join(
            [
                "104crm-b: https://github.com/104corp/104crm-b/pull/2015",
                "104crm-b-static: https://github.com/104corp/104crm-b/pull/2016",
                "104crm-laravel: https://github.com/104corp/104crm-laravel/pull/6483",
                "麻煩幫我簽一下 STG PR 感謝",
                "-----------------------------------------------------------------",
                "issue:",
                "https://104corp.atlassian.net/browse/SERU-12484",
                "https://104corp.atlassian.net/browse/SERU-12827",
                "上線單: https://104corp.atlassian.net/browse/PMOJBVIP-30282",
            ]
        )

        self.assertEqual(output, expected)

    def test_load_release_config_from_file(self):
        project_root = Path(__file__).resolve().parents[1]
        config = release_pr.load_release_config(project_root=project_root)
        self.assertIn("104corp/104crm-b", config.tracked_repos)
        self.assertTrue(config.has_static("104corp/104crm-b"))
        self.assertEqual(
            config.get_target_branch("104corp/104crm-b", "staging", is_static=False),
            "staging/project",
        )
        self.assertEqual(
            config.get_target_branch("104corp/104crm-b", "staging", is_static=True),
            "staging/static",
        )
        self.assertEqual(
            config.managers,
            ["cindy006", "yinmax225", "104lindalee"],
        )

    def test_custom_release_config_overrides(self):
        custom_cfg = release_pr.ReleaseConfig(
            default_env="staging",
            default_targets={"develop": "dev", "staging": "stg-main", "prod": "production"},
            managers=["boss1", "boss2"],
            tracked_repos=["my-org/custom-repo"],
            repos={
                "my-org/custom-repo": {
                    "has_static": True,
                    "targets": {"staging": "stg/custom"},
                    "static_targets": {"staging": "stg/custom-static"},
                }
            },
        )
        self.assertEqual(custom_cfg.managers, ["boss1", "boss2"])
        self.assertTrue(custom_cfg.has_static("my-org/custom-repo"))
        self.assertEqual(
            custom_cfg.get_target_branch("my-org/custom-repo", "staging", is_static=False),
            "stg/custom",
        )
        self.assertEqual(
            custom_cfg.get_target_branch("my-org/custom-repo", "staging", is_static=True),
            "stg/custom-static",
        )
        # Fallback to default_targets for untracked env
        self.assertEqual(
            custom_cfg.get_target_branch("my-org/custom-repo", "prod", is_static=False),
            "production",
        )

    def test_is_stg_or_prod(self):
        # Canonical env is staging / prod
        self.assertTrue(release_pr.is_stg_or_prod("staging", "develop"))
        self.assertTrue(release_pr.is_stg_or_prod("prod", "any_branch"))

        # Target branch contains staging / prod / master keywords
        self.assertTrue(release_pr.is_stg_or_prod("develop", "staging/project"))
        self.assertTrue(release_pr.is_stg_or_prod("develop", "staging/static"))
        self.assertTrue(release_pr.is_stg_or_prod("develop", "prod/project"))
        self.assertTrue(release_pr.is_stg_or_prod("develop", "master"))
        self.assertTrue(release_pr.is_stg_or_prod("develop", "master-k8s"))

        # Pure develop branch with develop env
        self.assertFalse(release_pr.is_stg_or_prod("develop", "develop"))
        self.assertFalse(release_pr.is_stg_or_prod("develop", "develop_static"))
        self.assertFalse(release_pr.is_stg_or_prod("develop", "develop-k8s"))

    def test_resolve_task_reviewers(self):
        managers = ["cindy006", "yinmax225", "104lindalee"]

        # STG/PROD automatically includes all managers
        revs = release_pr.resolve_task_reviewers(
            is_stg_prod=True,
            managers=managers,
        )
        self.assertEqual(revs, ["cindy006", "yinmax225", "104lindalee"])

        # STG/PROD merges extra reviewers and ignores duplicates
        revs_extra = release_pr.resolve_task_reviewers(
            is_stg_prod=True,
            managers=managers,
            user_reviewers="cindy006, extra_dev",
        )
        self.assertEqual(revs_extra, ["cindy006", "yinmax225", "104lindalee", "extra_dev"])

        # If author is one of the managers, exclude author
        revs_self = release_pr.resolve_task_reviewers(
            is_stg_prod=True,
            managers=managers,
            author="cindy006",
        )
        self.assertEqual(revs_self, ["yinmax225", "104lindalee"])

        # Develop does NOT automatically include managers unless specified
        revs_dev = release_pr.resolve_task_reviewers(
            is_stg_prod=False,
            managers=managers,
        )
        self.assertEqual(revs_dev, [])

        revs_dev_custom = release_pr.resolve_task_reviewers(
            is_stg_prod=False,
            managers=managers,
            user_reviewers="dev_lead",
        )
        self.assertEqual(revs_dev_custom, ["dev_lead"])

    @patch("subprocess.run")
    def test_fetch_pr_reviewer_info(self, mock_run):
        # PR view response
        mock_pr_res = MagicMock()
        mock_pr_res.returncode = 0
        mock_pr_res.stdout = """{
            "user": {"login": "dev_author"},
            "requested_reviewers": [
                {"login": "cindy006"},
                {"login": "104lindalee"}
            ]
        }"""

        # PR reviews response
        mock_rev_res = MagicMock()
        mock_rev_res.returncode = 0
        mock_rev_res.stdout = """[
            {"user": {"login": "yinmax225"}, "state": "APPROVED"}
        ]"""

        mock_run.side_effect = [mock_pr_res, mock_rev_res]

        reviewers, author = release_pr.fetch_pr_reviewer_info("104corp/104crm-b", 1234)
        self.assertEqual(author, "dev_author")
        self.assertEqual(reviewers, {"cindy006", "104lindalee", "yinmax225"})

    @patch("subprocess.run")
    def test_add_pr_reviewers(self, mock_run):
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_run.return_value = mock_res

        ok = release_pr.add_pr_reviewers("104corp/104crm-b", 1234, ["cindy006", "yinmax225"])
        self.assertTrue(ok)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("repos/104corp/104crm-b/pulls/1234/requested_reviewers", cmd[2])

    @patch("release_pr.add_pr_reviewers")
    @patch("release_pr.fetch_pr_reviewer_info")
    @patch("release_pr.fetch_existing_pr")
    @patch("release_pr.scan_repo_issues")
    @patch("release_pr.check_branch_exists")
    @patch("subprocess.run")
    def test_process_repo_task_existing_pr_missing_manager(
        self,
        mock_run,
        mock_check_branch,
        mock_scan_issues,
        mock_fetch_existing,
        mock_fetch_reviewer_info,
        mock_add_reviewers,
    ):
        mock_check_branch.return_value = True
        mock_scan_issues.return_value = set()
        mock_fetch_existing.return_value = (
            "https://github.com/104corp/104crm-b/pull/2025",
            2025,
            "Old Title",
            "OPEN",
        )
        # cindy006 and 104lindalee already there, but yinmax225 is missing
        mock_fetch_reviewer_info.return_value = ({"cindy006", "104lindalee"}, "dev_author")
        mock_add_reviewers.return_value = True

        mock_edit_res = MagicMock()
        mock_edit_res.returncode = 0
        mock_run.return_value = mock_edit_res

        task = release_pr.RepoTask(
            repo="104corp/104crm-b",
            is_static=False,
            head_branch="release/SERVICE-0922",
            target_branch="staging/project",
            display_name="104crm-b",
        )

        res = release_pr.process_repo_task(
            task=task,
            pr_title="[STG] 0922 上線列車 PR: PMOJBVIP-30282",
            ticket_id="PMOJBVIP-30282",
            canonical_env="staging",
            managers=["cindy006", "yinmax225", "104lindalee"],
        )

        self.assertEqual(res.action, "updated")
        mock_add_reviewers.assert_called_once_with("104corp/104crm-b", 2025, ["yinmax225"])
        self.assertIn("已補上主管 Reviewer: yinmax225", res.reviewer_status)

    @patch("release_pr.fetch_existing_pr")
    @patch("release_pr.scan_repo_issues")
    @patch("release_pr.check_branch_exists")
    @patch("subprocess.run")
    def test_process_repo_task_creates_pr_with_managers(
        self,
        mock_run,
        mock_check_branch,
        mock_scan_issues,
        mock_fetch_existing,
    ):
        mock_check_branch.return_value = True
        mock_scan_issues.return_value = set()
        mock_fetch_existing.return_value = None

        mock_create_res = MagicMock()
        mock_create_res.returncode = 0
        mock_create_res.stdout = "https://github.com/104corp/104crm-b/pull/2026\n"
        mock_run.return_value = mock_create_res

        task = release_pr.RepoTask(
            repo="104corp/104crm-b",
            is_static=False,
            head_branch="release/SERVICE-0922",
            target_branch="staging/project",
            display_name="104crm-b",
        )

        res = release_pr.process_repo_task(
            task=task,
            pr_title="[STG] 0922 上線列車 PR: PMOJBVIP-30282",
            ticket_id="PMOJBVIP-30282",
            canonical_env="staging",
            managers=["cindy006", "yinmax225", "104lindalee"],
        )

        self.assertEqual(res.action, "created")
        self.assertEqual(res.pr_number, 2026)
        self.assertIn("已加入主管 Reviewer: cindy006, yinmax225, 104lindalee", res.reviewer_status)

        # Verify command had --reviewer args
        create_cmd = mock_run.call_args[0][0]
        self.assertIn("--reviewer", create_cmd)
        indices = [i for i, x in enumerate(create_cmd) if x == "--reviewer"]
        reviewers_passed = [create_cmd[i + 1] for i in indices]
        self.assertEqual(reviewers_passed, ["cindy006", "yinmax225", "104lindalee"])


if __name__ == "__main__":
    unittest.main()

