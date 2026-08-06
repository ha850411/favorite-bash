#!/usr/bin/env python3
# ==============================================================================
# Favorite Bash - Autocomplete Helper for pr-scan
# 高效檢索追蹤的 Repos 分支與單號比對，支援 Branch A/B 雙向前綴匹配與動態過濾 (每 Repo 最多 3 個)
# ==============================================================================

import sys
import os
import json
import re
import time
import subprocess

def get_cache_path():
    cache_dir = os.path.expanduser("~/.cache/favorite-bash")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "branches_cache.json")

def load_config(config_path):
    if not config_path or not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def extract_keywords(branch_str):
    if not branch_str:
        return [], ""
    
    keywords = [branch_str]
    ticket_match = re.search(r'([A-Za-z]+[-_]\d+)', branch_str)
    ticket_id = ticket_match.group(1) if ticket_match else ""
    
    if ticket_id:
        keywords.append(ticket_id.upper())
        keywords.append(ticket_id.lower())
    
    parts = branch_str.split('/')
    if len(parts) > 1 and parts[-1]:
        keywords.append(parts[-1])
        
    return list(dict.fromkeys(keywords)), ticket_id

def get_local_git_branches():
    try:
        res = subprocess.run(
            ["git", "branch", "-a", "--format=%(refname:short)"],
            capture_output=True, text=True, timeout=0.8
        )
        if res.returncode == 0:
            branches = []
            for b in res.stdout.splitlines():
                b = b.strip()
                if b.startswith("origin/"):
                    b = b[7:]
                if b and b not in branches and b != "HEAD":
                    branches.append(b)
            return branches
    except Exception:
        pass
    return []

def get_cached_remote_branches(tracked_repos, config_path):
    cache_path = get_cache_path()
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("repos", {})
        except Exception:
            pass

    # Non-blocking background fetch if missing
    try:
        bg_cmd = f"python3 -c \"import json, time, subprocess, sys, os; repos={tracked_repos}; cache_data={{}}; [cache_data.update({{r: subprocess.run(['gh', 'api', f'repos/{{r}}/branches?per_page=100', '--jq', '.[].name'], capture_output=True, text=True, timeout=3).stdout.splitlines()}}) for r in repos]; open('{cache_path}', 'w').write(json.dumps({{'timestamp': time.time(), 'repos': cache_data}}))\" &"
        os.system(bg_cmd)
    except Exception:
        pass

    return {}

def main():
    if len(sys.argv) < 2:
        sys.exit(0)

    mode = sys.argv[1] # 'branch_a' or 'branch_b'
    input_a = sys.argv[2] if len(sys.argv) > 2 else ""
    config_path = sys.argv[3] if len(sys.argv) > 3 else ""
    input_b = sys.argv[4] if len(sys.argv) > 4 else ""

    config = load_config(config_path)
    tracked_repos = config.get("tracked_repos", [])
    repos_dict = config.get("repos", {})
    all_tracked = list(dict.fromkeys(tracked_repos + list(repos_dict.keys())))

    local_branches = get_local_git_branches()
    keywords_a, ticket_id_a = extract_keywords(input_a)
    keywords_b, ticket_id_b = extract_keywords(input_b)
    remote_branches_map = get_cached_remote_branches(all_tracked, config_path)

    MAX_PER_REPO = 3 # 每個 Repo 最多比對 3 個分支

    if mode == "branch_a":
        candidates = []
        seen = set()

        for b in local_branches:
            if not input_a or any(kw.lower() in b.lower() for kw in keywords_a if kw):
                if b not in seen:
                    seen.add(b)
                    candidates.append(f"{b}:本地 Git 分支")

        for repo in all_tracked:
            repo_branches = remote_branches_map.get(repo, [])
            repo_short = repo.split("/")[-1] if "/" in repo else repo
            count = 0
            for b in repo_branches:
                if not input_a or any(kw.lower() in b.lower() for kw in keywords_a if kw):
                    if b not in seen:
                        seen.add(b)
                        candidates.append(f"{b}:{repo_short} (遠端來源分支)")
                        count += 1
                        if count >= MAX_PER_REPO:
                            break

        for line in candidates[:40]:
            print(line)
        sys.exit(0)

    # Mode 'branch_b'
    candidates_by_repo = {}

    for repo in all_tracked:
        repo_branches = remote_branches_map.get(repo, [])
        matched_for_repo = []

        # 1. Match by exact Branch B input string (e.g. release/SERVICE-0 or release/SERVICE-08)
        if input_b and repo_branches:
            input_b_lower = input_b.lower()
            # Prefix matches first (e.g., release/SERVICE-0728 starts with release/SERVICE-0)
            prefix_matches = [b for b in repo_branches if b.lower().startswith(input_b_lower)]
            prefix_matches.sort(reverse=True)
            for b in prefix_matches:
                if not any(item[0] == b for item in matched_for_repo):
                    matched_for_repo.append((b, f"前綴完全符合"))
                if len(matched_for_repo) >= MAX_PER_REPO:
                    break

            # Substring matches second
            if len(matched_for_repo) < MAX_PER_REPO:
                sub_matches = [b for b in repo_branches if input_b_lower in b.lower()]
                sub_matches.sort(reverse=True)
                for b in sub_matches:
                    if not any(item[0] == b for item in matched_for_repo):
                        matched_for_repo.append((b, f"名稱匹配"))
                    if len(matched_for_repo) >= MAX_PER_REPO:
                        break

        # 2. Match by Branch A ticket ID (e.g. SERU-12705)
        if len(matched_for_repo) < MAX_PER_REPO and ticket_id_a and repo_branches:
            for b in repo_branches:
                if ticket_id_a.lower() in b.lower():
                    if not any(item[0] == b for item in matched_for_repo):
                        matched_for_repo.append((b, f"單號相符 ({ticket_id_a})"))
                if len(matched_for_repo) >= MAX_PER_REPO:
                    break

        # 3. Match in local branches if needed
        if len(matched_for_repo) < MAX_PER_REPO and input_b:
            input_b_lower = input_b.lower()
            for b in local_branches:
                if input_b_lower in b.lower():
                    if not any(item[0] == b for item in matched_for_repo):
                        matched_for_repo.append((b, f"本地分支匹配"))
                if len(matched_for_repo) >= MAX_PER_REPO:
                    break

        # 4. Fallback: Take release branches (sorted newest first) or default_base
        if len(matched_for_repo) < MAX_PER_REPO:
            repo_cfg = repos_dict.get(repo, {})
            default_base = repo_cfg.get("default_base", config.get("default_target_base", "develop"))
            
            all_candidates = repo_branches or local_branches
            release_branches = [b for b in all_candidates if b.startswith("release/")]
            release_branches.sort(reverse=True)

            for b in release_branches:
                if not any(item[0] == b for item in matched_for_repo):
                    matched_for_repo.append((b, f"近期的 Release 分支"))
                if len(matched_for_repo) >= MAX_PER_REPO:
                    break

            if len(matched_for_repo) < MAX_PER_REPO:
                if not any(item[0] == default_base for item in matched_for_repo):
                    matched_for_repo.append((default_base, f"預設 Base 分支"))

        candidates_by_repo[repo] = matched_for_repo[:MAX_PER_REPO]

    seen = set()
    for repo, matches in candidates_by_repo.items():
        repo_short = repo.split("/")[-1] if "/" in repo else repo
        for branch, reason in matches:
            if branch == input_a:
                continue
            item_str = f"{branch}:{repo_short} ({reason})"
            if item_str not in seen:
                seen.add(item_str)
                print(item_str)

if __name__ == "__main__":
    main()
