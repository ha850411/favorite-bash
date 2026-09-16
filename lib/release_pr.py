"""Batch create release PRs and generate summary output for favorite-bash."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Set, Tuple


DEFAULT_REPOS = [
    "104corp/104crm-b",
    "104corp/104crm-c",
    "104corp/104crm-wsp-jb-b",
    "104corp/104crm-lib",
    "104corp/104crm-laravel",
    "104corp/104crm-dashboard",
    "104corp/104crm-laravel-api",
    "104corp/104crm-laravel-aes",
    "104corp/104-service-km",
    "104corp/104-service-docker-image-hub",
]

JIRA_KEY_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+-[0-9]+)\b")
FEATURE_BRANCH_TICKET_PATTERN = re.compile(
    r"feature/(?P<ticket>[A-Z][A-Z0-9]+-[0-9]+)(?:$|[._/-].*)", re.IGNORECASE
)
EXCLUDED_KEY_PREFIXES = {
    "SERVICE",
    "HTTP",
    "HTTPS",
    "UTF",
    "ISO",
    "SHA",
    "MD5",
    "RFC",
    "API",
}

DEFAULT_JIRA_URL = "https://104corp.atlassian.net"


@dataclass(frozen=True)
class RepoTask:
    repo: str
    is_static: bool
    head_branch: str
    target_branch: str
    display_name: str


@dataclass
class RepoScanResult:
    task: RepoTask
    branch_exists: bool
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    action: str = "skipped"  # "created", "updated", "existing", "no_diff", "skipped", "error"
    error_message: Optional[str] = None
    detected_issues: Set[str] = field(default_factory=set)


def load_env_file(path: Path, environ: Dict[str, str]) -> None:
    """Load KEY=VALUE lines into environ if not already present."""
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        environ.setdefault(key, value)


def find_jira_env(project_root: Path) -> Optional[Path]:
    for candidate in (project_root / "jira.env", Path.cwd() / "jira.env"):
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    return None


@dataclass
class ReleaseConfig:
    default_env: str = "staging"
    default_targets: Dict[str, str] = field(
        default_factory=lambda: {
            "develop": "develop",
            "staging": "staging",
            "prod": "master",
        }
    )
    tracked_repos: List[str] = field(default_factory=lambda: list(DEFAULT_REPOS))
    repos: Dict[str, Dict[str, any]] = field(default_factory=dict)
    config_file_path: Optional[Path] = None

    def has_static(self, repo: str) -> bool:
        repo_cfg = self.repos.get(repo, {})
        return bool(repo_cfg.get("has_static", False))

    def get_target_branch(
        self, repo: str, target_env: str, is_static: bool = False
    ) -> str:
        repo_cfg = self.repos.get(repo, {})
        if is_static:
            static_targets = repo_cfg.get("static_targets", {})
            if target_env in static_targets:
                return static_targets[target_env]
            default_base = self.default_targets.get(target_env, target_env)
            return f"{default_base}_static"

        targets = repo_cfg.get("targets", {})
        if target_env in targets:
            return targets[target_env]

        return self.default_targets.get(target_env, target_env)


def find_release_pr_config(
    project_root: Optional[Path] = None, explicit: Optional[str | Path] = None
) -> Optional[Path]:
    """Locate release-pr.json config file."""
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if p.is_file():
            return p

    candidates: List[Path] = [
        Path.cwd() / "release-pr.json",
        Path.cwd() / ".release-pr.json",
        Path.home() / ".config" / "favorite-bash" / "release-pr.json",
    ]
    if project_root:
        candidates.append(project_root / "release-pr.json")

    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            continue
        if resolved not in seen and resolved.is_file():
            return resolved
        seen.add(resolved)

    return None


def load_release_config(
    project_root: Optional[Path] = None, explicit_path: Optional[str | Path] = None
) -> ReleaseConfig:
    """Load configuration from release-pr.json or return default config."""
    config_file = find_release_pr_config(
        project_root=project_root, explicit=explicit_path
    )
    if not config_file:
        return ReleaseConfig()

    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
        default_env = data.get("default_env", "staging")
        default_targets = data.get(
            "default_targets",
            {
                "develop": "develop",
                "staging": "staging",
                "prod": "master",
            },
        )
        tracked_repos = data.get("tracked_repos", list(DEFAULT_REPOS))
        repos = data.get("repos", {})

        return ReleaseConfig(
            default_env=default_env,
            default_targets=default_targets,
            tracked_repos=tracked_repos,
            repos=repos,
            config_file_path=config_file,
        )
    except Exception as e:
        print(
            f"⚠️ 讀取設定檔 {config_file} 失敗: {e}，將使用預設設定。",
            file=sys.stderr,
        )
        return ReleaseConfig(config_file_path=config_file)


def read_tracked_repos(config: Optional[ReleaseConfig] = None) -> List[str]:
    if config is None:
        config = load_release_config()
    return list(config.tracked_repos)


def normalize_target_env(raw_env: str) -> Tuple[str, str]:
    """Return (canonical_env, env_label).

    canonical_env is one of 'develop', 'staging', 'prod'.
    env_label is one of 'Develop', 'STG', 'PROD'.
    """
    env_lower = (raw_env or "").strip().lower()
    if env_lower in ("staging", "stg"):
        return "staging", "STG"
    elif env_lower in ("prod", "production"):
        return "prod", "PROD"
    elif env_lower in ("develop", "dev"):
        return "develop", "Develop"
    else:
        # Fallback to verbatim
        return env_lower, env_lower.upper()


def get_today_date_label(base_branch: str, target_env: str) -> str:
    """Return MMDD date string, extracting from branch when prod or develop if available."""
    today = datetime.now().strftime("%m%d")
    if target_env in ("prod", "develop"):
        match = re.search(r"([0-9]{4})$", base_branch)
        if match:
            return match.group(1)
    return today


def get_repo_target_branch(
    repo: str,
    target_env: str,
    is_static: bool = False,
    config: Optional[ReleaseConfig] = None,
) -> str:
    """Determine target branch for a given repository and environment from config."""
    if config is None:
        config = load_release_config()
    return config.get_target_branch(repo, target_env, is_static)


def build_pr_body(ticket_id: str, detected_issues: Sequence[str] = ()) -> str:
    issues_str = ", ".join(detected_issues) if detected_issues else ""
    return f"""## 關聯單號
