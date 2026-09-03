import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "lib" / "bulletin_quiz.py"
SPEC = importlib.util.spec_from_file_location("bulletin_quiz", MODULE_PATH)
quiz = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = quiz
SPEC.loader.exec_module(quiz)


class FakeClient:
    def __init__(self):
        self.posts = []
        self.completed = False

    def text(self, url):
        if url.endswith("search.html"):
            return "var apiUrl = 'https://api.example/prod';", url
        return "<html></html>", (
            "https://bulletin.example/index.html?ad=event-guid&utm_campaign=test"
        )

    def json(self, url, *, method="GET", json_body=None):
        if "/bulletin/check?" in url:
            records = [{"EventID": "event-guid"}] if self.completed else []
            return {
                "event": [
                    {
                        "ST": "2026/08/31",
                        "RU": "https://sharepoint.example/20260831_BeAGiver.aspx\n",
                        "KeyName": "event-guid",
                        "TX": "Be A Giver",
                    }
                ],
                "record": records,
            }, url
        if method == "POST":
            self.posts.append((url, json_body))
            self.completed = True
            return {"ok": True}, url
        return {
            "ET": "2099/09/10",
            "CHK": False,
            "Q": {
                "Text": "團隊到哪裡舉辦公益職涯服務？",
                "Answer": "高雄市",
                "Wrong": "高譚市",
            },
        }, url


class BulletinQuizTests(unittest.TestCase):
    def test_load_config_validates_and_keeps_employee_id_as_string(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"employee_id": 3395}), encoding="utf-8")
            config = quiz.load_config(path)

        self.assertEqual(config.employee_id, "3395")
        self.assertEqual(config.search_url, quiz.DEFAULT_SEARCH_URL)

    def test_load_config_rejects_invalid_employee_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"employee_id": "33 95"}), encoding="utf-8")
            with self.assertRaisesRegex(quiz.BulletinError, "employee_id"):
                quiz.load_config(path)

    def test_event_derives_shared_slug_from_article_url(self):
        event = quiz.Event(
            "guid",
            "2026/08/31",
            "title",
            "https://sharepoint.example/SitePages/20260831_BeAGiver.aspx\n",
        )
        self.assertEqual(event.slug, "20260831_BeAGiver")

    def test_service_discovers_api_and_sends_only_correct_registration(self):
        client = FakeClient()
        config = quiz.Config("3395")
        service = quiz.BulletinService(config, client)

        events, completed = service.query_records()
        self.assertEqual(completed, set())
        event = events[0]
        ad, form = service.load_form(event)
        question, answer = quiz.question_details(form)
        self.assertEqual(ad, "event-guid")
        self.assertIn("公益職涯服務", question)
        self.assertEqual(answer, "高雄市")

        service.submit(ad)
        self.assertEqual(
            client.posts,
            [
                (
                    "https://api.example/prod/bulletin/add",
                    {"EVENT_ID": "event-guid", "ID": "3395"},
                )
            ],
        )

    def test_http_client_carries_employee_cookie(self):
        response = unittest.mock.MagicMock()
        response.read.return_value = b"{}"
        response.geturl.return_value = "https://example.test"
        response.__enter__.return_value = response
        with patch.object(quiz, "urlopen", return_value=response) as urlopen:
            quiz.HttpClient("3395", retries=0).request("https://example.test")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Cookie"), "id=3395")

    def test_dry_run_does_not_post(self):
        client = FakeClient()
        config = quiz.Config("3395")
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(quiz, "HttpClient", return_value=client),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            config_path = Path(directory) / "bulletin-quiz.json"
            config_path.write_text(
                json.dumps({"employee_id": "3395"}), encoding="utf-8"
            )
            result = quiz.main(
                ["--config", str(config_path), "--dry-run"],
                project_root=Path(directory),
                environ={},
            )

        self.assertEqual(result, 0)
        self.assertEqual(client.posts, [])
        self.assertIn("作答：高雄市", stdout.getvalue())
        self.assertIn("未送出任何登記", stdout.getvalue())

    def test_live_flow_posts_then_verifies_record(self):
        client = FakeClient()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(quiz, "HttpClient", return_value=client),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            config_path = Path(directory) / "bulletin-quiz.json"
            config_path.write_text(
                json.dumps({"employee_id": "3395"}), encoding="utf-8"
            )
            result = quiz.main(
                ["--config", str(config_path), "--slug", "20260831_BeAGiver"],
                project_root=Path(directory),
                environ={},
            )

        self.assertEqual(result, 0)
        self.assertEqual(len(client.posts), 1)
        self.assertIn("點閱紀錄驗證完成", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
