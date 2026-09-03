"""Complete unread 104 bulletin quizzes using the bulletin's public web flow."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.request import Request, urlopen



DEFAULT_SEARCH_URL = (
    "https://bulletin-104.s3-ap-northeast-1.amazonaws.com/search.html"
)
DEFAULT_SHORT_LINK_BASE = "https://o.104.tw"
DEFAULT_LAUNCHD_LABEL = "com.favorite-bash.bulletin-quiz"
LEGACY_LAUNCHD_LABEL = "com.eason.bulletin-quiz"
DEFAULT_LOG_PATH = Path.home() / "Library" / "Logs" / "bulletin-quiz.log"

API_URL_PATTERN = re.compile(r"\bapiUrl\s*=\s*['\"]([^'\"]+)['\"]")


class BulletinError(RuntimeError):
    """A user-facing bulletin workflow error."""


@dataclass(frozen=True)
class Config:
    employee_id: str
    search_url: str = DEFAULT_SEARCH_URL
    short_link_base: str = DEFAULT_SHORT_LINK_BASE
    api_url: Optional[str] = None


@dataclass(frozen=True)
class Event:
    key: str
    start_date: str
    title: str
    article_url: str

    @property
    def slug(self) -> str:
        path = urlsplit(self.article_url.strip()).path
        filename = Path(path).name
        return filename[:-5] if filename.lower().endswith(".aspx") else filename


def validate_employee_id(employee_id: Any) -> str:
    clean_id = str(employee_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]+", clean_id):
        raise BulletinError("員工編號必須是非空白英數字")
    return clean_id


def load_config(path: Optional[Path] = None, employee_id: str = "") -> Config:
    valid_id = validate_employee_id(employee_id)
    search_url = DEFAULT_SEARCH_URL
    short_link_base = DEFAULT_SHORT_LINK_BASE
    api_url = None

    if path is not None and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BulletinError(f"無法讀取設定檔 {path}：{exc}") from exc

        if not isinstance(payload, dict):
            raise BulletinError(f"設定檔 {path} 必須是 JSON object")

        if "search_url" in payload and payload["search_url"]:
            search_url = str(payload["search_url"]).strip()
        if "short_link_base" in payload and payload["short_link_base"]:
            short_link_base = str(payload["short_link_base"]).strip()
        raw_api_url = payload.get("api_url")
        api_url = str(raw_api_url).strip().rstrip("/") if raw_api_url else None
    elif path is not None and not path.is_file():
        raise BulletinError(f"找不到設定檔：{path}")

    for name, value in (
        ("search_url", search_url),
        ("short_link_base", short_link_base),
    ):
        if urlsplit(value).scheme != "https" or not urlsplit(value).netloc:
            raise BulletinError(f"{name} 必須是有效的 https URL")
    if api_url and (urlsplit(api_url).scheme != "https" or not urlsplit(api_url).netloc):
        raise BulletinError("api_url 必須是有效的 https URL")

    return Config(valid_id, search_url, short_link_base.rstrip("/"), api_url)


def find_config_path(
    project_root: Path,
    explicit: Optional[str],
    environ: Mapping[str, str],
) -> Optional[Path]:
    if explicit:
        return Path(explicit).expanduser().resolve()
    if environ.get("FAVORITE_BASH_BULLETIN_CONFIG"):
        return Path(environ["FAVORITE_BASH_BULLETIN_CONFIG"]).expanduser().resolve()

    user_config = Path.home() / ".config" / "favorite-bash" / "bulletin-quiz.json"
    if user_config.is_file():
        return user_config
    project_config = project_root / "bulletin-quiz.json"
    if project_config.is_file():
        return project_config
    return None


class HttpClient:
    """Small stdlib-only HTTP client that consistently carries the employee cookie."""

    def __init__(self, employee_id: str, timeout: float = 20.0, retries: int = 2):
        self.employee_id = employee_id
        self.timeout = timeout
        self.retries = retries

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        json_body: Optional[Mapping[str, str]] = None,
    ) -> tuple[bytes, str]:
        data = None
        headers = {
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
            "Cookie": f"id={self.employee_id}",
            "User-Agent": "favorite-bash-bulletin-quiz/1.0",
        }
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        request = Request(url, data=data, headers=headers, method=method)
        for attempt in range(self.retries + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return response.read(), response.geturl()
            except HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                try:
                    detail = exc.read().decode("utf-8", errors="replace").strip()
                except OSError:
                    detail = ""
                suffix = f"：{detail}" if detail else ""
                raise BulletinError(f"HTTP {exc.code} {url}{suffix}") from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise BulletinError(f"無法連線到 {url}：{exc}") from exc

        raise BulletinError(f"無法連線到 {url}")

    def text(self, url: str) -> tuple[str, str]:
        body, final_url = self.request(url)
        return body.decode("utf-8", errors="replace"), final_url

    def json(
        self,
        url: str,
        *,
        method: str = "GET",
        json_body: Optional[Mapping[str, str]] = None,
    ) -> tuple[dict[str, Any], str]:
        body, final_url = self.request(url, method=method, json_body=json_body)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BulletinError(f"{url} 回傳的不是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise BulletinError(f"{url} 回傳的 JSON 格式不符預期")
        return payload, final_url


class BulletinService:
    def __init__(self, config: Config, client: HttpClient):
        self.config = config
        self.client = client
        self._api_url = config.api_url

    @property
    def api_url(self) -> str:
        if self._api_url:
            return self._api_url

        html, _ = self.client.text(self.config.search_url)
        match = API_URL_PATTERN.search(html)
        if not match:
            raise BulletinError("查詢頁中找不到 apiUrl，頁面結構可能已更新")
        self._api_url = match.group(1).rstrip("/")
        return self._api_url

    def query_records(self) -> tuple[list[Event], set[str]]:
        endpoint = f"{self.api_url}/bulletin/check?{urlencode({'ID': self.config.employee_id})}"
        payload, _ = self.client.json(endpoint)
        raw_events = payload.get("event") or []
        raw_records = payload.get("record") or []
        if not isinstance(raw_events, list) or not isinstance(raw_records, list):
            raise BulletinError("點閱紀錄 API 格式不符預期")

        events: list[Event] = []
        for item in raw_events:
            if not isinstance(item, dict):
                continue
            key = str(item.get("KeyName") or "").strip()
            article_url = str(item.get("RU") or "").strip()
            if not key or not article_url:
                continue
            events.append(
                Event(
                    key=key,
                    start_date=str(item.get("ST") or "").strip(),
                    title=str(item.get("TX") or "").strip(),
                    article_url=article_url,
                )
            )

        completed = {
            str(item.get("EventID")).strip()
            for item in raw_records
            if isinstance(item, dict) and item.get("EventID")
        }
        events.sort(key=lambda event: event.start_date, reverse=True)
        return events, completed

    def form_url(self, event: Event) -> str:
        if not event.slug:
            raise BulletinError(f"公告 {event.key} 無法從文章連結推導表單短網址")
        return f"{self.config.short_link_base}/{quote(event.slug)}"

    def resolve_ad(self, event: Event) -> str:
        """Resolve the shared article/form slug; use the record's key as a safe fallback."""
        try:
            _, final_url = self.client.text(self.form_url(event))
        except BulletinError:
            return event.key
        values = parse_qs(urlsplit(final_url).query).get("ad") or []
        return values[0] if values and values[0] else event.key

    def load_form(self, event: Event) -> tuple[str, dict[str, Any]]:
        # event.key matches the form 'ad' GUID; try it first to avoid 1-1.5s redirect latency.
        if event.key:
            try:
                query = urlencode({"ad": event.key, "id": self.config.employee_id})
                payload, _ = self.client.json(f"{self.api_url}/bulletin/add?{query}")
                return event.key, payload
            except BulletinError:
                pass

        ad = self.resolve_ad(event)
        query = urlencode({"ad": ad, "id": self.config.employee_id})
        payload, _ = self.client.json(f"{self.api_url}/bulletin/add?{query}")
        return ad, payload

    def submit(self, ad: str) -> None:
        self.client.json(
            f"{self.api_url}/bulletin/add",
            method="POST",
            json_body={"EVENT_ID": ad, "ID": self.config.employee_id},
        )

    def wait_until_all_completed(
        self,
        event_ids: set[str],
        *,
        attempts: int = 4,
        delay: float = 0.5,
    ) -> set[str]:
        """Allow for a short backend propagation delay after registration, returning confirmed IDs."""
        if not event_ids:
            return set()
        for attempt in range(attempts):
            _, completed = self.query_records()
            confirmed = event_ids & completed
            if confirmed == event_ids:
                return confirmed
            if attempt + 1 < attempts:
                time.sleep(delay * (attempt + 1))
        return event_ids & completed

    def wait_until_completed(
        self,
        event_ids: set[str],
        *,
        attempts: int = 4,
        delay: float = 0.5,
    ) -> bool:
        """Allow for a short backend propagation delay after registration."""
        confirmed = self.wait_until_all_completed(
            event_ids, attempts=attempts, delay=delay
        )
        return bool(event_ids & confirmed)


