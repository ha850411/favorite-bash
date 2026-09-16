"""Batch merge approved Pull Requests across microservice repositories."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Set, Tuple


PR_URL_PATTERN = re.compile(
    r"https://github\.com/(?P<repo>[^/\s]+/[^/\s]+)/pull/(?P<number>[0-9]+)"
)
ISSUE_URL_PATTERN = re.compile(
    r"https://github\.com/(?P<repo>[^/\s]+/[^/\s]+)/issues/(?P<number>[0-9]+)"
)
TICKET_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+-[0-9]+)\b")

DEFAULT_TARGET_REPO = "104corp/104-service-release-automation"


@dataclass
class PrMergeItem:
    url: str
    repo: str
    number: int
    title: str = ""
    state: str = ""  # OPEN, MERGED, CLOSED
    review_decision: Optional[str] = None  # APPROVED, REVIEW_REQUIRED, CHANGES_REQUESTED, None
    mergeable: str = ""  # MERGEABLE, CONFLICTING, UNKNOWN
    head_ref: str = ""
    base_ref: str = ""
    status: str = "pending"  # merged, already_merged, not_approved, closed, failed, skipped
    error_message: Optional[str] = None


def read_clipboard() -> str:
    """Read contents from macOS or Linux clipboard."""
    if shutil.which("pbpaste"):
        try:
            return subprocess.check_output(["pbpaste"], text=True, errors="replace")
        except Exception:
            pass
    elif shutil.which("wl-paste"):
        try:
            return subprocess.check_output(["wl-paste"], text=True, errors="replace")
        except Exception:
            pass
    elif shutil.which("xclip"):
        try:
            return subprocess.check_output(
                ["xclip", "-selection", "clipboard", "-o"], text=True, errors="replace"
            )
        except Exception:
            pass
    return ""


def extract_pr_urls_from_text(text: str) -> List[str]:
    """Find all GitHub pull request URLs in text while preserving order and uniqueness."""
    seen: Set[str] = set()
    urls: List[str] = []
    for match in PR_URL_PATTERN.finditer(text):
        url = match.group(0).rstrip(".,;)>'\"")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def extract_ticket_id_from_text(text: str) -> Optional[str]:
    """Look for 上線單 or ticket ID in text."""
    match = re.search(r"上線單[:：]\s*(?:https?://[^/\s]+/browse/)?([A-Z0-9_-]+)", text)
    if match:
        return match.group(1).upper()
    return None


def fetch_prs_from_github_issue(issue_ref: str) -> Tuple[List[str], Optional[str]]:
    """Fetch PR URLs from an issue body (by issue number or full URL)."""
    target_repo = DEFAULT_TARGET_REPO
    issue_num = issue_ref

    url_match = ISSUE_URL_PATTERN.match(issue_ref)
    if url_match:
        target_repo = url_match.group("repo")
        issue_num = url_match.group("number")

    cmd = ["gh", "issue", "view", issue_num, "--repo", target_repo, "--json", "body,title"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return [], None

    try:
        data = json.loads(res.stdout)
        body = data.get("body", "")
        title = data.get("title", "")
        ticket = extract_ticket_id_from_text(body) or extract_ticket_id_from_text(title)
        return extract_pr_urls_from_text(body), ticket
    except Exception:
        return [], None


def fetch_prs_for_branch(
    branch: str, target_env: str, project_root: Path
) -> List[str]:
    """Scan tracked repos for open PRs matching branch and environment using release-pr.json."""
    from release_pr import (
        load_release_config,
        normalize_target_env,
        fetch_existing_pr,
    )

    config = load_release_config(project_root=project_root)
    canonical_env, _ = normalize_target_env(target_env)
    urls: List[str] = []

    for repo in config.tracked_repos:
        main_target = config.get_target_branch(repo, canonical_env, is_static=False)
        main_pr = fetch_existing_pr(repo, branch, main_target, state="OPEN")
        if main_pr and main_pr[0]:
            urls.append(main_pr[0])

        if config.has_static(repo):
            static_target = config.get_target_branch(repo, canonical_env, is_static=True)
            static_pr = fetch_existing_pr(repo, f"{branch}_static", static_target, state="OPEN")
            if static_pr and static_pr[0]:
                urls.append(static_pr[0])

    return urls


def get_pr_details(url: str) -> Optional[PrMergeItem]:
    """Query GitHub CLI for PR review decision, state, and mergeable status."""
    match = PR_URL_PATTERN.match(url)
    if not match:
        return None

    repo = match.group("repo")
    number = int(match.group("number"))

    cmd = [
        "gh",
        "pr",
        "view",
        url,
        "--json",
        "title,state,reviewDecision,mergeable,headRefName,baseRefName",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return PrMergeItem(
            url=url,
            repo=repo,
            number=number,
            status="error",
            error_message=(res.stderr or res.stdout).strip(),
        )

    try:
        data = json.loads(res.stdout)
        return PrMergeItem(
            url=url,
            repo=repo,
            number=number,
            title=data.get("title", ""),
            state=data.get("state", "UNKNOWN").upper(),
            review_decision=data.get("reviewDecision"),
            mergeable=data.get("mergeable", "UNKNOWN").upper(),
            head_ref=data.get("headRefName", ""),
            base_ref=data.get("baseRefName", ""),
        )
    except Exception as e:
        return PrMergeItem(
            url=url,
            repo=repo,
            number=number,
            status="error",
            error_message=str(e),
        )


def execute_merge(
    item: PrMergeItem,
    method: str = "merge",
    ticket_id: Optional[str] = None,
    dry_run: bool = False,
) -> bool:
    """Merge the specified pull request."""
    if dry_run:
        item.status = "merged (dry-run)"
        return True

    cmd = ["gh", "pr", "merge", item.url, f"--{method}"]
    if ticket_id and item.title and ticket_id not in item.title:
        cmd.extend(["--subject", f"{item.title} [{ticket_id}]"])

    res = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if res.returncode == 0:
        item.status = "merged"
        return True
    else:
        item.status = "failed"
        item.error_message = (res.stderr or res.stdout).strip()
        return False


def run_merge_prs(
    inputs: Sequence[str],
    project_root: Path,
    method: str = "merge",
    force: bool = False,
    dry_run: bool = False,
    explicit_ticket: Optional[str] = None,
) -> int:
    """Main batch merge execution logic."""
    urls: List[str] = []
    detected_ticket: Optional[str] = explicit_ticket

    # 1. Inspect inputs
    if inputs:
        combined_text = " ".join(inputs)
        # Direct PR URLs in arguments
        found_urls = extract_pr_urls_from_text(combined_text)
        if found_urls:
            urls = found_urls
            if not detected_ticket:
                detected_ticket = extract_ticket_id_from_text(combined_text)
        # Issue URL or Issue number (e.g. 42 or full issue URL)
        elif len(inputs) == 1 and (
            inputs[0].isdigit() or ISSUE_URL_PATTERN.match(inputs[0])
        ):
            print(f"📋 正在讀取 GitHub Issue ({inputs[0]})...")
            urls, issue_ticket = fetch_prs_from_github_issue(inputs[0])
            if not detected_ticket:
                detected_ticket = issue_ticket
        # Branch & Environment (e.g. release/SERVICE-0922 staging)
        elif len(inputs) >= 2 and (
            inputs[1] in ("staging", "develop", "prod", "stg", "dev", "production")
            or inputs[0].startswith("release/")
        ):
            branch = inputs[0] if inputs[0].startswith("release/") else inputs[1]
            env = inputs[1] if inputs[0].startswith("release/") else inputs[0]
            if len(inputs) >= 3 and TICKET_PATTERN.match(inputs[0]):
                detected_ticket = inputs[0]
                branch = inputs[1]
                env = inputs[2]
            print(f"🔍 正在掃描分支 {branch} ({env}) 相關之 PR...")
            urls = fetch_prs_for_branch(branch, env, project_root)
        else:
            urls = extract_pr_urls_from_text(combined_text)

    # 2. Clipboard fallback (convenient for macOS pbcopy -> merge-pr)
    if not urls:
        clip_text = read_clipboard()
        if clip_text:
            clip_urls = extract_pr_urls_from_text(clip_text)
            if clip_urls:
                print("📋 偵測到剪貼簿中的 PR 列表，自動採用：")
                urls = clip_urls
                if not detected_ticket:
                    detected_ticket = extract_ticket_id_from_text(clip_text)

    # 3. Non-blocking Stdin pipe check
    if not urls and not sys.stdin.isatty():
        import select
        try:
            r, _, _ = select.select([sys.stdin], [], [], 0.0)
            if r:
                pipe_input = sys.stdin.read()
                urls = extract_pr_urls_from_text(pipe_input)
                if not detected_ticket:
                    detected_ticket = extract_ticket_id_from_text(pipe_input)
        except Exception:
            pass

    if not urls:
        print("❌ 找不到任何可合併的 PR 網址！")
        print("💡 用法範例：")
        print("  1) 直接執行 (自動讀取剪貼簿中的 PR 清單):")
        print("     merge-pr")
        print("  2) 指定 PR 網址:")
        print("     merge-pr https://github.com/104corp/104crm-b/pull/2015 https://github.com/104corp/104crm-laravel/pull/6483")
        print("  3) 指定 Release 分支與環境:")
        print("     merge-pr release/SERVICE-0922 staging")
        print("  4) 指定 GitHub Issue 編號或網址:")
        print("     merge-pr 42")
        return 1

    print(f"\n🔍 共找到 {len(urls)} 個待處理 PR：")
    for u in urls:
        print(f"  • {u}")
    print()

    items: List[PrMergeItem] = []
    for u in urls:
        item = get_pr_details(u)
        if item:
            items.append(item)

    # Process merges
    success_count = 0
    already_merged_count = 0
    not_approved_count = 0
    failed_count = 0
    skipped_count = 0

    print("🚀 開始執行 PR 狀態確認與批次 Merge...\n" + "-" * 55)

    for item in items:
        osc8_url = f"\033]8;;{item.url}\a{item.repo}#{item.number}\033]8;;\a"
        title_str = f" ({item.title})" if item.title else ""
        print(f"🔎 檢查: {osc8_url}{title_str}")

        if item.status == "error":
            print(f"  ⚠️ 無法讀取 PR 資訊，略過: {item.error_message}")
            skipped_count += 1
            print()
            continue

        if item.state == "MERGED":
            print("  ✅ 已經處於 MERGED 狀態，略過。")
            item.status = "already_merged"
            already_merged_count += 1
            print()
            continue

        if item.state == "CLOSED":
            print("  🚫 PR 已關閉 (CLOSED) 且未合併，略過。")
            item.status = "closed"
            skipped_count += 1
            print()
            continue

        # Review decision check
        is_approved = item.review_decision == "APPROVED"
        if not is_approved and not force:
            decision_label = item.review_decision or "尚未簽核 (PENDING)"
            print(f"  ⏳ 主管尚未通過審核 (狀態: {decision_label})，略過合併。")
            print("     💡 若確認需強制合併，可加上 -f 或 --force 參數。")
            item.status = "not_approved"
            not_approved_count += 1
            print()
            continue

        action_label = "強制 Merge" if (not is_approved and force) else "Merge"
        dry_label = " [預覽]" if dry_run else ""
        print(f"  ⚡ 審核通過，正在執行 {action_label}{dry_label}...")

        ok = execute_merge(
            item,
            method=method,
            ticket_id=detected_ticket,
            dry_run=dry_run,
        )
        if ok:
            print("  ✔ 合併成功！")
            success_count += 1
        else:
            print(f"  ❌ 合併失敗: {item.error_message}")
            failed_count += 1
        print()

    print("=" * 55)
    print("📊 執行統計：")
    print(f"  ✅ 成功合併: {success_count} 個")
    if already_merged_count > 0:
        print(f"  ♻️  早已合併: {already_merged_count} 個")
    if not_approved_count > 0:
        print(f"  ⏳ 待主管審核 (略過): {not_approved_count} 個")
    if failed_count > 0:
        print(f"  ❌ 合併失敗: {failed_count} 個")
    if skipped_count > 0:
        print(f"  ⏭️  其他略過: {skipped_count} 個")
    print("=" * 55)

    if not_approved_count > 0:
        print("\n⚠️ 提示：上述部分 PR 因主管尚未 Approve 而略過。")
        print("  待主管簽核完成後，再次執行 `merge-pr` 即可一鍵合併！")

    return 0 if failed_count == 0 else 1


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="merge-pr",
        description="批次檢查並合併主管已 Review Approve 之 Pull Requests",
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="PR 網址、Release 分支、或 GitHub Issue 編號/網址 (若不提供則自動讀取剪貼簿)",
    )
    parser.add_argument(
        "-m",
        "--method",
        choices=["merge", "squash", "rebase"],
        default="merge",
        help="Git 合併方式 (預設: merge，符合上線列車規範)",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="強制合併，略過 Reviewer APPROVED 檢查",
    )
    parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="預覽檢查 PR 審核與合併狀態，不實際在 GitHub 執行 Merge",
    )
    parser.add_argument(
        "-t",
        "--ticket",
        help="手動指定上線單號 (例如 PMOJBVIP-30282)",
    )

    return parser.parse_args(argv)


def main(
    argv: Optional[Sequence[str]] = None, project_root: Optional[Path] = None
) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent

    args = parse_arguments(argv)

    return run_merge_prs(
        inputs=args.inputs,
        project_root=project_root,
        method=args.method,
        force=args.force,
        dry_run=args.dry_run,
        explicit_ticket=args.ticket,
    )
