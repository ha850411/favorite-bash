"""Scan closed Jira feature branches and interactively delete selected refs."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import termios
import time
import tty
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


TICKET_PATTERN = re.compile(
    r"^feature/(?P<ticket>SERU-[0-9]+)(?:$|[._/-].*)$", re.IGNORECASE
)
REQUIRED_JIRA_VARS = ("JIRA_URL", "JIRA_USERNAME", "JIRA_API_TOKEN")


@dataclass(frozen=True)
class BranchCandidate:
    repo: str
    branch: str
    ticket: str


@dataclass(frozen=True)
class JiraStatus:
    ticket: str
    name: str
    category_key: str
    error: Optional[str] = None
    assignee: str = "未指派"

    @property
    def is_closed(self) -> bool:
        return self.error is None and self.category_key.lower() == "done"


def extract_ticket(branch: str) -> Optional[str]:
    """Return the normalized Jira key from a supported feature branch name."""
    match = TICKET_PATTERN.match(branch)
    return match.group("ticket").upper() if match else None


def load_env_file(path: Path, environ: Dict[str, str]) -> None:
    """Load simple KEY=VALUE entries without executing the env file as shell code."""
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


def find_env_file(project_root: Path, explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        return Path(explicit).expanduser().resolve()

    candidates = [project_root / "jira.env", Path.cwd() / "jira.env"]
    seen = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen and resolved.is_file():
            return resolved
        seen.add(resolved)
    return None


def read_repos(config_path: Path) -> List[str]:
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"找不到設定檔：{config_path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"無法讀取設定檔 {config_path}：{exc}") from exc

    repos = data.get("tracked_repos")
    if not isinstance(repos, list):
        raise ValueError(f"設定檔 {config_path} 缺少 tracked_repos 陣列")

    result = []
    seen = set()
    for repo in repos:
        if isinstance(repo, str) and re.fullmatch(r"[^/\s]+/[^/\s]+", repo) and repo not in seen:
            result.append(repo)
            seen.add(repo)
    if not result:
        raise ValueError(f"設定檔 {config_path} 沒有有效的 tracked_repos")
    return result


def scan_repo_branches(repo: str) -> Tuple[List[BranchCandidate], int]:
    """Use gh in GET-only mode and return Jira-shaped feature branches."""
    command = [
        "gh",
        "api",
        "--method",
        "GET",
        "--paginate",
        f"repos/{repo}/branches?per_page=100",
        "--jq",
        ".[].name",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "gh api 執行失敗"
        raise RuntimeError(message)

    candidates: List[BranchCandidate] = []
    branch_count = 0
    for branch in completed.stdout.splitlines():
        branch = branch.strip()
        if not branch:
            continue
        branch_count += 1
        ticket = extract_ticket(branch)
        if ticket:
            candidates.append(BranchCandidate(repo=repo, branch=branch, ticket=ticket))
    return candidates, branch_count


def _http_error_message(exc: HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        messages = payload.get("errorMessages") or []
        if messages:
            return "; ".join(str(item) for item in messages)
        if payload.get("message"):
            return str(payload["message"])
    except (ValueError, OSError):
        pass
    return f"HTTP {exc.code} {exc.reason}"


def fetch_jira_status(
    ticket: str,
    jira_url: str,
    username: str,
    token: str,
    retries: int = 2,
) -> JiraStatus:
    endpoint = (
        f"{jira_url.rstrip('/')}/rest/api/3/issue/{quote(ticket)}"
        "?fields=status,assignee"
    )
    credentials = base64.b64encode(f"{username}:{token}".encode("utf-8")).decode("ascii")
    request = Request(
        endpoint,
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": f"Basic {credentials}",
            "User-Agent": "favorite-bash-feature-branch-scan/1.0",
        },
    )

    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            status = payload.get("fields", {}).get("status", {})
            category = status.get("statusCategory", {})
            name = str(status.get("name") or "未知")
            category_key = str(category.get("key") or "")
            raw_assignee = payload.get("fields", {}).get("assignee")
            if raw_assignee:
                assignee = str(
                    raw_assignee.get("displayName")
                    or raw_assignee.get("emailAddress")
                    or raw_assignee.get("accountId")
                    or "未知"
                )
            else:
                assignee = "未指派"
            if not category_key:
                return JiraStatus(
                    ticket,
                    name,
                    "",
                    "Jira 回應缺少 statusCategory.key",
                    assignee,
                )
            return JiraStatus(ticket, name, category_key, assignee=assignee)
        except HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if retryable and attempt < retries:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    delay = min(float(retry_after), 10.0) if retry_after else 1.0 + attempt
                except ValueError:
                    delay = 1.0 + attempt
                time.sleep(delay)
                continue
            return JiraStatus(ticket, "查詢失敗", "", _http_error_message(exc))
        except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            if attempt < retries:
                time.sleep(1.0 + attempt)
                continue
            return JiraStatus(ticket, "查詢失敗", "", str(exc))

    return JiraStatus(ticket, "查詢失敗", "", "未知錯誤")


def fetch_all_jira_statuses(
    tickets: Iterable[str],
    jira_url: str,
    username: str,
    token: str,
    workers: int,
) -> Dict[str, JiraStatus]:
    unique_tickets = sorted(set(tickets))
    results: Dict[str, JiraStatus] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_jira_status, ticket, jira_url, username, token): ticket
            for ticket in unique_tickets
        }
        for future in as_completed(futures):
            ticket = futures[future]
            try:
                results[ticket] = future.result()
            except Exception as exc:  # Defensive: retain a partial report.
                results[ticket] = JiraStatus(ticket, "查詢失敗", "", str(exc))
    return results


def _display_width(value: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in value)


def _pad(value: str, width: int) -> str:
    return value + " " * max(0, width - _display_width(value))


def _truncate(value: str, width: int) -> str:
    if _display_width(value) <= width:
        return value
    if width <= 1:
        return "…"[:width]

    result = ""
    used = 0
    for char in value:
        char_width = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if used + char_width > width - 1:
            break
        result += char
        used += char_width
    return result + "…"


def print_table(rows: Sequence[Tuple[str, str, str, str, str]]) -> None:
    headers = ("Repository", "Branch", "Jira", "Status", "Assignee")
    all_rows = [headers, *rows]
    widths = [max(_display_width(row[index]) for row in all_rows) for index in range(5)]
    print("  ".join(_pad(headers[index], widths[index]) for index in range(5)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(_pad(row[index], widths[index]) for index in range(5)))


def print_simple_branch_list(
    candidates: Sequence[BranchCandidate],
    jira_statuses: Mapping[str, JiraStatus],
) -> None:
    """Print a compact, headerless list suitable for copying after cancellation."""
    rows = [
        (
            candidate.repo,
            candidate.branch,
            candidate.ticket,
            jira_statuses[candidate.ticket].name,
            jira_statuses[candidate.ticket].assignee,
        )
        for candidate in candidates
    ]
    if not rows:
        return

    widths = [
        max(_display_width(row[index]) for row in rows)
        for index in range(4)
    ]
    for row in rows:
        print(
            "  ".join(_pad(row[index], widths[index]) for index in range(4))
            + f"  {row[4]}"
        )


def delete_remote_branch(candidate: BranchCandidate) -> Optional[str]:
    """Delete one remote ref, returning an error message when deletion fails."""
    encoded_branch = quote(candidate.branch, safe="")
    command = [
        "gh",
        "api",
        "--method",
        "DELETE",
        f"repos/{candidate.repo}/git/refs/heads/{encoded_branch}",
        "--silent",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode == 0:
        return None
    return completed.stderr.strip() or completed.stdout.strip() or "GitHub API 刪除失敗"


def _render_selection_menu(
    candidates: Sequence[BranchCandidate],
    jira_statuses: Mapping[str, JiraStatus],
    cursor: int,
    checked: Sequence[bool],
) -> None:
    print("\033[2J\033[H", end="")
    terminal_size = shutil.get_terminal_size(fallback=(120, 24))
    terminal_lines = terminal_size.lines
    print("Jira Done branches｜預設全部不勾選\n")

    desired_widths = (
        min(30, max([_display_width("Repository"), *(_display_width(item.repo) for item in candidates)])),
        min(60, max([_display_width("Branch"), *(_display_width(item.branch) for item in candidates)])),
        min(14, max([_display_width("Jira"), *(_display_width(item.ticket) for item in candidates)])),
        min(12, max([_display_width("Status"), *(_display_width(jira_statuses[item.ticket].name) for item in candidates)])),
        min(26, max([_display_width("Assignee"), *(_display_width(jira_statuses[item.ticket].assignee) for item in candidates)])),
    )
    # 8 characters for cursor/checkbox/index and five visually clear separators.
    column_budget = max(5, terminal_size.columns - 23)
    if sum(desired_widths) <= column_budget:
        column_widths = desired_widths
    elif column_budget >= 34:
        repo_width = max(10, int(column_budget * 0.23))
        jira_width = max(4, int(column_budget * 0.13))
        status_width = max(6, int(column_budget * 0.10))
        assignee_width = max(8, int(column_budget * 0.20))
        branch_width = max(
            6,
            column_budget - repo_width - jira_width - status_width - assignee_width,
        )
        column_widths = (
            repo_width,
            branch_width,
            jira_width,
            status_width,
            assignee_width,
        )
    else:
        # Very narrow terminals still stay on one line, with aggressive truncation.
        weights = (20, 34, 14, 12, 20)
        column_widths = tuple(max(1, column_budget * weight // 100) for weight in weights)

    headers = ("Repository", "Branch", "Jira", "Status", "Assignee")
    header_cells = [
        _pad(_truncate(value, width), width)
        for value, width in zip(headers, column_widths)
    ]
    print("       # │ " + " │ ".join(header_cells))
    print("─────────┼─" + "─┼─".join("─" * width for width in column_widths))

    visible_count = max(1, terminal_lines - 9)
    start = min(
        max(0, cursor - visible_count + 1),
        max(0, len(candidates) - visible_count),
    )
    end = min(len(candidates), start + visible_count)
    if start:
        print(f"  ↑ 尚有 {start} 筆")
    for index in range(start, end):
        candidate = candidates[index]
        pointer = "❯" if index == cursor else " "
        checkbox = "✓" if checked[index] else " "
        status = jira_statuses[candidate.ticket]
        values = (
            candidate.repo,
            candidate.branch,
            candidate.ticket,
            status.name,
            status.assignee,
        )
        cells = [
            _pad(_truncate(value, width), width)
            for value, width in zip(values, column_widths)
        ]
        print(f"{pointer} [{checkbox}] {index + 1:>2} │ " + " │ ".join(cells))
    if end < len(candidates):
        print(f"  ↓ 尚有 {len(candidates) - end} 筆")
    selected_count = sum(checked)
    print(f"已勾選 {selected_count}/{len(candidates)}")
    print("↑/↓・j/k 移動  Space 勾選  a 全選  Enter 送出並刪除  q 取消")


def select_branches_interactively(
    candidates: Sequence[BranchCandidate],
    jira_statuses: Mapping[str, JiraStatus],
) -> Optional[List[BranchCandidate]]:
    """Return submitted branches, or None when the user cancels/cannot interact."""
    if not candidates:
        return []
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("非互動式終端，略過刪除；可使用 --json 取得掃描結果。", file=sys.stderr)
        return None

    checked = [False] * len(candidates)
    cursor = 0
    original_settings = termios.tcgetattr(sys.stdin.fileno())
    print("\033[?1049h\033[?25l", end="", flush=True)
    try:
        # cbreak keeps normal terminal output processing (notably CR/LF), while
        # still allowing single-key input. Raw mode makes each printed line
        # start at the previous line's ending column in some terminals.
        tty.setcbreak(sys.stdin.fileno())
        while True:
            _render_selection_menu(candidates, jira_statuses, cursor, checked)
            sys.stdout.flush()
            key = sys.stdin.read(1)
            if key == "\x1b":
                suffix = sys.stdin.read(2)
                if suffix == "[A":
                    cursor = (cursor - 1) % len(candidates)
                elif suffix == "[B":
                    cursor = (cursor + 1) % len(candidates)
            elif key in ("k", "K"):
                cursor = (cursor - 1) % len(candidates)
            elif key in ("j", "J"):
                cursor = (cursor + 1) % len(candidates)
            elif key == " ":
                checked[cursor] = not checked[cursor]
            elif key in ("a", "A"):
                new_value = not all(checked)
                checked = [new_value] * len(candidates)
            elif key in ("\r", "\n"):
                return [item for item, is_checked in zip(candidates, checked) if is_checked]
            elif key in ("q", "Q", "\x03", "\x04"):
                return None
            elif key == "":
                return None
    except KeyboardInterrupt:
        return None
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, original_settings)
        print("\033[?25h\033[?1049l", end="", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="feature-branch-scan",
        description="掃描 feature/SERU-* branches，勾選並刪除 Jira 已關單的 branches。",
        epilog="只有互動選單中勾選且按 Enter 送出的 branches 才會被刪除。",
    )
    parser.add_argument("--config", help="repository 設定檔（預設為專案的 pr-scan.json）")
    parser.add_argument("--env", dest="env_file", help="Jira env 檔（預設為專案的 jira.env）")
    parser.add_argument(
        "-r",
        "--repo",
        action="append",
        dest="repos",
        metavar="OWNER/REPO",
        help="只掃描指定 repository，可重複使用",
    )
    parser.add_argument("--workers", type=int, default=6, help="Jira 平行查詢數（預設：6）")
    parser.add_argument("--json", action="store_true", help="以 JSON 輸出完整結果（唯讀，不進入刪除選單）")
    return parser


def _validate_repos(repos: Sequence[str]) -> Optional[str]:
    invalid = [repo for repo in repos if not re.fullmatch(r"[^/\s]+/[^/\s]+", repo)]
    return invalid[0] if invalid else None


def main(
    argv: Optional[Sequence[str]] = None,
    project_root: Optional[Path] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = (project_root or Path(__file__).resolve().parent.parent).resolve()
    runtime_env: Dict[str, str] = dict(os.environ if environ is None else environ)

    if shutil.which("gh") is None:
        parser.error("找不到 GitHub CLI（gh），請先安裝並執行 gh auth login")
    if not 1 <= args.workers <= 20:
        parser.error("--workers 必須介於 1 到 20")

    env_file = find_env_file(project_root, args.env_file)
    if env_file:
        load_env_file(env_file, runtime_env)
    missing_vars = [key for key in REQUIRED_JIRA_VARS if not runtime_env.get(key)]
    if missing_vars:
        location = str(env_file) if env_file else str(project_root / "jira.env")
        parser.error(f"{location} 缺少必要設定：{', '.join(missing_vars)}")

    if args.repos:
        repos = args.repos
    else:
        config_path = Path(args.config).expanduser().resolve() if args.config else project_root / "pr-scan.json"
        try:
            repos = read_repos(config_path)
        except ValueError as exc:
            parser.error(str(exc))
    invalid_repo = _validate_repos(repos)
    if invalid_repo:
        parser.error(f"repository 格式錯誤：{invalid_repo}（預期 owner/repo）")

    candidates: List[BranchCandidate] = []
    repo_errors: Dict[str, str] = {}
    total_branches = 0
    for index, repo in enumerate(repos, start=1):
        if not args.json:
            print(f"[{index}/{len(repos)}] 掃描 {repo} ...", file=sys.stderr)
        try:
            found, count = scan_repo_branches(repo)
            candidates.extend(found)
            total_branches += count
        except RuntimeError as exc:
            repo_errors[repo] = str(exc)

    jira_statuses = fetch_all_jira_statuses(
        (candidate.ticket for candidate in candidates),
        runtime_env["JIRA_URL"],
        runtime_env["JIRA_USERNAME"],
        runtime_env["JIRA_API_TOKEN"],
        args.workers,
    )

    suggested = [
        candidate
        for candidate in candidates
        if jira_statuses.get(candidate.ticket)
        and jira_statuses[candidate.ticket].is_closed
    ]
    issue_errors = {
        ticket: status.error
        for ticket, status in jira_statuses.items()
        if status.error is not None
    }

    if args.json:
        payload = {
            "read_only": True,
            "summary": {
                "repositories": len(repos),
                "branches_scanned": total_branches,
                "feature_branches_matched": len(candidates),
                "suggested_deletions": len(suggested),
            },
            "branches": [
                {
                    **asdict(candidate),
                    "jira_status": jira_statuses[candidate.ticket].name,
                    "jira_status_category": jira_statuses[candidate.ticket].category_key,
                    "jira_assignee": jira_statuses[candidate.ticket].assignee,
                    "suggested": jira_statuses[candidate.ticket].is_closed,
                    "error": jira_statuses[candidate.ticket].error,
                }
                for candidate in candidates
            ],
            "repo_errors": repo_errors,
            "jira_errors": issue_errors,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        is_interactive = sys.stdin.isatty() and sys.stdout.isatty()
        if suggested and not is_interactive:
            print("\n待刪除 branches（Jira status category = Done）")
            rows = [
                (
                    candidate.repo,
                    candidate.branch,
                    candidate.ticket,
                    jira_statuses[candidate.ticket].name,
                    jira_statuses[candidate.ticket].assignee,
                )
                for candidate in suggested
            ]
            print_table(rows)
        elif not suggested:
            print("\n待刪除 branches（Jira status category = Done）")
            print("（沒有）")
        for repo, error in repo_errors.items():
            print(f"警告：{repo} 掃描失敗：{error}", file=sys.stderr)
        for ticket, error in issue_errors.items():
            print(f"警告：{ticket} Jira 查詢失敗：{error}", file=sys.stderr)

        selected = select_branches_interactively(suggested, jira_statuses)
        print(
            f"掃描完成：{len(repos)} repos、{total_branches} branches、"
            f"{len(candidates)} 個 feature/SERU-* branches、{len(suggested)} 個建議刪除。"
        )
        if selected is None:
            print("已取消，未刪除任何 branch。")
            if is_interactive and suggested:
                print("\n本次掃描清單：")
                print_simple_branch_list(suggested, jira_statuses)
        elif not selected:
            print("未勾選任何 branch，未執行刪除。")
        else:
            print(f"\n開始刪除 {len(selected)} 個已送出的 branches：")
            delete_errors: Dict[str, str] = {}
            for candidate in selected:
                error = delete_remote_branch(candidate)
                identity = f"{candidate.repo}:{candidate.branch}"
                if error:
                    delete_errors[identity] = error
                    print(f"✗ {identity}：{error}", file=sys.stderr)
                else:
                    print(f"✓ {identity}")
            print(
                f"刪除完成：成功 {len(selected) - len(delete_errors)}、"
                f"失敗 {len(delete_errors)}。"
            )
            if delete_errors:
                return 2

    return 2 if repo_errors or issue_errors else 0
