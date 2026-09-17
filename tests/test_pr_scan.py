from __future__ import annotations

import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from pr_scan import (
    normalize_target_env,
    get_env_display_label,
    get_env_branch_from_mapping,
    repo_has_static,
    is_static_branch_name,
    resolve_target_branch,
    get_candidate_branches_for_task,
    get_task_default_base,
    build_scan_tasks,
)


class PrScanCoreTests(unittest.TestCase):
    def setUp(self):
        self.sample_config = {
            "default_target_base": "develop",
            "default_environments": {
                "lab": "lab",
                "stg": "staging",
                "prod": "master",
            },
            "tracked_repos": [
                "104corp/104crm-laravel",
                "104corp/104crm-laravel-api",
                "104corp/104crm-b",
            ],
            "repos": {
                "104corp/104crm-laravel": {
                  "default_base": "develop",
                  "environments": {
                    "lab": "lab",
                    "stg": "staging",
                    "prod": "master",
                  },
                },
                "104corp/104crm-laravel-api": {
                  "default_base": "develop-k8s",
                  "environments": {
                    "lab": "lab-k8s",
                    "stg": "staging-k8s",
                    "prod": "master-k8s",
                  },
                },
                "104corp/104crm-b": {
                  "default_base": "develop",
                  "has_static": True,
                  "environments": {
                    "lab": "lab/project",
                    "stg": "staging/project",
                    "prod": "prod/project",
                  },
                  "static_environments": {
                    "lab": "lab/static",
                    "stg": "staging/static",
                    "prod": "prod/static",
                  },
                  "branch_rules": [
                    {
                      "pattern": "*static*",
                      "base": "develop_static",
                    },
                    {
                      "pattern": "release/*",
                      "base": "develop",
                    },
                  ],
                },
            },
        }

    def test_normalize_target_env(self):
        self.assertEqual(normalize_target_env("lab"), "lab")
        self.assertEqual(normalize_target_env("LAB"), "lab")
        self.assertEqual(normalize_target_env("stg"), "stg")
        self.assertEqual(normalize_target_env("staging"), "stg")
        self.assertEqual(normalize_target_env("STAGING"), "stg")
        self.assertEqual(normalize_target_env("prod"), "prod")
        self.assertEqual(normalize_target_env("production"), "prod")
        self.assertEqual(normalize_target_env("PROD"), "prod")
        self.assertIsNone(normalize_target_env("release/SERVICE-0811"))
        self.assertIsNone(normalize_target_env("feature/SERU-12345"))
        self.assertIsNone(normalize_target_env(""))
        self.assertIsNone(normalize_target_env(None))

    def test_get_env_display_label(self):
        self.assertEqual(get_env_display_label("lab"), "LAB")
        self.assertEqual(get_env_display_label("stg"), "STG")
        self.assertEqual(get_env_display_label("prod"), "PROD")

    def test_get_env_branch_from_mapping(self):
        mapping = {"lab": "lab/project", "staging": "staging/project", "master": "prod/project"}
        self.assertEqual(get_env_branch_from_mapping(mapping, "lab"), "lab/project")
        self.assertEqual(get_env_branch_from_mapping(mapping, "stg"), "staging/project")
        self.assertEqual(get_env_branch_from_mapping(mapping, "prod"), "prod/project")
        self.assertIsNone(get_env_branch_from_mapping({}, "lab"))

    def test_repo_has_static(self):
        self.assertTrue(repo_has_static("104corp/104crm-b", {}))
        self.assertTrue(repo_has_static("104corp/104crm-c", {}))
        self.assertTrue(repo_has_static("custom-repo", {"has_static": True}))
        self.assertTrue(repo_has_static("custom-repo", {"static_environments": {}}))
        self.assertFalse(repo_has_static("104corp/104crm-laravel", {}))
        self.assertFalse(repo_has_static("104corp/104crm-laravel-api", {}))

    def test_is_static_branch_name(self):
        self.assertTrue(is_static_branch_name("feature/SERU-12553-static"))
        self.assertTrue(is_static_branch_name("feature/SERU-12553_static"))
        self.assertTrue(is_static_branch_name("feature/static-SERU-12553"))
        self.assertTrue(is_static_branch_name("develop_static"))
        self.assertTrue(is_static_branch_name("prod/static"))
        self.assertFalse(is_static_branch_name("feature/SERU-12553"))
        self.assertFalse(is_static_branch_name("release/SERVICE-0811"))
        self.assertFalse(is_static_branch_name("develop"))

    def test_resolve_target_branch_environment(self):
        # 104crm-laravel
        laravel_cfg = self.sample_config["repos"]["104corp/104crm-laravel"]
        self.assertEqual(
            resolve_target_branch("104corp/104crm-laravel", laravel_cfg, self.sample_config, "", "lab"),
            "lab",
        )
        self.assertEqual(
            resolve_target_branch("104corp/104crm-laravel", laravel_cfg, self.sample_config, "", "stg"),
            "staging",
        )
        self.assertEqual(
            resolve_target_branch("104corp/104crm-laravel", laravel_cfg, self.sample_config, "", "prod"),
            "master",
        )

        # 104crm-laravel-api
        api_cfg = self.sample_config["repos"]["104corp/104crm-laravel-api"]
        self.assertEqual(
            resolve_target_branch("104corp/104crm-laravel-api", api_cfg, self.sample_config, "", "lab"),
            "lab-k8s",
        )
        self.assertEqual(
            resolve_target_branch("104corp/104crm-laravel-api", api_cfg, self.sample_config, "", "stg"),
            "staging-k8s",
        )
        self.assertEqual(
            resolve_target_branch("104corp/104crm-laravel-api", api_cfg, self.sample_config, "", "prod"),
            "master-k8s",
        )

        # 104crm-b: project vs static
        b_cfg = self.sample_config["repos"]["104corp/104crm-b"]
        self.assertEqual(
            resolve_target_branch("104corp/104crm-b", b_cfg, self.sample_config, "", "lab", is_static=False),
            "lab/project",
        )
        self.assertEqual(
            resolve_target_branch("104corp/104crm-b", b_cfg, self.sample_config, "", "lab", is_static=True),
            "lab/static",
        )
        self.assertEqual(
            resolve_target_branch("104corp/104crm-b", b_cfg, self.sample_config, "", "stg", is_static=False),
            "staging/project",
        )
        self.assertEqual(
            resolve_target_branch("104corp/104crm-b", b_cfg, self.sample_config, "", "stg", is_static=True),
            "staging/static",
        )
        self.assertEqual(
            resolve_target_branch("104corp/104crm-b", b_cfg, self.sample_config, "", "prod", is_static=False),
            "prod/project",
        )
        self.assertEqual(
            resolve_target_branch("104corp/104crm-b", b_cfg, self.sample_config, "", "prod", is_static=True),
            "prod/static",
        )

    def test_resolve_target_branch_custom(self):
        b_cfg = self.sample_config["repos"]["104corp/104crm-b"]
        # Custom branch
        self.assertEqual(
            resolve_target_branch("104corp/104crm-b", b_cfg, self.sample_config, "release/SERVICE-0811", None, is_static=False),
            "release/SERVICE-0811",
        )
        self.assertEqual(
            resolve_target_branch("104corp/104crm-b", b_cfg, self.sample_config, "release/SERVICE-0811", None, is_static=True),
            "release/SERVICE-0811_static",
        )

    def test_get_candidate_branches_for_task(self):
        # Project task with regular branch
        candidates = get_candidate_branches_for_task("feature/SERU-12553", is_static=False)
        self.assertEqual(candidates, ["feature/SERU-12553"])

        # Static task with regular branch
        candidates = get_candidate_branches_for_task("feature/SERU-12553", is_static=True)
        self.assertIn("feature/SERU-12553_static", candidates)
        self.assertIn("feature/SERU-12553-static", candidates)

        # Static task with static branch name
        candidates = get_candidate_branches_for_task("feature/SERU-12553-static", is_static=True)
        self.assertEqual(candidates, ["feature/SERU-12553-static"])

        # Project task when given a static branch name
        candidates = get_candidate_branches_for_task("feature/SERU-12553-static", is_static=False)
        self.assertEqual(candidates, ["feature/SERU-12553", "feature/SERU-12553-static"])

    def test_get_task_default_base(self):
        b_cfg = self.sample_config["repos"]["104corp/104crm-b"]
        base, label = get_task_default_base("104corp/104crm-b", b_cfg, "lab/project", self.sample_config, is_static=False)
        self.assertEqual(base, "develop")

        base_static, label_static = get_task_default_base("104corp/104crm-b", b_cfg, "lab/static", self.sample_config, is_static=True)
        self.assertEqual(base_static, "develop_static")

    def test_build_scan_tasks(self):
        tasks = build_scan_tasks(
            all_repos=["104corp/104crm-laravel", "104corp/104crm-b"],
            config_data=self.sample_config,
            branch_a="feature/SERU-12553",
            raw_branch_b="lab",
            target_env="lab",
        )
        self.assertEqual(len(tasks), 3)

        # Task 1: 104crm-laravel
        self.assertEqual(tasks[0]["repo"], "104corp/104crm-laravel")
        self.assertFalse(tasks[0]["is_static"])
        self.assertEqual(tasks[0]["target_branch"], "lab")

        # Task 2: 104crm-b project
        self.assertEqual(tasks[1]["repo"], "104corp/104crm-b")
        self.assertFalse(tasks[1]["is_static"])
        self.assertEqual(tasks[1]["target_branch"], "lab/project")
        self.assertIn("[project]", tasks[1]["display_name"])

        # Task 3: 104crm-b static
        self.assertEqual(tasks[2]["repo"], "104corp/104crm-b")
        self.assertTrue(tasks[2]["is_static"])
        self.assertEqual(tasks[2]["target_branch"], "lab/static")
        self.assertIn("[static]", tasks[2]["display_name"])
        self.assertIn("feature/SERU-12553_static", tasks[2]["head_candidates"])
        self.assertIn("feature/SERU-12553-static", tasks[2]["head_candidates"])


if __name__ == "__main__":
    unittest.main()
