#!/usr/bin/env python3
# ==============================================================================
# Favorite Bash - gh PR Scan Tool Core (pr-scan)
# 支援跨 Repositories 掃描分支、lab/stg/prod 環境分支解析、static 分支處理與批次 PR/Merge
# ==============================================================================

from __future__ import annotations

import fnmatch
import json
import os
import re
import select
import subprocess
import sys
import termios
import tty
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

C_CYAN = "\033[1;36m"
C_GREEN = "\033[1;32m"
C_YELLOW = "\033[1;33m"
C_RED = "\033[1;31m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_RESET = "\033[0m"


def normalize_target_env(raw_env: Optional[str]) -> Optional[str]:
    """正規化環境名稱為 'lab', 'stg', 'prod' 之一，若不是環境則回傳 None。"""
    if not raw_env:
        return None
    e = raw_env.strip().lower()
    if e in ("lab",):
        return "lab"
    elif e in ("stg", "staging"):
        return "stg"
    elif e in ("prod", "production"):
        return "prod"
    return None


def get_env_display_label(target_env: str) -> str:
    labels = {
        "lab": "LAB",
        "stg": "STG",
        "prod": "PROD",
    }
    return labels.get(target_env, target_env.upper())


def get_env_branch_from_mapping(mapping: Dict[str, Any], target_env: str) -> Optional[str]:
    if not mapping or not isinstance(mapping, dict) or not target_env:
        return None
    if target_env in mapping:
        return str(mapping[target_env])
    aliases = {
        "lab": ["lab"],
        "stg": ["stg", "staging"],
        "prod": ["prod", "production", "master"],
    }
    for alias in aliases.get(target_env, []):
        if alias in mapping:
            return str(mapping[alias])
    return None


def repo_has_static(repo: str, repo_cfg: Dict[str, Any]) -> bool:
    """判斷 repo 是否需要獨立區分 project 與 static 分支。"""
    if not isinstance(repo_cfg, dict):
        repo_cfg = {}
    if repo_cfg.get("has_static") is True:
        return True
    if "static_environments" in repo_cfg or "static_targets" in repo_cfg:
        return True
    branches_cfg = repo_cfg.get("branches")
    if isinstance(branches_cfg, dict) and "static" in branches_cfg:
        return True
    # 預設支援 104crm-b 與 104crm-c
    if repo in ("104corp/104crm-b", "104corp/104crm-c"):
        return True
    return False


def is_static_branch_name(branch: str) -> bool:
    """判斷分支名稱是否含有 static 關鍵字。"""
    return bool(re.search(r"(?:^|[._/-])static(?:$|[._/-])", branch, re.IGNORECASE)) or "static" in branch.lower()


def resolve_target_branch(
    repo: str,
    repo_cfg: Dict[str, Any],
    config_data: Dict[str, Any],
    raw_branch_b: str,
    target_env: Optional[str],
    is_static: bool = False,
) -> str:
    """解析 Repo 在特定環境或自訂分支時的目標分支 (Branch B) 名稱。"""
    if not isinstance(repo_cfg, dict):
        repo_cfg = {}
    if not isinstance(config_data, dict):
        config_data = {}

    if target_env:
        if is_static:
            static_map = (
                repo_cfg.get("static_environments")
                or repo_cfg.get("static_targets")
                or (repo_cfg.get("branches", {}).get("static") if isinstance(repo_cfg.get("branches"), dict) else None)
                or {}
            )
            branch = get_env_branch_from_mapping(static_map, target_env)
            if branch:
                return branch

            # Fallback: 基於 project 的分支加上 _static
            project_branch = resolve_target_branch(
                repo=repo,
                repo_cfg=repo_cfg,
                config_data=config_data,
                raw_branch_b=raw_branch_b,
                target_env=target_env,
                is_static=False,
            )
            if project_branch.endswith("_static") or project_branch.endswith("/static"):
                return project_branch
            return f"{project_branch}_static"
        else:
            env_map = (
                repo_cfg.get("environments")
                or repo_cfg.get("targets")
                or (repo_cfg.get("branches", {}).get("project") if isinstance(repo_cfg.get("branches"), dict) else None)
                or {}
            )
            branch = get_env_branch_from_mapping(env_map, target_env)
            if branch:
                return branch

            # 全域預設環境對應
            def_env_map = config_data.get("default_environments") or config_data.get("default_targets") or {}
            def_branch = get_env_branch_from_mapping(def_env_map, target_env)
            if def_branch:
                return def_branch

            # 內建預設
            builtin_defaults = {"lab": "lab", "stg": "staging", "prod": "master"}
            return builtin_defaults.get(target_env, target_env)
    else:
        # 自訂 Branch B (例如 release/SERVICE-0811)
        if is_static:
            if raw_branch_b.endswith("_static") or raw_branch_b.endswith("-static"):
                return raw_branch_b
            return f"{raw_branch_b}_static"
        return raw_branch_b


def get_candidate_branches_for_task(branch_a: str, is_static: bool) -> List[str]:
    """回傳該 Task 要在遠端依序檢查的 Branch A 候選名稱。"""
    if is_static:
        if is_static_branch_name(branch_a):
            return [branch_a]
        candidates = [
            f"{branch_a}_static",
            f"{branch_a}-static",
        ]
        if branch_a.startswith("feature/"):
            rest = branch_a[len("feature/"):]
            candidates.append(f"feature/static-{rest}")
            candidates.append(f"feature/static_{rest}")
        return candidates
    else:
        if is_static_branch_name(branch_a):
            # 若傳入的是 static 分支，嘗試反推 project 原分支
            stripped = re.sub(r"[-_]static$", "", branch_a, flags=re.IGNORECASE)
            candidates = []
            if stripped != branch_a:
                candidates.append(stripped)
            candidates.append(branch_a)
            return candidates
        return [branch_a]


def get_task_default_base(
    repo: str,
    repo_cfg: Dict[str, Any],
    target_branch: str,
    config_data: Dict[str, Any],
    is_static: bool = False,
) -> Tuple[str, str]:
    """取得當 Target Branch B 不存在時，建立該分支預設所依賴的來源 Base。"""
    default_base = config_data.get("default_target_base", "develop")
    source_label = "全域預設"

    if is_static:
        if "static_default_base" in repo_cfg:
            return repo_cfg["static_default_base"], "Repo Static 預設"
        rules = repo_cfg.get("branch_rules", [])
        for rule in rules:
            pattern = rule.get("pattern", "")
            target_b = rule.get("base", "")
            if pattern and target_b and fnmatch.fnmatch(target_branch, pattern):
                return target_b, f"規則 ({pattern})"
        return "develop_static", "Static 預設"

    if "default_base" in repo_cfg:
        default_base = repo_cfg["default_base"]
        source_label = "Repo 預設"

    rules = repo_cfg.get("branch_rules", [])
    for rule in rules:
        pattern = rule.get("pattern", "")
        target_b = rule.get("base", "")
        if pattern and target_b and target_branch and fnmatch.fnmatch(target_branch, pattern):
            default_base = target_b
            if pattern == "*":
                source_label = "Repo 預設 (*)"
            else:
                source_label = f"規則 ({pattern})"
            break

    return default_base, source_label


def build_scan_tasks(
    all_repos: List[str],
    config_data: Dict[str, Any],
    branch_a: str,
    raw_branch_b: str,
    target_env: Optional[str],
    arg_base_of_b: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """建立待掃描的任務清單，考慮單一 Repo 的 project 與 static 雙任務。"""
    repos_dict = config_data.get("repos", {})
    tasks = []
    idx = 1

    for repo in all_repos:
        repo_cfg = repos_dict.get(repo, {})
        has_static = repo_has_static(repo, repo_cfg)

        if has_static:
            # 1. Project Task
            target_b_proj = resolve_target_branch(
                repo=repo,
                repo_cfg=repo_cfg,
                config_data=config_data,
                raw_branch_b=raw_branch_b,
                target_env=target_env,
                is_static=False,
            )
            def_base_proj, src_label_proj = get_task_default_base(
                repo=repo,
                repo_cfg=repo_cfg,
                target_branch=target_b_proj,
                config_data=config_data,
                is_static=False,
            )
            tasks.append(
                {
                    "index": idx,
                    "repo": repo,
                    "is_static": False,
                    "display_name": f"{repo} [project]",
                    "head_candidates": get_candidate_branches_for_task(branch_a, is_static=False),
                    "target_branch": target_b_proj,
                    "default_base": def_base_proj,
                    "selected_base": arg_base_of_b if arg_base_of_b else def_base_proj,
                    "source_label": src_label_proj,
                }
            )
            idx += 1

            # 2. Static Task
            target_b_static = resolve_target_branch(
                repo=repo,
                repo_cfg=repo_cfg,
                config_data=config_data,
                raw_branch_b=raw_branch_b,
                target_env=target_env,
                is_static=True,
            )
            def_base_static, src_label_static = get_task_default_base(
                repo=repo,
                repo_cfg=repo_cfg,
                target_branch=target_b_static,
                config_data=config_data,
                is_static=True,
            )
            tasks.append(
                {
                    "index": idx,
                    "repo": repo,
                    "is_static": True,
                    "display_name": f"{repo} [static]",
                    "head_candidates": get_candidate_branches_for_task(branch_a, is_static=True),
                    "target_branch": target_b_static,
                    "default_base": def_base_static,
                    "selected_base": arg_base_of_b if arg_base_of_b else def_base_static,
                    "source_label": src_label_static,
                }
            )
            idx += 1
        else:
            target_b = resolve_target_branch(
                repo=repo,
                repo_cfg=repo_cfg,
                config_data=config_data,
                raw_branch_b=raw_branch_b,
                target_env=target_env,
                is_static=False,
            )
            def_base, src_label = get_task_default_base(
                repo=repo,
                repo_cfg=repo_cfg,
                target_branch=target_b,
                config_data=config_data,
                is_static=False,
            )
            tasks.append(
                {
                    "index": idx,
                    "repo": repo,
                    "is_static": False,
                    "display_name": repo,
                    "head_candidates": [branch_a],
                    "target_branch": target_b,
                    "default_base": def_base,
                    "selected_base": arg_base_of_b if arg_base_of_b else def_base,
                    "source_label": src_label,
                }
            )
            idx += 1

    return tasks


_GH_TOKEN: Optional[str] = None


def get_github_token() -> Optional[str]:
    global _GH_TOKEN
    if _GH_TOKEN:
        return _GH_TOKEN
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and token.strip():
        _GH_TOKEN = token.strip()
        return _GH_TOKEN
    try:
        res = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0 and res.stdout.strip():
            _GH_TOKEN = res.stdout.strip()
            os.environ["GH_TOKEN"] = _GH_TOKEN
            return _GH_TOKEN
    except Exception:
        pass
    return None


def http_request_json(
    url: str,
    token: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    method: Optional[str] = None,
    timeout: float = 8.0,
) -> Tuple[int, Any]:
    if token is None:
        token = get_github_token()
    headers = {
        "User-Agent": "favorite-bash/pr-scan",
        "Accept": "application/vnd.github.v3+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req_data = None
    if data is not None:
        req_data = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            body = resp.read().decode("utf-8")
            try:
                return status, json.loads(body)
            except Exception:
                return status, body
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")
            return e.code, json.loads(body)
        except Exception:
            return e.code, None
    except Exception:
        return -1, None


def fetch_compare_diff(repo: str, head_branch: str, base_branch: str, token: Optional[str] = None) -> Dict[str, Any]:
    token = token or get_github_token()
    if token:
        status, data = http_request_json(
            f"https://api.github.com/repos/{repo}/compare/{base_branch}...{head_branch}",
            token=token,
        )
        if status == 200 and isinstance(data, dict):
            commits = data.get("commits", [])
            files = data.get("files", [])
            additions = sum(f.get("additions", 0) for f in files)
            deletions = sum(f.get("deletions", 0) for f in files)
            return {
                "ahead_by": data.get("ahead_by", len(commits)),
                "commits_count": len(commits),
                "files_count": len(files),
                "additions": additions,
                "deletions": deletions,
                "commits": commits,
                "files": files,
            }
    res = subprocess.run(
        ["gh", "api", f"repos/{repo}/compare/{base_branch}...{head_branch}"],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0 and res.stdout.strip():
        try:
            data = json.loads(res.stdout)
            commits = data.get("commits", [])
            files = data.get("files", [])
            additions = sum(f.get("additions", 0) for f in files)
            deletions = sum(f.get("deletions", 0) for f in files)
            return {
                "ahead_by": data.get("ahead_by", len(commits)),
                "commits_count": len(commits),
                "files_count": len(files),
                "additions": additions,
                "deletions": deletions,
                "commits": commits,
                "files": files,
            }
        except Exception:
            pass
    return {
        "ahead_by": 0,
        "commits_count": 0,
        "files_count": 0,
        "additions": 0,
        "deletions": 0,
        "commits": [],
        "files": [],
    }


def check_existing_pr(
    repo: str, head_branch: str, base_branch: str, token: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    token = token or get_github_token()
    if token and "/" in repo:
        owner = repo.split("/")[0]
        status, prs = http_request_json(
            f"https://api.github.com/repos/{repo}/pulls?head={owner}:{head_branch}&base={base_branch}&state=open",
            token=token,
        )
        if status == 200 and isinstance(prs, list) and prs:
            return {
                "number": prs[0].get("number"),
                "url": prs[0].get("html_url") or prs[0].get("url"),
                "title": prs[0].get("title", ""),
            }
        elif status == 200 and isinstance(prs, list) and not prs:
            return None
    res = subprocess.run(
        [
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
            "OPEN",
            "--json",
            "number,url,title",
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0 and res.stdout.strip():
        try:
            prs = json.loads(res.stdout)
            if prs and len(prs) > 0:
                return prs[0]
        except Exception:
            pass
    return None


def scan_single_task(task: Dict[str, Any]) -> Dict[str, Any]:
    repo = task["repo"]
    target_branch = task["target_branch"]
    candidates = task["head_candidates"]
    token = get_github_token()

    head_branch = candidates[0]
    has_a = False

    # 檢測候選 Branch A 是否存在於遠端
    for cand in candidates:
        if token:
            st, _ = http_request_json(f"https://api.github.com/repos/{repo}/branches/{cand}", token=token)
            if st == 200:
                head_branch = cand
                has_a = True
                break
        else:
            res_a = subprocess.run(
                ["gh", "api", f"repos/{repo}/branches/{cand}", "--silent"],
                capture_output=True,
            )
            if res_a.returncode == 0:
                head_branch = cand
                has_a = True
                break

    has_b = False
    if has_a:
        if token:
            st, _ = http_request_json(f"https://api.github.com/repos/{repo}/branches/{target_branch}", token=token)
            has_b = (st == 200)
        else:
            res_b = subprocess.run(
                ["gh", "api", f"repos/{repo}/branches/{target_branch}", "--silent"],
                capture_output=True,
            )
            has_b = res_b.returncode == 0

    selected_base = task["selected_base"]
    compare_target = target_branch if has_b else selected_base
    diff_info = {
        "commits_count": 0,
        "files_count": 0,
        "additions": 0,
        "deletions": 0,
        "commits": [],
        "files": [],
    }
    if has_a:
        diff_info = fetch_compare_diff(repo, head_branch, compare_target, token=token)

    has_changes = diff_info["commits_count"] > 0
    existing_pr = check_existing_pr(repo, head_branch, target_branch, token=token) if (has_a and has_b) else None

    task_result = dict(task)
    task_result.update(
        {
            "head_branch": head_branch,
            "has_a": has_a,
            "has_b": has_b,
            "diff": diff_info,
            "has_changes": has_changes,
            "existing_pr": existing_pr,
            "selected": (has_a and (has_changes or existing_pr is not None)),
        }
    )
    return task_result


def scan_all_tasks(tasks: List[Dict[str, Any]], token: Optional[str] = None) -> List[Dict[str, Any]]:
    token = token or get_github_token()
    if not token:
        with ThreadPoolExecutor(max_workers=min(16, len(tasks))) as executor:
            return list(executor.map(scan_single_task, tasks))

    chunk_size = 4
    chunks = [tasks[i:i + chunk_size] for i in range(0, len(tasks), chunk_size)]

    def query_chunk(task_chunk: List[Dict[str, Any]]) -> Dict[str, Any]:
        parts = ["query {"]
        for t in task_chunk:
            i = t["index"]
            repo = t["repo"]
            if "/" not in repo:
                continue
            owner, name = repo.split("/", 1)
            target_b = t["target_branch"]
            selected_b = t["selected_base"]
            parts.append(f"  task_{i}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{")
            for c_idx, cand in enumerate(t["head_candidates"]):
                parts.append(
                    f"    cand_{c_idx}: ref(qualifiedName: {json.dumps('refs/heads/' + cand)}) {{ target {{ oid }} }}"
                )
            parts.append(
                f"    target_ref: ref(qualifiedName: {json.dumps('refs/heads/' + target_b)}) {{ target {{ oid }} }}"
            )
            parts.append(
                f"    base_ref: ref(qualifiedName: {json.dumps('refs/heads/' + selected_b)}) {{ target {{ oid }} }}"
            )
            parts.append("  }")
        parts.append("}")
        status, res = http_request_json(
            "https://api.github.com/graphql",
            token=token,
            data={"query": "\n".join(parts)},
            timeout=8.0,
        )
        return res.get("data", {}) if status == 200 and isinstance(res, dict) else {}

    with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as ex:
        chunk_results = list(ex.map(query_chunk, chunks))

    merged = {}
    for d in chunk_results:
        if d:
            merged.update(d)

    task_results = []
    matched_tasks = []
    for t in tasks:
        i = t["index"]
        t_data = merged.get(f"task_{i}")
        if t_data is None:
            # Repo 未在 GraphQL 成功解析，回退單任務處理
            item_res = scan_single_task(t)
            task_results.append(item_res)
            continue

        head_b = t["head_candidates"][0]
        has_a = False
        for c_idx, cand in enumerate(t["head_candidates"]):
            if t_data.get(f"cand_{c_idx}"):
                head_b = cand
                has_a = True
                break
        has_b = bool(t_data.get("target_ref"))
        base_sha = (t_data.get("base_ref") or {}).get("target", {}).get("oid", "")
        item_res = dict(t)
        item_res.update(
            {
                "head_branch": head_b,
                "has_a": has_a,
                "has_b": has_b,
                "base_sha": base_sha,
                "diff": {
                    "ahead_by": 0,
                    "commits_count": 0,
                    "files_count": 0,
                    "additions": 0,
                    "deletions": 0,
                    "commits": [],
                    "files": [],
                },
                "has_changes": False,
                "existing_pr": None,
                "selected": False,
            }
        )
        task_results.append(item_res)
        if has_a:
            matched_tasks.append(item_res)

    if matched_tasks:
        def enrich_diff(item: Dict[str, Any]) -> None:
            repo = item["repo"]
            head_branch = item["head_branch"]
            compare_target = item["target_branch"] if item["has_b"] else item["selected_base"]
            item["diff"] = fetch_compare_diff(repo, head_branch, compare_target, token=token)
            item["has_changes"] = item["diff"]["commits_count"] > 0

        def enrich_pr(item: Dict[str, Any]) -> None:
            if item["has_b"]:
                item["existing_pr"] = check_existing_pr(
                    item["repo"], item["head_branch"], item["target_branch"], token=token
                )

        with ThreadPoolExecutor(max_workers=len(matched_tasks) * 2) as ex:
            f_diffs = [ex.submit(enrich_diff, it) for it in matched_tasks]
            f_prs = [ex.submit(enrich_pr, it) for it in matched_tasks]
            for f in f_diffs + f_prs:
                try:
                    f.result()
                except Exception:
                    pass

        for it in matched_tasks:
            it["selected"] = it["has_a"] and (it["has_changes"] or it["existing_pr"] is not None)

    return task_results


def get_key() -> str:
    fd = sys.stdin.fileno()
    if not os.isatty(fd):
        return sys.stdin.read(1)
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        data = os.read(fd, 32)
        if not data:
            return ""
        if data == b"\x1b":
            r, _, _ = select.select([fd], [], [], 0.05)
            if r:
                extra = os.read(fd, 32)
                data += extra

        if data in (b"\x1b[A", b"\x1bOA"):
            return "UP"
        elif data in (b"\x1b[B", b"\x1bOB"):
            return "DOWN"
        elif data in (b"\x1b[C", b"\x1bOC"):
            return "RIGHT"
        elif data in (b"\x1b[D", b"\x1bOD"):
            return "LEFT"
        elif data.startswith(b"\x1b[") or data.startswith(b"\x1bO"):
            if data.endswith(b"A"):
                return "UP"
            elif data.endswith(b"B"):
                return "DOWN"
            elif data.endswith(b"C"):
                return "RIGHT"
            elif data.endswith(b"D"):
                return "LEFT"
            elif b"5~" in data:
                return "PAGE_UP"
            elif b"6~" in data:
                return "PAGE_DOWN"
            return "IGNORE"
        elif data == b"\x1b":
            return "ESC"
        elif data in (b"\r", b"\n"):
            return "ENTER"
        elif data == b" ":
            return "SPACE"
        elif data == b"\x03":
            return "CTRL_C"
        elif data == b"\x04":
            return "CTRL_D"
        else:
            try:
                return data.decode("utf-8")
            except Exception:
                return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def clear_screen() -> None:
    if sys.stdout.isatty():
        sys.stdout.write("\033[H\033[J")
        sys.stdout.flush()


def execute_single_task(
    item: Dict[str, Any],
    arg_title: str = "",
    arg_body: str = "",
    target_env: Optional[str] = None,
    is_draft: bool = False,
    do_auto_merge: bool = True,
    token: Optional[str] = None,
) -> List[str]:
    lines = []
    repo = item["repo"]
    selected_base = item["selected_base"]
    has_b = item["has_b"]
    diff = item["diff"]
    ex_pr = item["existing_pr"]
    head_b = item["head_branch"]
    target_b = item["target_branch"]
    disp_name = item["display_name"]
    is_static_item = item["is_static"]

    lines.append("-" * 80)
    lines.append(f"{C_BOLD}📦 [{disp_name}] ({head_b} ➔ {target_b}){C_RESET}")

    # Step A: 建立遠端目標分支 B (若不存在)
    if not has_b:
        base_sha = item.get("base_sha")
        if not base_sha:
            token = token or get_github_token()
            if token:
                st, ref_data = http_request_json(
                    f"https://api.github.com/repos/{repo}/git/ref/heads/{selected_base}",
                    token=token,
                )
                if st == 200 and isinstance(ref_data, dict):
                    base_sha = ref_data.get("object", {}).get("sha", "")
            if not base_sha:
                base_sha_res = subprocess.run(
                    ["gh", "api", f"repos/{repo}/git/ref/heads/{selected_base}", "--jq", ".object.sha"],
                    capture_output=True,
                    text=True,
                )
                base_sha = base_sha_res.stdout.strip()
        if not base_sha:
            lines.append(f"  {C_RED}❌ 錯誤：遠端不存在 Base 分支 \"{selected_base}\"，無法建立 \"{target_b}\"。跳過此項目。{C_RESET}")
            return lines

        lines.append(f"  {C_CYAN}🔨 正在基於 \"{selected_base}\" ({base_sha[:7]}) 建立遠端分支 \"{target_b}\"...{C_RESET}")
        created = False
        token = token or get_github_token()
        if token:
            st, _ = http_request_json(
                f"https://api.github.com/repos/{repo}/git/refs",
                token=token,
                data={"ref": f"refs/heads/{target_b}", "sha": base_sha},
                method="POST",
            )
            if st in (200, 201):
                created = True
        if not created:
            create_res = subprocess.run(
                ["gh", "api", f"repos/{repo}/git/refs", "-f", f"ref=refs/heads/{target_b}", "-f", f"sha={base_sha}", "--silent"]
            )
            created = (create_res.returncode == 0)

        if created:
            lines.append(f"  {C_GREEN}✔ 已成功建立遠端分支 \"{target_b}\" (based on \"{selected_base}\")！{C_RESET}")
        else:
            lines.append(f"  {C_RED}❌ 建立遠端分支 \"{target_b}\" 失敗！跳過此項目。{C_RESET}")
            return lines

    # Step B: PR 建立或偵測
    pr_url = ""
    pr_num = None

    if ex_pr:
        pr_url = ex_pr.get("url", "")
        pr_num = ex_pr.get("number", "")
        pr_title_val = ex_pr.get("title", "")
        pr_link = f"\033]8;;{pr_url}\a{pr_url}\033]8;;\a" if pr_url else pr_url
        lines.append(f"  {C_CYAN}ℹ️ 偵測到 PR 已存在：#{pr_num} ({pr_title_val}){C_RESET}")
        lines.append(f"  {C_BOLD}🔗 {pr_link}{C_RESET}")
    else:
        commits = diff.get("commits", [])
        files = diff.get("files", [])

        if arg_title:
            pr_t = arg_title
            if is_static_item and "[static]" not in pr_t.lower():
                pr_t = f"{pr_t} [static]"
        elif target_env:
            env_tag = get_env_display_label(target_env)
            static_tag = " [static]" if is_static_item else ""
            pr_t = f"[{env_tag}]{static_tag} Merge {head_b} into {target_b}"
        else:
            static_tag = " [static]" if is_static_item else ""
            pr_t = f"Merge {head_b} into {target_b}{static_tag}"

        if arg_body:
            pr_b = arg_body
        else:
            body_lines = [f"## 🔀 Merge `{head_b}` into `{target_b}`", "", "### 📜 Merged Commits:"]
            for c in commits[:20]:
                sha = c.get("sha", "")[:7]
                msg = c.get("commit", {}).get("message", "").split("\n")[0]
                body_lines.append(f"- [{sha}] {msg}")
            if len(commits) > 20:
                body_lines.append(f"- ... and {len(commits) - 20} more commits")
            pr_b = "\n".join(body_lines)

        lines.append(f"  {C_CYAN}🚀 發起 Pull Request ({len(commits)} commits, {len(files)} files)...{C_RESET}")

        created_pr = False
        token = token or get_github_token()
        if token:
            payload = {
                "title": pr_t,
                "body": pr_b,
                "head": head_b,
                "base": target_b,
                "draft": is_draft,
            }
            st, pr_data = http_request_json(
                f"https://api.github.com/repos/{repo}/pulls",
                token=token,
                data=payload,
                method="POST",
            )
            if st in (200, 201) and isinstance(pr_data, dict):
                pr_url = pr_data.get("html_url") or pr_data.get("url", "")
                pr_num = pr_data.get("number", "")
                created_pr = True

        if not created_pr:
            gh_cmd = [
                "gh",
                "pr",
                "create",
                "--repo",
                repo,
                "--head",
                head_b,
                "--base",
                target_b,
                "--title",
                pr_t,
                "--body",
                pr_b,
            ]
            if is_draft:
                gh_cmd.append("--draft")

            pr_res = subprocess.run(gh_cmd, capture_output=True, text=True)
            if pr_res.returncode == 0 and pr_res.stdout.strip():
                pr_url = pr_res.stdout.strip()
                created_pr = True
                match = re.search(r"/pull/(\d+)", pr_url)
                if match:
                    pr_num = match.group(1)
            else:
                err_msg = pr_res.stderr.strip() if pr_res.stderr else "未知錯誤"
                lines.append(f"  {C_RED}❌ PR 建立失敗: {err_msg}{C_RESET}")

        if created_pr:
            pr_link = f"\033]8;;{pr_url}\a{pr_url}\033]8;;\a" if pr_url else pr_url
            lines.append(f"  {C_GREEN}✨ PR 建立成功！{C_RESET}")
            lines.append(f"  {C_BOLD}🔗 {pr_link}{C_RESET}")

    # Step C: 自動 Merge PR (若有啟用)
    if do_auto_merge and pr_url:
        lines.append(f"  {C_CYAN}🔀 正在將 PR 合併進 {target_b}...{C_RESET}")
        merged_ok = False
        token = token or get_github_token()
        if token and pr_num:
            st, m_data = http_request_json(
                f"https://api.github.com/repos/{repo}/pulls/{pr_num}/merge",
                token=token,
                data={"merge_method": "merge"},
                method="PUT",
            )
            if st == 200 and isinstance(m_data, dict) and m_data.get("merged"):
                merged_ok = True
                lines.append(f"  {C_GREEN}✨ PR 已成功合併進 {target_b}！{C_RESET}")

        if not merged_ok:
            m_res = subprocess.run(
                ["gh", "pr", "merge", pr_url, "--repo", repo, "--merge"],
                capture_output=True,
                text=True,
            )
            if m_res.returncode == 0:
                lines.append(f"  {C_GREEN}✨ PR 已成功合併進 {target_b}！{C_RESET}")
            else:
                m_auto = subprocess.run(
                    ["gh", "pr", "merge", pr_url, "--repo", repo, "--auto", "--merge"],
                    capture_output=True,
                    text=True,
                )
                if m_auto.returncode == 0:
                    lines.append(f"  {C_GREEN}✨ PR 已設定為 Auto-Merge！{C_RESET}")
                else:
                    m_err = m_res.stderr.strip() if m_res.stderr else "無法執行 Merge"
                    lines.append(f"  {C_RED}⚠️ 自動 Merge 失敗: {m_err}{C_RESET}")

    return lines


def run_pr_scan(
    config_file: str,
    branch_a: str,
    branch_b: str,
    arg_repo: str = "",
    arg_base_of_b: str = "",
    arg_title: str = "",
    arg_body: str = "",
    is_draft: bool = False,
    auto_yes: bool = False,
    do_auto_merge: bool = True,
    arg_env: str = "",
) -> int:
    config_data = {}
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config_data = json.load(f)
    except Exception:
        pass

    # 決定目標環境 (lab / stg / prod)
    target_env = normalize_target_env(arg_env)
    if not target_env:
        target_env = normalize_target_env(branch_b)

    # 決定 Repository 掃描清單
    all_repos = []
    if arg_repo:
        all_repos = [arg_repo]
    else:
        tracked = config_data.get("tracked_repos", [])
        repos_dict = config_data.get("repos", {})
        seen = set()
        for r in tracked + list(repos_dict.keys()):
            if r and isinstance(r, str) and r not in seen:
                seen.add(r)
                all_repos.append(r)

    if not all_repos:
        print(f"{C_RED}❌ 設定檔中沒有配置任何要追蹤的 Repositories。{C_RESET}")
        return 1

    tasks = build_scan_tasks(
        all_repos=all_repos,
        config_data=config_data,
        branch_a=branch_a,
        raw_branch_b=branch_b,
        target_env=target_env,
        arg_base_of_b=arg_base_of_b,
    )

    env_banner = f" (目標環境: {C_BOLD}{get_env_display_label(target_env)}{C_RESET}{C_CYAN})" if target_env else ""
    print(
        f"{C_CYAN}🔍 正在平行掃描 {len(all_repos)} 個 Repositories ({len(tasks)} 個任務) 中的分支與變更...{env_banner} (設定檔: {config_file}){C_RESET}"
    )

    items = scan_all_tasks(tasks)

    matched_count = sum(1 for item in items if item["has_a"])
    if matched_count == 0:
        print(f"\n{C_YELLOW}⚠️ 在所有追蹤的 Repositories 中皆未找到來源分支 \"{branch_a}\"。{C_RESET}")
        print(f"{C_DIM}請確認 Branch A 名稱是否正確並已 Push 到遠端。{C_RESET}")
        return 0

    # 預設游標移動至第一個有變更或既有 PR 的任務
    cursor = 0
    for idx_i, item in enumerate(items):
        if item["has_a"] and (item["has_changes"] or item["existing_pr"]):
            cursor = idx_i
            break

    # 互動式全螢幕操作迴圈
    print("\033[?25l", end="", flush=True)
    try:
        while True:
            clear_screen()
            merge_status_label = (
                f"{C_GREEN}🟢 已開啟 (單鍵 m 切換，發起/偵測 PR 後會直接自動 Merge){C_RESET}"
                if do_auto_merge
                else f"{C_DIM}⚪ 已關閉 (單鍵 m 切換，僅發起/檢查 PR){C_RESET}"
            )
            print("=" * 80)
            target_desc = f"目標環境: {C_BOLD}{get_env_display_label(target_env)}{C_RESET}" if target_env else f"目標: {branch_b}"
            print(f" {C_BOLD}{C_CYAN}🔍 跨 Repository 掃描結果與 PR 管理 (來源: {branch_a} ➔ {target_desc}){C_RESET}")
            print(f" {C_BOLD}⚡ 自動 Merge 模式:{C_RESET} {merge_status_label}")
            print("=" * 80)

            for idx_i, item in enumerate(items):
                is_cursor = idx_i == cursor
                pointer = f"{C_CYAN}{C_BOLD}❯{C_RESET}" if is_cursor else " "
                status_check = f"{C_GREEN}[✓]{C_RESET}" if item["selected"] else f"{C_DIM}[ ]{C_RESET}"
                disp_name = item["display_name"]
                item_label = f"{C_BOLD}{C_CYAN}{disp_name}{C_RESET}" if is_cursor else f"{C_BOLD}{disp_name}{C_RESET}"
                idx_num = item["index"]
                diff = item["diff"]
                ex_pr = item["existing_pr"]
                t_branch = item["target_branch"]
                h_branch = item["head_branch"]

                action_suffix = f" {C_GREEN}➔ 將【自動 Merge】{C_RESET}" if (do_auto_merge and item["selected"]) else ""

                if not item["has_a"]:
                    cands_str = " / ".join(item["head_candidates"])
                    print(f" {pointer} {status_check} {idx_num}) {item_label} {C_RED}(遠端未找到分支: {cands_str}){C_RESET}")
                else:
                    if ex_pr:
                        pr_num = ex_pr.get("number", "")
                        pr_url = ex_pr.get("url", "")
                        pr_link = f"\033]8;;{pr_url}\a{pr_url}\033]8;;\a" if pr_url else ""
                        b_desc = f"{C_CYAN}PR 已存在 (#{pr_num}): {pr_link}{C_RESET}{action_suffix}"
                        print(f" {pointer} {status_check} {idx_num}) {item_label} {C_GREEN}(PR 已存在 #{pr_num}){C_RESET}")
                        print(f"        • 來源分支 A: {C_BOLD}{h_branch}{C_RESET} ➔ 目標分支 B: {C_BOLD}{t_branch}{C_RESET}")
                        print(f"        • 狀態: {b_desc}")
                    elif not item["has_changes"]:
                        print(
                            f" {pointer} {status_check} {idx_num}) {item_label} {C_YELLOW}(無檔案變更: 0 commits, +0/-0){C_RESET} {C_DIM}➔ 自動跳過{C_RESET}"
                        )
                        print(f"        • 來源分支 A: {h_branch} ➔ 目標分支 B: {t_branch}")
                    else:
                        c_cnt = diff["commits_count"]
                        f_cnt = diff["files_count"]
                        adds = diff["additions"]
                        dels = diff["deletions"]
                        diff_summary = f"{c_cnt} commits, {f_cnt} files (+{adds}/-{dels})"
                        if item["has_b"]:
                            b_desc = f"{C_GREEN}遠端已存在 {t_branch}{C_RESET}{action_suffix}"
                        else:
                            sel_b = item["selected_base"]
                            s_lbl = item["source_label"]
                            base_desc = f"{C_YELLOW}將自動建立並 Base 於: {sel_b}{C_RESET} {C_DIM}({s_lbl}){C_RESET}"
                            b_desc = f"{C_YELLOW}遠端尚未建立 {t_branch}{C_RESET} ➔ {base_desc}{action_suffix}"

                        print(f" {pointer} {status_check} {idx_num}) {item_label} {C_GREEN}(有檔案變更: {diff_summary}){C_RESET}")
                        print(f"        • 來源分支 A: {C_BOLD}{h_branch}{C_RESET}")
                        print(f"        • 目標分支 B: {b_desc}")

            print("=" * 80)

            selected_items = [it for it in items if it["selected"]]

            if auto_yes:
                break

            exec_action_text = f"{C_GREEN}發起/檢查 PR 並直接 Merge{C_RESET}" if do_auto_merge else "發起/檢查 PR"

            print(f"{C_BOLD}請按按鍵進行操作 (單鍵即時響應，零延遲原地刷新)：{C_RESET}")
            print(f"  • {C_CYAN}↑ / ↓{C_RESET} (或 {C_CYAN}j/k{C_RESET})       : 上下移動游標選擇 Repo / Task")
            print(f"  • {C_CYAN}← / →{C_RESET} (或 {C_CYAN}Space{C_RESET})     : 左右切換勾選 (← 取消勾選 / → 勾選 / Space 切換)")
            print(f"  • 按 {C_CYAN}a{C_RESET}                 : 全選 / 全部取消勾選")
            print(f"  • 按 {C_YELLOW}m{C_RESET}                 : 切換【自動 Merge 模式】 (零延遲原地切換)")
            print(f"  • 按 {C_YELLOW}b{C_RESET}                 : 選擇並修改目前游標 (或指定) Repo 的 Base 分支")
            print(f"  • 按 {C_CYAN}1-{len(items)}{C_RESET}               : 即時勾選 / 取消勾選指定編號")
            print(
                f"  • 按 {C_GREEN}y{C_RESET} 或 {C_GREEN}Enter{C_RESET}          : 確認執行勾選的 {len(selected_items)} 個任務 ({exec_action_text})"
            )
            print(f"  • 按 {C_RED}q{C_RESET}                 : 取消操作並退出")
            print("")
            print(f"{C_YELLOW}👉 請按下按鍵 [↑↓←→/Space/y/m/b/1-{len(items)}/q]: {C_RESET}", end="", flush=True)

            try:
                key = get_key()
            except (EOFError, KeyboardInterrupt):
                print(f"\n{C_DIM}已取消操作。{C_RESET}")
                return 0

            if key in ["UP", "k", "K"]:
                cursor = (cursor - 1) % len(items)
                continue
            elif key in ["DOWN", "j", "J"]:
                cursor = (cursor + 1) % len(items)
                continue
            elif key in ["LEFT", "h", "H"]:
                items[cursor]["selected"] = False
                continue
            elif key in ["RIGHT", "l", "L"]:
                items[cursor]["selected"] = True
                continue
            elif key == "SPACE":
                items[cursor]["selected"] = not items[cursor]["selected"]
                continue
            elif key in ["a", "A"]:
                valid_items = [it for it in items if it["has_a"]]
                new_val = not all(it["selected"] for it in valid_items) if valid_items else False
                for it in items:
                    if it["has_a"]:
                        it["selected"] = new_val
                continue
            elif key in ["y", "Y", "ENTER"]:
                break
            elif key in ["IGNORE", ""]:
                continue
            elif key in ["q", "Q", "ESC", "CTRL_C", "CTRL_D"]:
                print(f"\n{C_DIM}已取消操作。{C_RESET}")
                return 0
            elif key in ["m", "M"]:
                do_auto_merge = not do_auto_merge
                continue
            elif key in ["b", "B"]:
                print("\033[?25h", end="", flush=True)
                try:
                    default_target = cursor + 1
                    sub_input = input(
                        f"{C_YELLOW}請輸入要修改 Base 分支的項目編號 [1-{len(items)}] (預設: {default_target}): {C_RESET}"
                    ).strip()
                    target_idx = int(sub_input) if sub_input.isdigit() else default_target
                    match_item = next((it for it in items if it["index"] == target_idx), None)
                    if match_item:
                        t_branch = match_item["target_branch"]
                        if match_item["has_b"]:
                            print(
                                f"{C_YELLOW}⚠️ 注意：{match_item['display_name']} 的 Branch B ({t_branch}) 遠端已存在，無需選擇 Base。{C_RESET}"
                            )
                            input("按 Enter 繼續...")
                            continue

                        r_name = match_item["repo"]
                        curr_base = match_item["selected_base"]
                        is_static_item = match_item["is_static"]

                        print(f"\n{C_CYAN}📌 請選擇 {match_item['display_name']} 建立 {t_branch} 的 Base 分支：{C_RESET}")
                        if is_static_item:
                            base_options = ["develop_static", "develop", "main"]
                        else:
                            base_options = ["develop", "main", "develop-k8s"]

                        if curr_base not in base_options:
                            base_options.insert(0, curr_base)

                        for b_idx, b_opt in enumerate(base_options, 1):
                            mark = f"{C_GREEN}(目前選擇){C_RESET}" if b_opt == curr_base else ""
                            print(f"  {b_idx}) {b_opt} {mark}")
                        print(f"  {len(base_options)+1}) 手動輸入自訂分支名稱...")

                        b_choice = input(
                            f"{C_YELLOW}請選擇選項 [1-{len(base_options)+1}] (預設: 1): {C_RESET}"
                        ).strip()

                        new_base = ""
                        if not b_choice or b_choice == "1":
                            new_base = base_options[0]
                        elif b_choice.isdigit() and 1 <= int(b_choice) <= len(base_options):
                            new_base = base_options[int(b_choice) - 1]
                        elif b_choice.isdigit() and int(b_choice) == len(base_options) + 1:
                            custom_input = input(f"{C_YELLOW}請輸入自訂 Base 分支名稱: {C_RESET}").strip()
                            if custom_input:
                                new_base = custom_input
                        else:
                            new_base = b_choice

                        if new_base:
                            match_item["selected_base"] = new_base
                            match_item["source_label"] = "手動指定"
                            match_item["diff"] = fetch_compare_diff(r_name, match_item["head_branch"], new_base)
                            match_item["has_changes"] = match_item["diff"]["commits_count"] > 0
                            match_item["selected"] = match_item["has_changes"]

                            print(f"{C_GREEN}✔ 已將 {match_item['display_name']} 的 Base 成功更新為 \"{new_base}\"！{C_RESET}")
                            input("按 Enter 繼續...")
                    else:
                        print(f"{C_RED}❌ 找不到編號為 {target_idx} 的項目。{C_RESET}")
                        input("按 Enter 繼續...")
                except (EOFError, KeyboardInterrupt):
                    continue
                finally:
                    print("\033[?25l", end="", flush=True)

            elif key.isdigit():
                target_idx = int(key)
                if 1 <= target_idx <= len(items):
                    cursor = target_idx - 1
                    match_item = items[cursor]
                    if not match_item["has_a"]:
                        print(f"\n{C_YELLOW}⚠️ 注意：{match_item['display_name']} 遠端未找到 Branch A。{C_RESET}")
                    elif not match_item["has_changes"] and not match_item["existing_pr"]:
                        print(f"\n{C_YELLOW}⚠️ 注意：{match_item['display_name']} 沒有檔案變更 (0 commits)。{C_RESET}")

                    match_item["selected"] = not match_item["selected"]
    finally:
        print("\033[?25h", end="", flush=True)

    if not selected_items:
        print(f"{C_YELLOW}沒有勾選任何要執行的項目，已結束。{C_RESET}")
        return 0

    # 執行並行建立分支、PR 與 Merge
    print(f"\n{C_CYAN}🚀 開始並行執行 {len(selected_items)} 個任務的 Branch B 建立、PR 發起與 Merge...{C_RESET}\n")

    token = get_github_token()
    with ThreadPoolExecutor(max_workers=min(8, len(selected_items))) as executor:
        futures = [
            executor.submit(
                execute_single_task,
                item=item,
                arg_title=arg_title,
                arg_body=arg_body,
                target_env=target_env,
                is_draft=is_draft,
                do_auto_merge=do_auto_merge,
                token=token,
            )
            for item in selected_items
        ]
        for future in as_completed(futures):
            task_lines = future.result()
            if task_lines:
                print("\n".join(task_lines))

    print("")
    print("=" * 80)
    print(f" {C_GREEN}✨ 所有選取項目的 PR 與 Merge 作業已執行完成！{C_RESET}")
    print("=" * 80)
    return 0


def main() -> int:
    if len(sys.argv) < 4:
        print("Usage: pr_scan.py <config_file> <branch_a> <branch_b> [arg_repo] [arg_base] [title] [body] [draft] [auto_yes] [auto_merge] [arg_env]")
        return 1

    config_file = sys.argv[1]
    branch_a = sys.argv[2]
    branch_b = sys.argv[3]
    arg_repo = sys.argv[4] if len(sys.argv) > 4 else ""
    arg_base_of_b = sys.argv[5] if len(sys.argv) > 5 else ""
    arg_title = sys.argv[6] if len(sys.argv) > 6 else ""
    arg_body = sys.argv[7] if len(sys.argv) > 7 else ""
    is_draft = (sys.argv[8] == "true") if len(sys.argv) > 8 else False
    auto_yes = (sys.argv[9] == "true") if len(sys.argv) > 9 else False
    do_auto_merge = (sys.argv[10] == "true") if len(sys.argv) > 10 else True
    arg_env = sys.argv[11] if len(sys.argv) > 11 else ""

    return run_pr_scan(
        config_file=config_file,
        branch_a=branch_a,
        branch_b=branch_b,
        arg_repo=arg_repo,
        arg_base_of_b=arg_base_of_b,
        arg_title=arg_title,
        arg_body=arg_body,
        is_draft=is_draft,
        auto_yes=auto_yes,
        do_auto_merge=do_auto_merge,
        arg_env=arg_env,
    )


if __name__ == "__main__":
    sys.exit(main())