- **需求單:** {issues_str}
- **上線單:** {ticket_id}

> 若該 PR 目標分支為 `staging` 或 `master`：
> 1. **PR 描述內容**：請務必填寫上方單號。
> 2. **Merge Commit Message**：合併時，請手動將「上線單號」填入 Commit 訊息中。

## 環境變數 / 配置變更 (Vault)
- [ ] 本次變更 **不涉及** 環境變數調整
- [ ] 本次變更 **涉及** 環境變數調整
    - [ ] 已將變數範例更新至 `.env.example`
    - [ ] 已確實提供 **上線車長(Release Manager)** 詳細資訊

## Author Self-Check
- [ ] **功能驗證**：我已在本地環境親自測試過，功能運作符合預期。
- [ ] **範圍控制**：確認除提升可測試性調整之外，**無** 夾帶與需求無關的程式碼改動。
    - *(若包含必要之額外改動，請務必在該段程式碼處留下 Comment 說明原委)*
- [ ] **測試覆蓋**：在非緊急狀況、時程壓力下，需求變更皆有對應自動化測試
- [ ] **本地驗證**：已於本地執行相關自動化測試（或說明未執行原因）

---

## Reviewer Only
- [ ] **行為正確性**：程式碼實際行為符合需求描述，無隱含副作用或邊界案例遺漏
- [ ] **例外與失敗情境**：需求相關的錯誤情境皆有合理處理，例外拋出與回傳行為一致且可預期
- [ ] **可讀性與簡化**：命名清楚、邏輯易讀，無明顯可合併或過度複雜的實作
- [ ] **測試合理性**：測試案例能反映實際使用情境，非僅為覆蓋率而寫  