def event_has_ended(payload: Mapping[str, Any], today: Optional[date] = None) -> bool:
    end_date = str(payload.get("ET") or "").strip()
    if not end_date:
        return False
    try:
        parsed = datetime.strptime(end_date, "%Y/%m/%d").date()
    except ValueError:
        return False
    return parsed < (today or date.today())


def question_details(payload: Mapping[str, Any]) -> tuple[str, str]:
    """Return the question and its correct choice, matching the page's value=1 option."""
    question = payload.get("Q")
    if question is None:
        return "", ""
    if not isinstance(question, dict):
        raise BulletinError("題目格式不符預期")
    text = str(question.get("Text") or "").strip()
    answer = str(question.get("Answer") or "").strip()
    if not answer:
        raise BulletinError("題目沒有提供可辨識的正確選項")
    return text, answer


def select_events(
    events: Sequence[Event], completed: set[str], slug: Optional[str]
) -> list[Event]:
    pending = [event for event in events if event.key not in completed]
    if slug:
        pending = [event for event in pending if event.slug == slug]
    return pending


def parse_schedule_time(time_str: str) -> tuple[int, int]:
    match = re.fullmatch(r"^([01]?\d|2[0-3]):([0-5]\d)$", time_str.strip())
    if not match:
        raise BulletinError(f"排程時間格式錯誤：{time_str}，請使用 HH:MM 格式（例如 10:00）")
    return int(match.group(1)), int(match.group(2))


