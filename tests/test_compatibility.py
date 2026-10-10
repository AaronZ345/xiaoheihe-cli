import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from api_client import XiaoheiheAPIClient
from xhh_operator.compat import legacy_command
from xhh_operator.errors import OperatorError, ProtocolError
from xhh_operator.http import HeyboxAPI
from xhh_operator.service import Operator


@pytest.mark.parametrize(
    "command", ["get", "comments", "batch", "creator", "list", "pub", "serve", "status"]
)
def test_upstream_commands_route_with_global_output_options(command):
    assert legacy_command(["--headless", "-f", "json", command, "--help"]) == command


def test_personal_commands_do_not_get_routed_to_upstream():
    assert legacy_command(["review", "get", "570"]) is None
    assert legacy_command(["-f", "csv", "games"]) is None


class Context:
    async def cookies(self):
        return []


class Page:
    context = Context()


@pytest.mark.parametrize("mode", ["direct", "cookie"])
def test_saved_session_queries_do_not_wait_for_website_homepage(monkeypatch, mode):
    import xiaoheihe

    class Manager:
        api_page = Page()
        heybox_id = "42"

        def __init__(self, **kwargs):
            pass

        async def inject_cookies(self, cookie, persist):
            assert not persist

        async def validate_cookies(self, *, prepare_page=True):
            assert not prepare_page
            return True

        async def start_session(self):
            raise AssertionError("HTTP 查询不应导航官网首页")

        async def close(self):
            pass

    monkeypatch.setattr(xiaoheihe, "BrowserManager", Manager)
    monkeypatch.setattr(xiaoheihe, "get_cookie", lambda: "fixture-only")

    async def check():
        client = xiaoheihe.XiaoheiheClient()
        try:
            if mode == "cookie":
                await client.connect_with_cookies("fixture-only")
            else:
                await client.connect()
            assert client._api_client is not None
        finally:
            await client.close()

    asyncio.run(check())