---
*此 PR 由 [自動化腳本](https://github.com/104corp/favorite-bash) 產生*"""


def extract_jira_issues_from_text(
    text: str, ticket_id: str, branch_name: str
) -> Set[str]:
    """Extract valid Jira issue keys from text, excluding the release ticket and branch artifacts."""
    if not text:
        return set()

    found: Set[str] = set()
    ticket_id_upper = ticket_id.upper()
    branch_upper = branch_name.upper()

    for match in JIRA_KEY_PATTERN.finditer(text):
        raw_key = match.group(1).upper()
        prefix = raw_key.split("-")[0]
        # Ignore release tickets (PMOJBVIP), branch prefixes (SERVICE), and non-jira tokens
        if prefix in EXCLUDED_KEY_PREFIXES or prefix == "PMOJBVIP":
            continue
        if raw_key == ticket_id_upper:
            continue
        if raw_key in branch_upper:
            continue
        found.add(raw_key)

    for match in FEATURE_BRANCH_TICKET_PATTERN.finditer(text):
        raw_key = match.group("ticket").upper()
        prefix = raw_key.split("-")[0]
        if prefix not in EXCLUDED_KEY_PREFIXES and prefix != "PMOJBVIP" and raw_key != ticket_id_upper:
            found.add(raw_key)

    return found


def sort_jira_keys(keys: Iterable[str]) -> List[str]:
    """Natural sort for Jira issue keys (e.g. SERU-12484 before SERU-12827)."""
    def sort_key(k: str) -> Tuple[str, int]:
        parts = k.split("-", 1)
        prefix = parts[0]
        try:
            num = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            num = 0
        return prefix, num

    return sorted(set(keys), key=sort_key)


def check_branch_exists(repo: str, branch: str) -> bool:
    """Check if branch exists on GitHub remote."""
    cmd = ["gh", "api", f"repos/{repo}/branches/{branch}"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode == 0


def fetch_existing_pr(
    repo: str, head_branch: str, base_branch: str, state: str = "OPEN"
) -> Optional[Tuple[str, int, str, str]]:
    """Return (pr_url, pr_number, pr_title, pr_state) if a PR exists."""
    cmd = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--head",
        head_branch,
        "--base",
        base_branch,
        "--state",
        state,
        "--json",
        "number,url,title,state",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0 and res.stdout.strip():
        try:
            prs = json.loads(res.stdout)
            if prs and len(prs) > 0:
                first = prs[0]
                return (
                    first.get("url"),
                    first.get("number"),
                    first.get("title", ""),
                    first.get("state", ""),
                )
        except Exception:
            pass
    return None


def scan_repo_issues(
    repo: str, head_branch: str, target_branch: str, ticket_id: str
) -> Set[str]:
    """Scan compare commits and merged PRs for Jira ticket references."""
    issues: Set[str] = set()

    # 1. Compare target_branch...head_branch (only new commits for this release)
    comp_cmd = ["gh", "api", f"repos/{repo}/compare/{target_branch}...{head_branch}"]
    res_comp = subprocess.run(comp_cmd, capture_output=True, text=True)
    if res_comp.returncode == 0 and res_comp.stdout.strip():
        try:
            data = json.loads(res_comp.stdout)
            for c in data.get("commits", []):
                msg = c.get("commit", {}).get("message", "")
                issues |= extract_jira_issues_from_text(msg, ticket_id, head_branch)
        except Exception:
            pass

    # 2. PRs targeting/merged into head_branch
    pr_cmd = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--base",
        head_branch,
        "--state",
        "all",
        "--limit",
        "50",
        "--json",
        "number,title,headRefName,body",
    ]
    res_pr = subprocess.run(pr_cmd, capture_output=True, text=True)
    if res_pr.returncode == 0 and res_pr.stdout.strip():
        try:
            prs = json.loads(res_pr.stdout)
            for pr in prs:
                blob = f"{pr.get('headRefName', '')} {pr.get('title', '')} {pr.get('body', '')}"
                issues |= extract_jira_issues_from_text(blob, ticket_id, head_branch)
        except Exception:
            pass

    return issues


def process_repo_task(
    task: RepoTask,
    pr_title: str,
    ticket_id: str,
    reviewers: Optional[str] = None,
    dry_run: bool = False,
) -> RepoScanResult:
    """Check branch, scan issues, and create or update PR."""
    if not check_branch_exists(task.repo, task.head_branch):
        return RepoScanResult(task=task, branch_exists=False, action="skipped")

    # Branch exists! Scan for Jira issues
    detected_issues = scan_repo_issues(
        task.repo, task.head_branch, task.target_branch, ticket_id
    )

    pr_body = build_pr_body(ticket_id, sort_jira_keys(detected_issues))

    # Check for existing open PR
    existing = fetch_existing_pr(task.repo, task.head_branch, task.target_branch, state="OPEN")

    if dry_run:
        if existing:
            return RepoScanResult(
                task=task,
                branch_exists=True,
                pr_url=existing[0],
                pr_number=existing[1],
                action="existing (dry-run)",
                detected_issues=detected_issues,
            )
        # In dry run, check if PR exists in all states (e.g. was merged for this release)
        any_pr = fetch_existing_pr(task.repo, task.head_branch, task.target_branch, state="all")
        if any_pr and (ticket_id in any_pr[2] or any_pr[3] == "MERGED"):
            return RepoScanResult(
                task=task,
                branch_exists=True,
                pr_url=any_pr[0],
                pr_number=any_pr[1],
                action=f"{any_pr[3].lower()} (dry-run)",
                detected_issues=detected_issues,
            )

        # Check if there are diffs
        comp_cmd = ["gh", "api", f"repos/{task.repo}/compare/{task.target_branch}...{task.head_branch}"]
        res_comp = subprocess.run(comp_cmd, capture_output=True, text=True)
        ahead_by = 0
        if res_comp.returncode == 0 and res_comp.stdout.strip():
            try:
                ahead_by = json.loads(res_comp.stdout).get("ahead_by", 0)
            except Exception:
                ahead_by = 0

        if ahead_by > 0:
            return RepoScanResult(
                task=task,
                branch_exists=True,
                pr_url=f"https://github.com/{task.repo}/pull/(preview)",
                action="created (dry-run)",
                detected_issues=detected_issues,
            )
        else:
            return RepoScanResult(
                task=task,
                branch_exists=True,
                action="no_diff",
                detected_issues=detected_issues,
            )

    if existing:
        pr_url, pr_num, _, _ = existing
        # Update existing PR title and body
        edit_cmd = ["gh", "pr", "edit", pr_url, "--title", pr_title, "--body", pr_body]
        subprocess.run(edit_cmd, capture_output=True, text=True)
        return RepoScanResult(
            task=task,
            branch_exists=True,
            pr_url=pr_url,
            pr_number=pr_num,
            action="updated",
            detected_issues=detected_issues,
        )

    # Attempt to create PR
    create_cmd = [
        "gh",
        "pr",
        "create",
        "--repo",
        task.repo,
        "--head",
        task.head_branch,
        "--base",
        task.target_branch,
        "--title",
        pr_title,
        "--body",
        pr_body,
    ]
    if reviewers:
        create_cmd.extend(["--reviewer", reviewers])

    res = subprocess.run(create_cmd, capture_output=True, text=True)
    if res.returncode == 0 and res.stdout.strip():
        pr_url = res.stdout.strip().splitlines()[-1]
        return RepoScanResult(
            task=task,
            branch_exists=True,
            pr_url=pr_url,
            action="created",
            detected_issues=detected_issues,
        )

    # Failed to create: check if branch has no difference or already merged
    err = (res.stderr or res.stdout).strip()
    if "No commits between" in err or "already exists" in err:
        existing_again = fetch_existing_pr(
            task.repo, task.head_branch, task.target_branch, state="all"
        )
        if existing_again and (ticket_id in existing_again[2] or existing_again[3] == "MERGED"):
            return RepoScanResult(
                task=task,
                branch_exists=True,
                pr_url=existing_again[0],
                pr_number=existing_again[1],
                action=existing_again[3].lower(),
                detected_issues=detected_issues,
            )
        return RepoScanResult(
            task=task,
            branch_exists=True,
            action="no_diff",
            detected_issues=detected_issues,
        )

    return RepoScanResult(
        task=task,
        branch_exists=True,
        action="error",
        error_message=err,
        detected_issues=detected_issues,
    )


def format_output_message(
    pr_results: List[RepoScanResult],
    env_label: str,
    all_issues: Sequence[str],
    ticket_id: str,
    jira_base_url: str = DEFAULT_JIRA_URL,
) -> str:
    """Format final output matching user specification."""
    lines: List[str] = []

    # 1. PR list: "<display_name>: <pr_url>"
    for res in pr_results:
        if res.pr_url:
            lines.append(f"{res.task.display_name}: {res.pr_url}")

    # 2. Sign-off line
    lines.append(f"麻煩幫我簽一下 {env_label} PR 感謝")

    # 3. Divider
    lines.append("-----------------------------------------------------------------")

    # 4. Issues list
    lines.append("issue:")
    clean_jira_url = jira_base_url.rstrip("/")
    for issue in sort_jira_keys(all_issues):
        lines.append(f"{clean_jira_url}/browse/{issue}")

    # 5. Release ticket line
    lines.append(f"上線單: {clean_jira_url}/browse/{ticket_id}")

    return "\n".join(lines)


def copy_to_clipboard(text: str) -> bool:
    """Copy text to macOS pbcopy or xclip/wl-copy if available."""
    if shutil.which("pbcopy"):
        try:
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, close_fds=True)
            p.communicate(input=text.encode("utf-8"))
            return p.returncode == 0
        except Exception:
            return False
    elif shutil.which("wl-copy"):
        try:
            p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE, close_fds=True)
            p.communicate(input=text.encode("utf-8"))
            return p.returncode == 0
        except Exception:
            return False
    elif shutil.which("xclip"):
        try:
            p = subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE,
                close_fds=True,
            )
            p.communicate(input=text.encode("utf-8"))
            return p.returncode == 0
        except Exception:
            return False
    return False