def get_launchd_path_env(runtime_env: Mapping[str, str]) -> str:
    base_dirs = [
        str(Path.home() / ".local" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    seen = set()
    ordered = []
    env_path = runtime_env.get("PATH", "")
    candidates = base_dirs + [p for p in env_path.split(os.pathsep) if p]
    for p in candidates:
        if p and p not in seen:
            seen.add(p)
            ordered.append(p)
    return os.pathsep.join(ordered)


def resolve_cli_path(project_root: Path) -> Path:
    found = shutil.which("bulletin-quiz")
    if found:
        return Path(found).resolve()
    local_bin = Path.home() / ".local" / "bin" / "bulletin-quiz"
    if local_bin.exists():
        return local_bin.resolve()
    project_bin = project_root / "bin" / "bulletin-quiz"
    if project_bin.exists():
        return project_bin.resolve()
    return Path(sys.argv[0]).resolve()


def build_launchd_plist_dict(
    label: str,
    cli_path: Path,
    employee_id: str,
    hour: int,
    minute: int,
    log_path: Path,
    path_env: str,
    config_path: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    cmd_parts = [
        'echo "=== $(date \'+%Y-%m-%d %H:%M:%S\') ==="',
        f"{cli_path} {employee_id}",
    ]
    if config_path:
        cmd_parts[1] += f" --config {Path(config_path).resolve()}"
    if dry_run:
        cmd_parts[1] += " -d"
    shell_command = f"{cmd_parts[0]} && {cmd_parts[1]}"

    return {
        "Label": label,
        "ProgramArguments": [
            "/bin/zsh",
            "-c",
            shell_command,
        ],
        "EnvironmentVariables": {
            "PATH": path_env,
        },
        "StartCalendarInterval": {
            "Hour": hour,
            "Minute": minute,
        },
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
    }


def handle_schedule(
    action: str,
    *,
    employee_id: Optional[str] = None,
    schedule_time: str = "10:00",
    config_path: Optional[str] = None,
    dry_run: bool = False,
    project_root: Optional[Path] = None,
    environ: Optional[Mapping[str, str]] = None,
    agents_dir: Optional[Path] = None,
    log_file: Optional[Path] = None,
    label: str = DEFAULT_LAUNCHD_LABEL,
    system_platform: Optional[str] = None,
) -> int:
    platform_name = system_platform if system_platform is not None else sys.platform
    if platform_name != "darwin":
        print("錯誤：排程功能目前僅支援 macOS (launchd)。", file=sys.stderr)
        return 2

    target_agents_dir = agents_dir or (Path.home() / "Library" / "LaunchAgents")
    plist_path = target_agents_dir / f"{label}.plist"
    legacy_plist = target_agents_dir / f"{LEGACY_LAUNCHD_LABEL}.plist"
    uid = os.getuid() if hasattr(os, "getuid") else 501

    if action == "enable":
        if not employee_id:
            print(
                "錯誤：啟用排程請提供員工編號（例如：bulletin-quiz 3395 --schedule enable）",
                file=sys.stderr,
            )
            return 2

        try:
            valid_id = validate_employee_id(employee_id)
            hour, minute = parse_schedule_time(schedule_time)
        except BulletinError as exc:
            print(f"錯誤：{exc}", file=sys.stderr)
            return 2

        target_agents_dir.mkdir(parents=True, exist_ok=True)
        root = (project_root or Path(__file__).resolve().parent.parent).resolve()
        cli = resolve_cli_path(root)
        target_log = log_file or DEFAULT_LOG_PATH
        target_log.parent.mkdir(parents=True, exist_ok=True)

        path_env = get_launchd_path_env(environ or os.environ)
        plist_dict = build_launchd_plist_dict(
            label=label,
            cli_path=cli,
            employee_id=valid_id,
            hour=hour,
            minute=minute,
            log_path=target_log,
            path_env=path_env,
            config_path=config_path,
            dry_run=dry_run,
        )
        plist_bytes = plistlib.dumps(plist_dict, fmt=plistlib.FMT_XML)

        # 卸載舊服務（包含 legacy label）
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True)
        if legacy_plist.exists() or label != LEGACY_LAUNCHD_LABEL:
            subprocess.run(
                ["launchctl", "bootout", f"gui/{uid}/{LEGACY_LAUNCHD_LABEL}"],
                capture_output=True,
            )
            if legacy_plist.exists():
                legacy_plist.unlink(missing_ok=True)

        plist_path.write_bytes(plist_bytes)

        res = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            print(f"錯誤：載入 launchd 服務失敗：{res.stderr.strip()}", file=sys.stderr)
            return 2

        print(f"✓ 已成功啟用 macOS launchd 排程（{label}）：")
        print(f"  - 員工編號：{valid_id}")
        print(f"  - 執行時間：每天 {hour:02d}:{minute:02d}（若電腦睡眠，喚醒時自動補跑）")
        print(f"  - 設定檔案：{plist_path}")
        print(f"  - 執行記錄：{target_log}")
        return 0

    elif action == "disable":
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True)
        if legacy_plist.exists() or label != LEGACY_LAUNCHD_LABEL:
            subprocess.run(
                ["launchctl", "bootout", f"gui/{uid}/{LEGACY_LAUNCHD_LABEL}"],
                capture_output=True,
            )
            if legacy_plist.exists():
                legacy_plist.unlink(missing_ok=True)

        if plist_path.exists():
            plist_path.unlink()

        print("✓ 已停用 macOS launchd 排程並移除相關設定。")
        return 0

    elif action == "status":
        active_plist = (
            plist_path
            if plist_path.exists()
            else (legacy_plist if legacy_plist.exists() else None)
        )
        active_label = (
            label
            if plist_path.exists()
            else (LEGACY_LAUNCHD_LABEL if legacy_plist.exists() else label)
        )

        res = subprocess.run(
            ["launchctl", "print", f"gui/{uid}/{active_label}"],
            capture_output=True,
            text=True,
        )
        is_loaded = res.returncode == 0

        if not is_loaded and not active_plist:
            print("排程狀態：未啟用")
            print("提示：可使用「bulletin-quiz <員編> --schedule enable」啟用每日自動排程。")
            return 0

        print(f"排程狀態：{'已啟用 (launchd 運作中)' if is_loaded else '設定檔存在但尚未載入'}")
        print(f"  - 服務名稱 (Label)：{active_label}")

        if active_plist and active_plist.exists():
            try:
                data = plistlib.loads(active_plist.read_bytes())
                cal = data.get("StartCalendarInterval", {})
                h = cal.get("Hour", "--")
                m = cal.get("Minute", "--")
                if isinstance(h, int) and isinstance(m, int):
                    print(f"  - 執行時間：每天 {h:02d}:{m:02d}（若電腦睡眠，喚醒時自動補跑）")
                else:
                    print(f"  - 執行時間：每天 {h}:{m}")

                args_list = data.get("ProgramArguments", [])
                if len(args_list) >= 3:
                    cmd_str = args_list[2]
                    parts = cmd_str.split()
                    if parts:
                        emp_candidate = parts[-1]
                        if emp_candidate.isdigit():
                            print(f"  - 員工編號：{emp_candidate}")

                print(f"  - 設定檔案：{active_plist}")
                log_out = data.get("StandardOutPath", str(DEFAULT_LOG_PATH))
                print(f"  - 執行記錄：{log_out}")

                log_path = Path(log_out)
                if log_path.exists():
                    log_lines = log_path.read_text(
                        encoding="utf-8", errors="replace"
                    ).strip().splitlines()
                    if log_lines:
                        recent = log_lines[-4:]
                        print("  - 最近日誌紀錄：")
                        for line in recent:
                            print(f"    {line}")
            except Exception as exc:
                print(f"  - 讀取設定檔警告：{exc}")
        else:
            print(f"  - 設定檔案：{plist_path} (找不到檔案)")

        return 0

    elif action == "run":
        active_label = (
            label
            if plist_path.exists()
            else (LEGACY_LAUNCHD_LABEL if legacy_plist.exists() else label)
        )
        res = subprocess.run(
            ["launchctl", "kickstart", "-k", f"gui/{uid}/{active_label}"],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            print(f"錯誤：觸發排程失敗：{res.stderr.strip()}", file=sys.stderr)
            return 2
        print("✓ 已手動觸發排程執行，請稍候檢查日誌：")
        print(f"  tail -n 10 {DEFAULT_LOG_PATH}")
        return 0

    print(f"錯誤：未知的排程動作：{action}", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bulletin-quiz",
        description="查詢 104 佈告欄未完成紀錄、自動選出正確答案並登記。",
    )
    parser.add_argument(
        "employee_id",
        nargs="?",
        help="員工編號，例如 3395",
    )
    parser.add_argument(
        "-e",
        "--employee-id",
        dest="employee_id_opt",
        metavar="EMPLOYEE_ID",
        help="員工編號（亦可直接以位置參數帶入）",
    )
    parser.add_argument("--config", help="設定檔路徑（預設 bulletin-quiz.json）")
    parser.add_argument("--slug", help="只處理指定文章尾碼，例如 20260831_BeAGiver")
    parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="查詢題目與答案，但不送出登記",
    )
    parser.add_argument(
        "--schedule",
        choices=["enable", "disable", "status", "run"],
        help="設定 macOS launchd 排程（enable: 啟用, disable: 停用, status: 查看狀態, run: 立即觸發測試）",
    )
    parser.add_argument(
        "--schedule-time",
        default="10:00",
        help="排程執行時間，格式為 HH:MM（預設 10:00）",
    )
    return parser


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    project_root: Optional[Path] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.schedule:
        project_root = (project_root or Path(__file__).resolve().parent.parent).resolve()
        runtime_env = dict(os.environ if environ is None else environ)
        employee_id = args.employee_id or args.employee_id_opt
        return handle_schedule(
            args.schedule,
            employee_id=employee_id,
            schedule_time=args.schedule_time,
            config_path=args.config,
            dry_run=args.dry_run,
            project_root=project_root,
            environ=runtime_env,
        )

    employee_id = args.employee_id or args.employee_id_opt
    if not employee_id:
        print("錯誤：請提供員工編號（例如：bulletin-quiz 3395）", file=sys.stderr)
        return 2

    project_root = (project_root or Path(__file__).resolve().parent.parent).resolve()
    runtime_env = dict(os.environ if environ is None else environ)
    config_path = find_config_path(project_root, args.config, runtime_env)

    try:
        config = load_config(config_path, employee_id)
        service = BulletinService(config, HttpClient(config.employee_id))
        events, completed = service.query_records()
        pending = select_events(events, completed, args.slug)
    except BulletinError as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 2

    print(
        f"員編 {config.employee_id}：共 {len(events)} 則、已完成 {len(completed)} 則、"
        f"本次待處理 {len(pending)} 則。"
    )
    if not pending:
        if args.slug:
            matched = next((event for event in events if event.slug == args.slug), None)
            if matched and matched.key in completed:
                print(f"✓ {args.slug} 已完成。")
            else:
                print(f"找不到未完成的 {args.slug}。")
        else:
            print("✓ 沒有未完成的公告。")
        return 0

    # 1. 併發抓取所有待處理表單
    forms_cache: dict[str, Any] = {}
    if len(pending) > 1:
        with ThreadPoolExecutor(max_workers=min(8, len(pending))) as executor:
            future_to_event = {
                executor.submit(service.load_form, event): event for event in pending
            }
            for future in as_completed(future_to_event):
                event = future_to_event[future]
                try:
                    forms_cache[event.key] = future.result()
                except Exception as exc:
                    forms_cache[event.key] = exc

    # 2. 結構化解析各篇公告與題目
    tasks: list[dict[str, Any]] = []
    for event in pending:
        task: dict[str, Any] = {
            "event": event,
            "ad": event.key,
            "form": None,
            "question": "",
            "answer": "",
            "skip": False,
            "error": None,
            "verified": False,
        }
        res = forms_cache.get(event.key)
        try:
            if isinstance(res, Exception):
                raise res
            elif res is not None:
                ad, form = res
            else:
                ad, form = service.load_form(event)

            task["ad"] = ad
            task["form"] = form

            if bool(form.get("CHK")):
                task["skip"] = True
            elif event_has_ended(form):
                task["error"] = f"活動已於 {form.get('ET')} 結束。"
            else:
                question, answer = question_details(form)
                task["question"] = question
                task["answer"] = answer
        except BulletinError as exc:
            task["error"] = str(exc)

        tasks.append(task)

    # 3. 若非 dry-run，併發送出作答並批次驗證點閱紀錄
    if not args.dry_run:
        to_submit = [t for t in tasks if not t["skip"] and not t["error"]]
        if to_submit:
            def _submit_task(t: dict[str, Any]) -> None:
                try:
                    service.submit(t["ad"])
                except BulletinError as exc:
                    t["error"] = str(exc)

            if len(to_submit) > 1:
                with ThreadPoolExecutor(max_workers=min(8, len(to_submit))) as executor:
                    list(executor.map(_submit_task, to_submit))
            else:
                _submit_task(to_submit[0])

            # 收集成功送出的 ID 進行統一批次驗證
            pending_verify = [t for t in to_submit if not t["error"]]
            if pending_verify:
                target_ids = {t["event"].key for t in pending_verify} | {
                    t["ad"] for t in pending_verify if t.get("ad")
                }
                confirmed = service.wait_until_all_completed(target_ids)
                for t in pending_verify:
                    if t["event"].key in confirmed or t["ad"] in confirmed:
                        t["verified"] = True
                    else:
                        t["error"] = "送出後重新查詢，點閱紀錄仍未顯示完成"

    # 4. 依原始順序格式化輸出每篇公告結果
    failures = 0
    for index, task in enumerate(tasks, start=1):
        event = task["event"]
        print(f"\n[{index}/{len(tasks)}] {event.title or event.slug}")
        if event.start_date:
            form_et = task["form"].get("ET") if task.get("form") else None
            date_info = f"  公告日期：{event.start_date}"
            if form_et:
                date_info += f"（截止：{str(form_et).strip()}）"
            print(date_info)
        print(f"  表單：{service.form_url(event)}")

        if task["skip"]:
            print("  ✓ 表單回報已完成，略過重複登記。")
            continue

        if task["error"]:
            failures += 1
            print(f"  ✗ {task['error']}", file=sys.stderr)
            continue

        if task["question"]:
            print(f"  題目：{task['question']}")
            print(f"  作答：{task['answer']}")
        else:
            print("  此公告沒有題目。")

        if args.dry_run:
            print("  DRY RUN：未送出登記。")
        elif task["verified"]:
            print("  ✓ 已送出正確答案，且點閱紀錄驗證完成。")
        else:
            failures += 1
            print("  ✗ 送出後重新查詢，點閱紀錄仍未顯示完成", file=sys.stderr)

    if failures:
        print(f"\n完成：成功 {len(pending) - failures}、失敗 {failures}。")
        return 2
    if args.dry_run:
        print(f"\nDRY RUN 完成：檢查 {len(pending)} 則，未送出任何登記。")
    else:
        print(f"\n完成：成功 {len(pending)}、失敗 0。")
    return 0
