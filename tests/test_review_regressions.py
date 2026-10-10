import asyncio

import httpx
import pytest

from xhh_operator import auth
from xhh_operator.errors import OperatorError, ProtocolError
from xhh_operator.http import HeyboxAPI
from xhh_operator.service import Operator, encode_text
from xhh_operator.session import SessionStore


class QRAPI:
    def __init__(self, *args):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def request(self, path, **kwargs):
        if "get_qrcode" in path:
            return {
                "status": "ok",
                "result": {"qr_url": "https://www.xiaoheihe.cn/?qr=fixture-only"},
            }
        return {"status": "ok", "result": {"error": "expired"}}


def test_qr_destination_never_overwrites_existing_file(tmp_path, monkeypatch):
    output = tmp_path / "existing-file"
    output.write_text("keep-existing-content")
    monkeypatch.setattr(auth, "HeyboxAPI", QRAPI)

    async def immediate(_):
        pass

    monkeypatch.setattr(auth.asyncio, "sleep", immediate)
    with pytest.raises(OperatorError, match="存在"):
        asyncio.run(auth.login_qr(SessionStore(tmp_path / "session"), qr_file=output, timeout=1))
    assert output.read_text() == "keep-existing-content"


def test_qr_image_error_cleans_owned_temporary_file(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "session")
    monkeypatch.setattr(auth, "HeyboxAPI", QRAPI)

    def broken_image(*args, **kwargs):
        raise OSError("fixture rendering error")

    monkeypatch.setattr(auth.qrcode.QRCode, "make_image", broken_image)
    with pytest.raises(OSError):
        asyncio.run(auth.login_qr(store))
    assert not list(store.root.glob("login-qr*.png"))


def test_host_only_cookie_aliases_are_usable_for_account_api():
    cookies = [
        {"name": name, "value": value, "domain": "www.xiaoheihe.cn", "path": "/"}
        for name, value in (
            ("pkey", "fixture-only"),
            ("user_pkey", "fixture-only"),
            ("heybox_id", "42"),
            ("user_heybox_id", "42"),
        )
    ]

    def handler(request):
        assert "fixture-only" in request.headers.get("cookie", "")
        return httpx.Response(
            200, json={"status": "ok", "result": {"profile": {"heybox_id": "42"}}}
        )

    async def check():
        async with HeyboxAPI(
            auth.normalize_cookies(cookies), transport=httpx.MockTransport(handler), interval=0
        ) as api:
            assert await auth.verify(api) == "42"

    asyncio.run(check())


@pytest.mark.parametrize("mismatch", [{"userid": "99"}, {"appid": "999"}])
def test_review_delete_rejects_mismatched_record_before_any_write(tmp_path, mismatch):
    store = SessionStore(tmp_path / "session")
    store.save([{"name": "pkey", "value": "fixture-only", "domain": ".xiaoheihe.cn"}], "42")
    requests = []

    def handler(request):
        requests.append(request)
        result = (
            {"profile": {"heybox_id": "42"}}
            if request.url.path == "/account/restore_login"
            else {
                "exists": True,
                "appid": "570",
                "link": {
                    "linkid": "900",
                    "userid": "42",
                    "appid": "570",
                    "text": encode_text("fixture"),
                    **mismatch,
                },
            }
        )
        return httpx.Response(200, json={"status": "ok", "result": result})

    async def check():
        async with Operator(
            store, api=HeyboxAPI(transport=httpx.MockTransport(handler), interval=0)
        ) as operator:
            with pytest.raises(ProtocolError):
                await operator.delete_review("570")
        assert all(request.method == "GET" for request in requests)

    asyncio.run(check())


@pytest.mark.parametrize("value", ["unexpected", ["unexpected"]])
def test_malformed_profile_has_structured_protocol_error(value):
    with pytest.raises(ProtocolError):
        auth.identity({"status": "ok", "result": {"profile": value}})