def run_release_pr(
    ticket_id: str,
    source_branch: str,
    raw_env: str,
    project_root: Path,
    manual_issues: Sequence[str] = (),
    reviewers: Optional[str] = None,
    dry_run: bool = False,
    config: Optional[ReleaseConfig] = None,
    max_workers: int = 8,
) -> int:
    """Execute concurrent repo scan, PR creation, and format output."""
    if config is None:
        config = load_release_config(project_root=project_root)

    canonical_env, env_label = normalize_target_env(raw_env)
    today_label = get_today_date_label(source_branch, canonical_env)
    dynamic_pr_title = f"[{env_label}] {today_label} 上線列車 PR: {ticket_id}"

    # Load environment variables (from jira.env if present)
    environ: Dict[str, str] = dict(os.environ)
    jira_env_path = find_jira_env(project_root)
    if jira_env_path:
        load_env_file(jira_env_path, environ)

    jira_url = environ.get("JIRA_URL", DEFAULT_JIRA_URL).rstrip("/")
    if not reviewers:
        reviewers = environ.get("REVIEWERS") or environ.get("PR_REVIEWERS")

    # Build tasks based on configuration
    tasks: List[RepoTask] = []
    for repo in config.tracked_repos:
        repo_name = repo.split("/")[-1]

        # Main project task
        main_target = config.get_target_branch(repo, canonical_env, is_static=False)
        tasks.append(
            RepoTask(
                repo=repo,
                is_static=False,
                head_branch=source_branch,
                target_branch=main_target,
                display_name=repo_name,
            )
        )

        # Static branch task if configured in release-pr.json
        if config.has_static(repo):
            static_target = config.get_target_branch(repo, canonical_env, is_static=True)
            tasks.append(
                RepoTask(
                    repo=repo,
                    is_static=True,
                    head_branch=f"{source_branch}_static",
                    target_branch=static_target,
                    display_name=f"{repo_name}-static",
                )
            )

    config_info = (
        f" (設定檔: {config.config_file_path.name})"
        if config.config_file_path
        else ""
    )
    print(
        f"🚀 開始併發掃描 {len(tasks)} 個專案分支...{config_info} (單號: {ticket_id} | 來源: {source_branch} | 環境: {canonical_env})"
    )

    results: List[RepoScanResult] = []
    all_detected_issues: Set[str] = set(manual_issues)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                process_repo_task,
                task,
                dynamic_pr_title,
                ticket_id,
                reviewers,
                dry_run,
            ): task
            for task in tasks
        }
        for future in as_completed(future_map):
            try:
                res = future.result()
                results.append(res)
                all_detected_issues |= res.detected_issues
                if res.branch_exists and res.pr_url:
                    print(f"  ✔ [{res.action}] {res.task.display_name}: {res.pr_url}")
                elif res.branch_exists and res.action == "no_diff":
                    print(
                        f"  ℹ [無變更] {res.task.display_name}: 分支與目標分支無差異，略過建立 PR"
                    )
            except Exception as e:
                task = future_map[future]
                print(f"  ❌ 處理 {task.display_name} 失敗: {e}", file=sys.stderr)

    # Sort results according to original tasks order
    task_order = {t.display_name: i for i, t in enumerate(tasks)}
    results.sort(key=lambda r: task_order.get(r.task.display_name, 999))

    valid_prs = [r for r in results if r.pr_url]

    if not valid_prs:
        print("\n⚠️ 本次掃描沒有建立或找到任何 PR (可能分支皆無差異或遠端無此分支)。")
        if all_detected_issues:
            print(f"偵測到關聯單號：{', '.join(sort_jira_keys(all_detected_issues))}")
        return 0

    output_text = format_output_message(
        pr_results=valid_prs,
        env_label=env_label,
        all_issues=list(all_detected_issues),
        ticket_id=ticket_id,
        jira_base_url=jira_url,
    )

    print("\n" + "=" * 65)
    print(output_text)
    print("=" * 65 + "\n")

    if copy_to_clipboard(output_text):
        print("📋 已自動將上述內容複製至剪貼簿！可以直接貼上至發布通知。")

    return 0


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="release-pr",
        description="跨微服務專案併發掃描分支、發布 Release PR 並產製發布清單",
    )
    parser.add_argument(
        "ticket_id",
        nargs="?",
        help="上線單號 (例如: PMOJBVIP-30282)",
    )
    parser.add_argument(
        "source_branch",
        nargs="?",
        help="來源 Release 分支名稱 (例如: release/SERVICE-0922)",
    )
    parser.add_argument(
        "target_env",
        nargs="?",
        help="目標環境: develop, staging, prod (預設: staging)",
    )
    parser.add_argument(
        "extra_issues",
        nargs="*",
        help="手動附加的 Jira 需求單號 (例如: SERU-12484 SERU-12827)",
    )
    parser.add_argument(
        "-i",
        "--issue",
        action="append",
        default=[],
        dest="flag_issues",
        help="指定 Jira 需求單號 (可多次指定或逗點分隔)",
    )
    parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="僅進行併發掃描與預覽，不實際在 GitHub 上建立或修改 PR",
    )
    parser.add_argument(
        "-r",
        "--reviewer",
        help="指定 PR Reviewer 使用者名稱",
    )
    parser.add_argument(
        "-c",
        "--config",
        help="指定 release-pr.json 設定檔路徑",
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

    ticket_id = args.ticket_id
    source_branch = args.source_branch
    target_env = args.target_env

    # Check for interactive prompt if missing args and stdin is a TTY
    if sys.stdin.isatty():
        if not ticket_id:
            ticket_id = input("請輸入上線單號 (例如 PMOJBVIP-30282): ").strip()
        if not source_branch:
            source_branch = input("請輸入來源分支名稱 (例如 release/SERVICE-0922): ").strip()
        if not target_env:
            env_input = input("請輸入目標環境 (develop/staging/prod) [預設: staging]: ").strip()
            target_env = env_input if env_input else "staging"

    if not ticket_id or not source_branch or not target_env:
        print("❌ 參數錯誤！缺少必要參數。")
        print("💡 用法: release-pr <單號> <分支名稱> <環境(develop/staging/prod)> [需求單號...]")
        print("📝 範例: release-pr PMOJBVIP-30282 release/SERVICE-0922 staging")
        return 1

    # Aggregate manual issues
    manual_issues: List[str] = []
    for issue in args.extra_issues:
        for item in issue.replace(",", " ").split():
            item_clean = item.strip().upper()
            if item_clean:
                manual_issues.append(item_clean)
    for issue in args.flag_issues:
        for item in issue.replace(",", " ").split():
            item_clean = item.strip().upper()
            if item_clean:
                manual_issues.append(item_clean)

    config = load_release_config(project_root=project_root, explicit_path=args.config)

    return run_release_pr(
        ticket_id=ticket_id,
        source_branch=source_branch,
        raw_env=target_env,
        project_root=project_root,
        manual_issues=manual_issues,
        reviewers=args.reviewer,
        dry_run=args.dry_run,
        config=config,
    )