def test_creator_reads_use_official_parameters_without_website_navigation(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/list"):
            assert request.url.params["article_type"] == "all"
            assert request.url.params["artilce_state"] == "all"
            assert request.url.params["sort_filter"] == "create_at"
            result = {"articles": []}
        else:
            assert request.url.params["link_id"] == "123"
            result = {"article": {"link_id": 123}}
        return httpx.Response(200, json={"status": "ok", "result": result})

    monkeypatch.setattr(
        "xhh_operator.http.HeyboxAPI",
        lambda cookies: HeyboxAPI(cookies, transport=httpx.MockTransport(handler), interval=0),
    )

    async def check():
        api = XiaoheiheAPIClient(Page())
        assert (await api.get_article_list())["result"]["articles"] == []
        assert (await api.get_creator_data("123"))["result"]["article"]["link_id"] == 123

    asyncio.run(check())
    assert len(seen) == 2 and all(request.method == "GET" for request in seen)


def test_full_comments_advances_root_pages_and_preserves_complete_replies(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("sub/comments"):
            result = {
                "has_more": False,
                "comments": [{"commentid": 11, "replyid": 10}, {"commentid": 12, "replyid": 11}],
            }
        elif request.url.params["offset"] == "0":
            result = {
                "link": {"linkid": 123},
                "has_more_floors": True,
                "comments": [
                    {
                        "comment": [
                            {"commentid": 10, "child_num": 2},
                            {"commentid": 11, "replyid": 10},
                        ]
                    }
                ],
            }
        else:
            result = {
                "link": {"linkid": 123},
                "has_more_floors": False,
                "comments": [{"comment": [{"commentid": 20, "child_num": 0}]}],
            }
        return httpx.Response(200, json={"status": "ok", "result": result})

    monkeypatch.setattr(
        "xhh_operator.http.HeyboxAPI",
        lambda cookies: HeyboxAPI(cookies, transport=httpx.MockTransport(handler), interval=0),
    )
    result = asyncio.run(XiaoheiheAPIClient(Page()).get_post_full("123", page_size=2))["result"]
    assert [g["comment"][0]["commentid"] for g in result["comments"]] == [10, 20]
    assert [c["commentid"] for c in result["comments"][0]["comment"]] == [10, 11, 12]
    assert [r.url.params.get("offset") for r in calls] == ["0", None, "1"]
    assert result["full_comments"] and not result["has_more_floors"]


def test_repeated_comment_page_fails_instead_of_claiming_completeness(monkeypatch):
    body = {
        "status": "ok",
        "result": {
            "has_more_floors": True,
            "comments": [{"comment": [{"commentid": 1, "child_num": 0}]}],
        },
    }
    monkeypatch.setattr(
        "xhh_operator.http.HeyboxAPI",
        lambda cookies: HeyboxAPI(
            cookies,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
            interval=0,
        ),
    )
    with pytest.raises(ProtocolError, match="结果不完整"):
        asyncio.run(XiaoheiheAPIClient(Page()).get_post_full("123"))


def test_full_comments_use_web_page_and_last_visible_reply_id(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("sub/comments"):
            cursor = request.url.params.get("lastval")
            if cursor == "11":
                result = {"comments": [{"commentid": 12}], "has_more": True}
            elif cursor == "12":
                result = {"comments": [{"commentid": 13}], "has_more": False}
            else:
                result = {"comments": [{"commentid": 11}], "has_more": True}
        elif request.url.params.get("page") == "2":
            result = {"comments": [{"comment": [{"commentid": 20}]}], "has_more_floors": False}
        else:
            result = {
                "comments": [{"comment": [{"commentid": 10, "child_num": 3}, {"commentid": 11}]}],
                "has_more_floors": True,
            }
        return httpx.Response(200, json={"status": "ok", "result": result})

    monkeypatch.setattr(
        "xhh_operator.http.HeyboxAPI",
        lambda cookies: HeyboxAPI(cookies, transport=httpx.MockTransport(handler), interval=0),
    )
    result = asyncio.run(XiaoheiheAPIClient(Page()).get_post_full("123"))["result"]
    assert [group["comment"][0]["commentid"] for group in result["comments"]] == [10, 20]
    assert [item["commentid"] for item in result["comments"][0]["comment"]] == [10, 11, 12, 13]
    root_requests = [request for request in seen if not request.url.path.endswith("sub/comments")]
    assert [request.url.params["is_first"] for request in root_requests] == ["1", "0"]


def test_comment_page_two_does_not_reset_first_page_state(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"status": "ok", "result": {"comments": []}})

    monkeypatch.setattr(
        "xhh_operator.http.HeyboxAPI",
        lambda cookies: HeyboxAPI(cookies, transport=httpx.MockTransport(handler), interval=0),
    )
    asyncio.run(XiaoheiheAPIClient(Page()).get_post_comments("123", page_num=2, limit=20))
    assert seen[0].url.params["page"] == "2" and seen[0].url.params["is_first"] == "0"


def test_rest_routes_preserve_upstream_and_expose_new_reviews(monkeypatch):
    import api_server

    async def fake_call(method, *args, **kwargs):
        return {"ok": True, "data": {"method": method, "kwargs": kwargs}}

    monkeypatch.setattr(api_server, "operator_call", fake_call)
    client = TestClient(api_server.app)
    paths = {route.path for route in api_server.app.routes}
    assert "/api/post/{post_id}" in paths
    assert "/api/reviews/{appid}" in paths
    assert client.get("/api/reviews?limit=101").status_code == 400
    assert client.post("/api/reviews/570", json={"score": 6, "text": "短评"}).status_code == 422
    assert client.patch("/api/reviews/570", json={}).status_code == 400
    response = client.patch("/api/reviews/570", json={"score": 4, "dry_run": True})
    assert response.status_code == 200
    assert response.json()["data"]["kwargs"]["edit"] is True
    assert response.json()["data"]["kwargs"]["dry_run"] is True


def test_personal_summary_never_uses_community_score(tmp_path):
    from xhh_operator.session import SessionStore

    store = SessionStore(tmp_path)
    store.save([{"name": "user_pkey", "value": "fixture", "domain": ".xiaoheihe.cn"}], "42")

    def handler(request):
        result = (
            {"profile": {"heybox_id": "42"}}
            if request.url.path == "/account/restore_login"
            else {
                "game_list": [
                    {"appid": 570, "name": "测试游戏", "score": "9.8", "comment_score": 4}
                ]
            }
        )
        return httpx.Response(200, json={"status": "ok", "result": result})

    async def check():
        async with Operator(
            store, api=HeyboxAPI(transport=httpx.MockTransport(handler), interval=0)
        ) as op:
            result = await op.reviews(summary=True)
        assert result["items"][0]["personal_score"] == 4
        assert "9.8" not in json.dumps(result)

    asyncio.run(check())


def test_rest_article_and_comment_writes_route_to_real_operations(monkeypatch):
    import api_server

    calls = []

    async def fake_call(method, *args, **kwargs):
        calls.append((method, args, kwargs))
        return {"ok": True, "data": {"accepted": True}}

    monkeypatch.setattr(api_server, "operator_call", fake_call)
    client = TestClient(api_server.app)
    body = {"title": "标题", "text": "正文", "tag": 11, "dry_run": True}
    assert client.post("/api/posts", json=body).status_code == 200
    assert calls[-1][0] == "write_post" and calls[-1][2]["draft"] is True
    assert client.patch("/api/posts/123", json=body).status_code == 200
    assert calls[-1][2]["postid"] == "123"
    assert client.delete("/api/posts/123?dry_run=true").status_code == 200
    assert calls[-1][0] == "delete_post" and calls[-1][2]["dry_run"] is True
    assert (
        client.post("/api/posts/123/comments", json={"text": "回复", "reply_id": "2"}).status_code
        == 400
    )
    assert (
        client.post(
            "/api/posts/123/comments",
            json={"text": "回复", "reply_id": "2", "root_id": "1", "dry_run": True},
        ).status_code
        == 200
    )
    assert calls[-1][0] == "comment" and calls[-1][2]["reply_id"] == "2"


def test_rest_batch_returns_results_and_stops_on_failure(monkeypatch):
    import api_server
    from xhh_operator.errors import ProtocolError

    ids = []

    class API:
        async def get_post_comments(self, postid, **kwargs):
            ids.append(postid)
            if postid == "2":
                raise ProtocolError("fixture failure")
            return {"status": "ok", "result": {"link": {"linkid": postid}}}

    async def no_wait(_):
        pass

    monkeypatch.setattr(api_server, "api_client", API())
    monkeypatch.setattr(api_server.asyncio, "sleep", no_wait)
    client = TestClient(api_server.app)
    result = client.post("/api/posts/batch", json={"urls": ["1"]})
    assert result.status_code == 200 and len(result.json()["data"]) == 1
    ids.clear()
    result = client.post("/api/posts/batch", json={"urls": ["1", "2", "3"]})
    assert result.status_code == 502 and ids == ["1", "2"]


@pytest.mark.parametrize("path", ["/api/post/123", "/api/post/123/comments", "/api/post/123/full"])
@pytest.mark.parametrize(
    "code,status", [("auth", 401), ("captcha", 428), ("rate_limit", 429), ("network", 503)]
)
def test_legacy_rest_reads_classify_platform_errors(monkeypatch, path, code, status):
    import api_server

    class API:
        async def get_post_comments(self, *args, **kwargs):
            raise OperatorError("fixture failure", code)

        get_post_full = get_post_comments

    monkeypatch.setattr(api_server, "api_client", API())
    response = TestClient(api_server.app).get(path)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


def test_daemon_stop_finishes_start_and_closes_listener(monkeypatch):
    import xiaoheihe

    managers = []

    class Manager:
        cookies = []
        heybox_id = None
        api_page = Page()
        closed = False

        def __init__(self, **kwargs):
            managers.append(self)

        async def init(self):
            pass

        async def close(self):
            self.closed = True

    monkeypatch.setattr(xiaoheihe, "BrowserManager", Manager)
    monkeypatch.setattr("config.get_cookie", lambda: "")

    async def check():
        ready = asyncio.Event()
        listener = {}
        original_start = asyncio.start_server

        async def started(*args, **kwargs):
            server = await original_start(*args, **kwargs)
            listener["port"] = server.sockets[0].getsockname()[1]
            ready.set()
            return server

        monkeypatch.setattr(asyncio, "start_server", started)
        daemon = xiaoheihe.DaemonServer(port=0)
        task = asyncio.create_task(daemon.start())
        try:
            await asyncio.wait_for(ready.wait(), timeout=2)
            reader, writer = await asyncio.open_connection("127.0.0.1", listener["port"])
            writer.write(b'{"action":"stop"}\n')
            await writer.drain()
            assert json.loads(await reader.readline())["status"] == "ok"
            writer.close()
            await writer.wait_closed()
            await asyncio.wait_for(asyncio.shield(task), timeout=1)
            with pytest.raises(OSError):
                await asyncio.open_connection("127.0.0.1", listener["port"])
            assert managers[0].closed
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await daemon.stop()

    asyncio.run(check())
