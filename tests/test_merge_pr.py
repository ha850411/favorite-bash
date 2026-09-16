import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "lib" / "merge_pr.py"
SPEC = importlib.util.spec_from_file_location("merge_pr", MODULE_PATH)
merge_pr = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = merge_pr
SPEC.loader.exec_module(merge_pr)


class MergePrTests(unittest.TestCase):
    def test_extract_pr_urls_from_text(self):
        sample = """
        104crm-b: https://github.com/104corp/104crm-b/pull/2015
        104crm-b-static: https://github.com/104corp/104crm-b/pull/2016
        104crm-laravel: https://github.com/104corp/104crm-laravel/pull/6483
        麻煩幫我簽一下 STG PR 感謝
        上線單: https://104corp.atlassian.net/browse/PMOJBVIP-30282
        """
        urls = merge_pr.extract_pr_urls_from_text(sample)
        self.assertEqual(
            urls,
            [
                "https://github.com/104corp/104crm-b/pull/2015",
                "https://github.com/104corp/104crm-b/pull/2016",
                "https://github.com/104corp/104crm-laravel/pull/6483",
            ],
        )

    def test_extract_ticket_id_from_text(self):
        sample = "上線單: https://104corp.atlassian.net/browse/PMOJBVIP-30282"
        self.assertEqual(
            merge_pr.extract_ticket_id_from_text(sample), "PMOJBVIP-30282"
        )
        sample2 = "上線單: PMOJBVIP-12345"
        self.assertEqual(
            merge_pr.extract_ticket_id_from_text(sample2), "PMOJBVIP-12345"
        )

    def test_execute_merge_dry_run(self):
        item = merge_pr.PrMergeItem(
            url="https://github.com/104corp/104crm-b/pull/2015",
            repo="104corp/104crm-b",
            number=2015,
            title="[STG] Test PR",
            state="OPEN",
            review_decision="APPROVED",
        )
        ok = merge_pr.execute_merge(item, dry_run=True)
        self.assertTrue(ok)
        self.assertEqual(item.status, "merged (dry-run)")


if __name__ == "__main__":
    unittest.main()