@pytest.mark.parametrize("score", [4.5, True, float("nan"), float("inf")])
def test_sdk_does_not_round_or_coerce_invalid_personal_score(tmp_path, score):
    store = SessionStore(tmp_path / "session")
    store.save([{"name": "pkey", "value": "fixture-only", "domain": ".xiaoheihe.cn"}], "42")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"status": "ok", "result": {}})

    async def check():
        async with Operator(
            store, api=HeyboxAPI(transport=httpx.MockTransport(handler), interval=0)
        ) as operator:
            with pytest.raises(ValueError, match="整数"):
                await operator.write_review("570", score=score, content="fixture")

    asyncio.run(check())
    assert requests == []


def test_post_readback_does_not_verify_matching_title_with_stale_body(tmp_path):
    store = SessionStore(tmp_path / "session")
    store.save([{"name": "pkey", "value": "fixture-only", "domain": ".xiaoheihe.cn"}], "42")

    def handler(request):
        if request.url.path == "/account/restore_login":
            result = {"profile": {"heybox_id": "42"}}
        elif request.method == "POST":
            return httpx.Response(200, json={"status": "ok", "link_id": "900"})
        else:
            result = {
                "link": {
                    "linkid": "900",
                    "userid": "42",
                    "title": "fixture title",
                    "text": encode_text("stale body"),
                }
            }
        return httpx.Response(200, json={"status": "ok", "result": result})

    async def check():
        async with Operator(
            store, api=HeyboxAPI(transport=httpx.MockTransport(handler), interval=0)
        ) as operator:
            result = await operator.write_post(
                "fixture title", "new body", tag=11, draft=False, readback_attempts=1
            )
            assert result["accepted"] is True and result["verified"] is False

    asyncio.run(check())


def test_draft_readback_handles_delayed_title_without_resubmitting(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "session")
    store.save([{"name": "pkey", "value": "fixture-only", "domain": ".xiaoheihe.cn"}], "42")
    writes = []
    reads = []
    expected_text = encode_text("new body")

    def handler(request):
        if request.url.path == "/account/restore_login":
            result = {"profile": {"heybox_id": "42"}}
        elif request.method == "POST":
            writes.append(request)
            from urllib.parse import parse_qs

            nonlocal expected_text
            expected_text = parse_qs(request.content.decode())["text"][0]
            return httpx.Response(200, json={"status": "ok", "link_id": "900"})
        else:
            reads.append(request)
            result = {
                "link": {
                    "linkid": "900",
                    "userid": "42",
                    "title": "new title" if len(reads) > 1 else "old title",
                    "text": expected_text,
                }
            }
        return httpx.Response(200, json={"status": "ok", "result": result})

    async def no_wait(_):
        pass

    monkeypatch.setattr("xhh_operator.service.asyncio.sleep", no_wait)

    async def check():
        async with Operator(
            store, api=HeyboxAPI(transport=httpx.MockTransport(handler), interval=0)
        ) as operator:
            result = await operator.write_post("new title", "new body", tag=11, draft=True)
            assert result["verified"] is True

    asyncio.run(check())
    assert len(writes) == 1 and len(reads) == 2


@pytest.mark.parametrize("kind,search_type", [("post", "link"), ("user", "user")])
def test_search_uses_official_keyword_and_type_instead_of_empty_success(
    tmp_path, kind, search_type
):
    def handler(request):
        params = request.url.params
        items = (
            [{"type": search_type, "info": {"linkid": "123"}}]
            if (params.get("q") == "fixture keyword" and params.get("search_type") == search_type)
            else []
        )
        return httpx.Response(200, json={"status": "ok", "result": {"items": items}})

    async def check():
        async with Operator(
            SessionStore(tmp_path),
            api=HeyboxAPI(transport=httpx.MockTransport(handler), interval=0),
        ) as operator:
            result = await operator.search("fixture keyword", kind=kind)
        assert len(result["result"]["items"]) == 1

    asyncio.run(check())
