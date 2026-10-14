"""Query Jira release tickets via local Jira MCP or direct REST API."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unicodedata
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


DEFAULT_FILTER_ID = "42752"
DEFAULT_JIRA_URL = "https://104corp.atlassian.net"
DEFAULT_MCP_URL = "http://127.0.0.1:10001/mcp"

# ANSI Colors
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_DIM = "\033[2m"
COLOR_GREEN = "\033[32m"
COLOR_YELLOW = "\033[33m"
COLOR_BLUE = "\033[34m"
COLOR_MAGENTA = "\033[35m"
COLOR_CYAN = "\033[36m"
COLOR_RED = "\033[31m"
COLOR_GRAY = "\033[90m"


def is_tty() -> bool:
    return sys.stdout.isatty()


def c(text: str, color_code: str) -> str:
    if not is_tty() or not color_code:
        return text
    return f"{color_code}{text}{COLOR_RESET}"


def display_width(s: str) -> int:
    """Calculate terminal display width taking CJK characters into account."""
    if not s:
        return 0
    w = 0
    for ch in str(s):
        status = unicodedata.east_asian_width(ch)
        if status in ("F", "W"):
            w += 2
        else:
            w += 1
    return w


def pad_right(s: str, target_width: int) -> str:
    s_str = str(s or "")
    current_width = display_width(s_str)
    if current_width >= target_width:
        return s_str
    return s_str + " " * (target_width - current_width)


def get_status_color(status_name: str) -> str:
    s = status_name.lower()
    if any(k in s for k in ("結案", "done", "closed", "resolved")):
        return COLOR_GRAY
    if any(k in s for k in ("取消", "cancel", "rejected", "won't do")):
        return COLOR_RED
    if any(k in s for k in ("線上", "production", "prod")):
        return COLOR_GREEN
    if any(k in s for k in ("staging", "stg", "測試", "test", "qa")):
        return COLOR_YELLOW
    if any(k in s for k in ("作業中", "進行中", "in progress")):
        return COLOR_CYAN
    return COLOR_BLUE


def load_jira_env(project_root: Optional[Path] = None) -> Dict[str, str]:
    env_vars: Dict[str, str] = {}
    candidates = []
    if project_root:
        candidates.append(project_root / "jira.env")
    candidates.extend([
        Path.home() / ".config" / "favorite-bash" / "jira.env",
        Path("/Volumes/workspace/favorite-bash/jira.env"),
    ])

    for p in candidates:
        if p.is_file():
            try:
                with p.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            env_vars[k.strip()] = v.strip().strip("\"'")
                break
            except Exception:
                pass

    # Process env override
    for key in ("JIRA_URL", "JIRA_USERNAME", "JIRA_API_TOKEN"):
        if key in os.environ and os.environ[key]:
            env_vars[key] = os.environ[key]

    return env_vars


def query_via_mcp(jql: str, limit: int = 50, mcp_url: str = DEFAULT_MCP_URL) -> Tuple[bool, Any]:
    """Query Jira search using the local FastMCP streamable-http endpoint."""
    try:
        # Step 1: Initialize
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "jira-releases-cli", "version": "1.0"}
            }
        }
        req = Request(mcp_url, data=json.dumps(init_payload).encode("utf-8"), headers=headers)
        with urlopen(req, timeout=4) as resp:
            session_id = resp.headers.get("mcp-session-id")

        if not session_id:
            return False, "Failed to obtain MCP session ID"

        # Step 2: Send initialized notification
        init_notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        notif_headers = {"Content-Type": "application/json", "mcp-session-id": session_id}
        req_notif = Request(mcp_url, data=json.dumps(init_notif).encode("utf-8"), headers=notif_headers)
        try:
            with urlopen(req_notif, timeout=3):
                pass
        except Exception:
            pass

        # Step 3: Call jira_search
        call_payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "jira_search",
                "arguments": {
                    "jql": jql,
                    "limit": limit
                }
            }
        }
        call_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "mcp-session-id": session_id
        }
        req_call = Request(mcp_url, data=json.dumps(call_payload).encode("utf-8"), headers=call_headers)
        with urlopen(req_call, timeout=10) as resp:
            raw_text = resp.read().decode("utf-8")
            data = None
            for line in raw_text.splitlines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    break

            if not data or "result" not in data:
                return False, "Invalid response from Jira MCP"

            result = data["result"]
            if result.get("isError"):
                content = result.get("content", [{}])[0].get("text", "Unknown MCP error")
                return False, content

            content_text = result.get("content", [{}])[0].get("text", "{}")
            parsed = json.loads(content_text)
            return True, parsed

    except (URLError, TimeoutError, ConnectionRefusedError, OSError) as e:
        return False, f"MCP connection error: {e}"
    except Exception as e:
        return False, f"MCP query error: {e}"


def query_via_api(jql: str, limit: int = 50, project_root: Optional[Path] = None) -> Tuple[bool, Any]:
    """Fallback: query Jira Cloud enhanced_jql directly using REST API."""
    env = load_jira_env(project_root)
    jira_url = env.get("JIRA_URL", DEFAULT_JIRA_URL).rstrip("/")
    username = env.get("JIRA_USERNAME")
    token = env.get("JIRA_API_TOKEN")

    if not username or not token:
        return False, "Missing JIRA_USERNAME or JIRA_API_TOKEN in environment or jira.env"

    auth_str = base64.b64encode(f"{username}:{token}".encode("utf-8")).decode("utf-8")
    query_params = urlencode({
        "jql": jql,
        "maxResults": limit,
        "fields": "summary,status,assignee,updated,created"
    })
    api_url = f"{jira_url}/rest/api/3/search/jql?{query_params}"

    headers = {
        "Authorization": f"Basic {auth_str}",
        "Accept": "application/json"
    }

    try:
        req = Request(api_url, headers=headers)
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            # Standardize issue format to match mcp-atlassian output
            standardized_issues = []
            for item in data.get("issues", []):
                fields = item.get("fields", {})
                status_obj = fields.get("status", {})
                assignee_obj = fields.get("assignee")
                standardized_issues.append({
                    "id": item.get("id"),
                    "key": item.get("key"),
                    "summary": fields.get("summary", ""),
                    "status": {
                        "name": status_obj.get("name", "Unknown"),
                        "category": status_obj.get("statusCategory", {}).get("name", "")
                    },
                    "assignee": {
                        "display_name": assignee_obj.get("displayName", "未指派") if assignee_obj else "未指派"
                    } if assignee_obj else None,
                    "updated": fields.get("updated", ""),
                    "created": fields.get("created", "")
                })
            return True, {"issues": standardized_issues, "total": data.get("total", len(standardized_issues))}
    except HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            return False, f"Jira API HTTP {e.code}: {err_body}"
        except Exception:
            return False, f"Jira API HTTP {e.code}: {e.reason}"
    except Exception as e:
        return False, f"Jira API error: {e}"


def format_date(raw_date: str) -> str:
    """Format ISO 8601 string to short MM/DD HH:MM."""
    if not raw_date or len(raw_date) < 16:
        return raw_date or ""
    try:
        # e.g. 2026-10-08T15:31:06.726+0800 -> 10/08 15:31
        date_part = raw_date[5:10].replace("-", "/")
        time_part = raw_date[11:16]
        return f"{date_part} {time_part}"
    except Exception:
        return raw_date[:10]


def main(project_root: Optional[Path] = None, argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jira-releases",
        description="查詢 104 Jira 上線單列表 (支援本地 Jira MCP 及 Direct REST API 自動容錯)"
    )
    parser.add_argument(
        "search",
        nargs="?",
        default=None,
        help="依關鍵字、單號或日期過濾 (例如: 30930, 獵派, 10/27)"
    )
    parser.add_argument(
        "-f", "--filter",
        default=DEFAULT_FILTER_ID,
        help=f"指定 Jira Filter ID (預設: {DEFAULT_FILTER_ID})"
    )
    parser.add_argument(
        "-q", "--jql",
        default=None,
        help="自訂 JQL 查詢語法 (指定此選項時將忽略 --filter)"
    )
    parser.add_argument(
        "-s", "--status",
        default=None,
        help="依狀態關鍵字過濾 (例如: staging, 線上, 測試)"
    )
    parser.add_argument(
        "-a", "--all",
        action="store_true",
        help="顯示所有單號 (預設僅篩選未結案 / 進行中單號，若結果不足時會自動放寬)"
    )
    parser.add_argument(
        "-n", "--limit",
        type=int,
        default=50,
        help="最多取得筆數 (預設: 50)"
    )
    parser.add_argument(
        "-o", "--open",
        action="store_true",
        help="在預設瀏覽器中開啟該 Filter 或指定單號的 Jira 網頁"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="輸出原始 JSON 格式"
    )
    parser.add_argument(
        "--api",
        action="store_true",
        help="強制使用 Jira REST API (跳過本機 MCP)"
    )
    parser.add_argument(
        "--mcp-url",
        default=DEFAULT_MCP_URL,
        help=f"自訂 MCP Server URL (預設: {DEFAULT_MCP_URL})"
    )

    args = parser.parse_args(argv)

    # Handle --open early if requested for a specific single ticket
    if args.open:
        target_url = f"{DEFAULT_JIRA_URL}/issues?filter={args.filter}"
        if args.search and args.search.upper().startswith("PMOJBVIP-"):
            target_url = f"{DEFAULT_JIRA_URL}/browse/{args.search.upper()}"
        print(f"🌐 正在瀏覽器中開啟: {target_url}")
        subprocess.run(["open", target_url])
        return 0

    # Build JQL
    if args.jql:
        jql = args.jql
    else:
        jql = f"filter = {args.filter}"

    # Query backend: MCP first, then fallback to API
    backend_used = "Jira MCP"
    data = None

    if not args.api:
        success, res = query_via_mcp(jql, limit=args.limit, mcp_url=args.mcp_url)
        if success:
            data = res
        else:
            # Fallback to direct API
            api_ok, api_res = query_via_api(jql, limit=args.limit, project_root=project_root)
            if api_ok:
                backend_used = "Jira REST API (MCP 離線自動切換)"
                data = api_res
            else:
                print(c(f"❌ 查詢失敗: MCP 失敗 ({res})，REST API 亦失敗 ({api_res})", COLOR_RED), file=sys.stderr)
                return 1
    else:
        backend_used = "Jira REST API"
        api_ok, api_res = query_via_api(jql, limit=args.limit, project_root=project_root)
        if api_ok:
            data = api_res
        else:
            print(c(f"❌ Jira REST API 查詢失敗: {api_res}", COLOR_RED), file=sys.stderr)
            return 1

    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    issues: List[Dict[str, Any]] = data.get("issues", [])
    if not issues:
        print(c(f"ℹ️ 查無任何單號 (JQL: {jql})", COLOR_YELLOW))
        return 0

    # Filter by keyword if provided
    if args.search:
        term = args.search.lower()
        issues = [
            it for it in issues
            if term in it.get("key", "").lower()
            or term in it.get("summary", "").lower()
            or term in (it.get("assignee") or {}).get("display_name", "").lower()
        ]

    # Filter by status if provided
    if args.status:
        st_term = args.status.lower()
        issues = [
            it for it in issues
            if st_term in (it.get("status") or {}).get("name", "").lower()
        ]

    # Partition active vs closed
    active_issues = []
    closed_issues = []
    for it in issues:
        st_name = (it.get("status") or {}).get("name", "")
        if any(k in st_name.lower() for k in ("結案", "done", "closed", "取消", "cancel")):
            closed_issues.append(it)
        else:
            active_issues.append(it)

    # If --all wasn't set, display active issues. If none active, show all so user isn't left empty.
    if args.all or not active_issues:
        display_list = issues
    else:
        display_list = active_issues

    # Terminal output header
    term_width = shutil.get_terminal_size((100, 24)).columns
    filter_url = f"{DEFAULT_JIRA_URL}/issues?filter={args.filter}" if not args.jql else DEFAULT_JIRA_URL

    print()
    print(c(f"🚀 Jira 上線單查詢結果 ({backend_used})", COLOR_BOLD + COLOR_CYAN))
    print(c(f"🔗 網址: {filter_url}", COLOR_DIM))
    print(c(f"📊 統計: 總計 {len(issues)} 筆 (進行中: {len(active_issues)} 筆, 結案/取消: {len(closed_issues)} 筆)", COLOR_DIM))
    if not args.all and len(closed_issues) > 0 and active_issues:
        print(c(f"💡 目前僅列出進行中 {len(active_issues)} 筆 (使用 -a 或 --all 檢視全部)", COLOR_DIM + COLOR_YELLOW))
    print("─" * min(term_width, 100))

    # Column widths
    key_w = 16
    status_w = 16
    assignee_w = 18
    updated_w = 12

    for it in display_list:
        key = it.get("key", "")
        summary = it.get("summary", "").strip()
        status_name = (it.get("status") or {}).get("name", "Unknown")
        assignee_name = (it.get("assignee") or {}).get("display_name", "未指派")
        updated_str = format_date(it.get("updated", ""))

        st_color = get_status_color(status_name)
        key_colored = c(pad_right(key, key_w), COLOR_BOLD + COLOR_BLUE)
        status_colored = c(pad_right(f"[{status_name}]", status_w), st_color)
        assignee_colored = c(pad_right(assignee_name, assignee_w), COLOR_GRAY)
        updated_colored = c(pad_right(updated_str, updated_w), COLOR_DIM)

        print(f" {key_colored} {status_colored} {assignee_colored} {updated_colored} {summary}")

    print("─" * min(term_width, 100))
    print()
    return 0
