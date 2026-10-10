import asyncio
import json
import os
import stat
from urllib.parse import parse_qs

import httpx
import pytest

from xhh_operator.auth import identity, verify
from xhh_operator.cli import main, parser
from xhh_operator.errors import AuthError, OperatorError, ProtocolError
from xhh_operator.http import HeyboxAPI
from xhh_operator.service import Operator, encode_text, review_record
from xhh_operator.session import SessionStore, safe_result
from xhh_operator.signing import sign


@pytest.fixture
def store(tmp_path):
    session = SessionStore(tmp_path / "account")
    session.save([{"name": "user_pkey", "value": "fixture-only", "domain": ".xiaoheihe.cn"}], "42")
    return session


def run(coro):
    return asyncio.run(coro)


def account():
    return {"status": "ok", "result": {"profile": {"heybox_id": "42"}}}


def personal_review(score="4", text="旧短评"):
    return {
        "exists": True,
        "impression_score": score,
        "link": {"linkid": "900", "userid": "42", "text": encode_text(text)},
    }


def test_sign_matches_independent_official_website_vectors():
    nonce = "0123456789ABCDEF0123456789ABCDEF"
    assert sign("/account/get_qrcode_url/", 1700000000, nonce) == "UV77P62"
    assert sign("bbs/app/api/link/post/", 1700000000, nonce) == "YT27P47"


def test_session_private_atomic_and_isolated(store, tmp_path):
    if os.name != "nt":
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
        assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
    assert store.load()["user_id"] == "42"
    foreign = tmp_path / "other-session"
    foreign.write_text("keep")
    store.delete()
    assert store.load() is None
    assert foreign.read_text() == "keep"
    assert not list(store.root.glob(".session-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink protection check")
def test_session_rejects_symlink(store, tmp_path):
    target = tmp_path / "target"
    target.write_text("untouched")
    store.path.unlink()
    store.path.symlink_to(target)
    with pytest.raises(OperatorError):
        store.save([{"name": "a", "value": "b", "domain": ".xiaoheihe.cn"}], "42")
    with pytest.raises(OperatorError):
        store.load()
    assert target.read_text() == "untouched"


def test_sensitive_response_fields_never_leave_cli():
    result = safe_result(
        {
            "profile": {"user_pkey": "private", "x_xhh_tokenid": "private", "nickname": "test"},
            "items": [{"token": "private", "text": "公开短评"}],
        }
    )
    assert result == {"profile": {"nickname": "test"}, "items": [{"text": "公开短评"}]}
    assert "private" not in json.dumps(result)


def test_public_access_is_not_account_authentication():
    with pytest.raises(AuthError):
        identity({"status": "ok", "result": {"link": {"linkid": "900"}}})


def test_account_switch_stops_operation():
    async def check():
        async with HeyboxAPI(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=account())), interval=0
        ) as api:
            with pytest.raises(AuthError):
                await verify(api, "another-account")

    run(check())


@pytest.mark.parametrize(
    "status,code", [(401, "auth"), (403, "auth"), (429, "rate_limit"), (500, "upstream")]
)
def test_http_failures_stop_once_and_redact_request(status, code):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, text="private material")

    async def check():
        async with HeyboxAPI(transport=httpx.MockTransport(handler), interval=0) as api:
            with pytest.raises(OperatorError) as error:
                await api.request("/bbs/app/api/link/post", form={"text": "test"})
            assert error.value.code == code
            assert "private" not in str(error.value)
            assert len(requests) == 1

    run(check())


def test_ambiguous_write_timeout_is_never_retried():
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("private URL", request=request)

    async def check():
        async with HeyboxAPI(transport=httpx.MockTransport(handler), interval=0) as api:
            with pytest.raises(OperatorError, match="结果未知"):
                await api.request("/bbs/app/api/link/post", form={"text": "test"})
            assert len(requests) == 1

    run(check())


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"status": "show_captcha"},
        {"status": "relogin"},
        {"status": "unknown", "msg": "private material"},
    ],
)
def test_incompatible_or_rejected_responses_do_not_look_successful(body):
    async def check():
        async with HeyboxAPI(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)), interval=0
        ) as api:
            with pytest.raises(OperatorError) as error:
                await api.request("/account/restore_login")
            assert "private" not in str(error.value)

    run(check())


def test_empty_and_unknown_review_are_distinguished():
    assert review_record({"exists": False, "name": "游戏", "link": None}) is None
    with pytest.raises(ProtocolError):
        review_record({"exists": True, "unexpected": "changed"})


def test_personal_list_uses_current_account_and_requested_page(store):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/account/restore_login":
            return httpx.Response(200, json=account())
        return httpx.Response(
            200, json={"status": "ok", "result": {"game_list": [], "last_val": "next"}}
        )

    async def check():
        async with Operator(
            store, api=HeyboxAPI(transport=httpx.MockTransport(handler), interval=0)
        ) as operator:
            await operator.reviews(offset=40, limit=10)
        request = seen[-1]
        assert request.url.path == "/account/my_comment_list"
        assert request.url.params["userid"] == "42"
        assert request.url.params["offset"] == "40"
        assert request.url.params["limit"] == "10"

    run(check())


@pytest.mark.parametrize("action", ["create", "edit", "delete"])
def test_review_dry_run_never_sends_a_write(store, action):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/account/restore_login":
            return httpx.Response(200, json=account())
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "result": {"exists": False} if action == "create" else personal_review(),
            },
        )

    async def check():
        async with Operator(
            store, api=HeyboxAPI(transport=httpx.MockTransport(handler), interval=0)
        ) as operator:
            if action == "delete":
                result = await operator.delete_review("570", dry_run=True)
            else:
                result = await operator.write_review(
                    "570", score=5, content="新短评", edit=action == "edit", dry_run=True
                )
            assert result["dry_run"]
        assert all(request.method == "GET" for request in seen)

    run(check())


def test_edit_score_preserves_original_text_and_reads_back(store):
    writes = []

    def handler(request):
        if request.url.path == "/account/restore_login":
            return httpx.Response(200, json=account())
        if request.method == "POST":
            writes.append(parse_qs(request.content.decode()))
            assert "_rnd" in request.url.params
            return httpx.Response(200, json={"status": "ok", "link_id": "900"})
        return httpx.Response(
            200, json={"status": "ok", "result": personal_review("5" if writes else "4")}
        )

    async def check():
        async with Operator(
            store, api=HeyboxAPI(transport=httpx.MockTransport(handler), interval=0)
        ) as operator:
            result = await operator.write_review("570", score=5, edit=True)
        assert writes == [
            {
                "appid": ["570"],
                "score": ["5"],
                "text": [encode_text("旧短评")],
                "game_impression_post_type": ["2"],
                "link_tag": ["3"],
                "edit": ["1"],
                "link_id": ["900"],
            }
        ]
        assert result["accepted"] and result["verified"]

    run(check())


def test_existing_review_cannot_be_accidentally_created_twice(store):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json=account()
            if request.url.path == "/account/restore_login"
            else {"status": "ok", "result": personal_review()},
        )

    async def check():
        async with Operator(
            store, api=HeyboxAPI(transport=httpx.MockTransport(handler), interval=0)
        ) as operator:
            with pytest.raises(OperatorError) as error:
                await operator.write_review("570", score=5, content="新短评")
            assert error.value.code == "conflict"
        assert all(request.method == "GET" for request in seen)

    run(check())


def test_deleting_foreign_post_is_stopped_before_write(store):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json=account()
            if request.url.path == "/account/restore_login"
            else {"status": "ok", "result": {"link": {"user": {"userid": "foreign"}}}},
        )

    async def check():
        async with Operator(
            store, api=HeyboxAPI(transport=httpx.MockTransport(handler), interval=0)
        ) as operator:
            with pytest.raises(OperatorError) as error:
                await operator.delete_post("900")
            assert error.value.code == "ownership"
        assert all(request.method == "GET" for request in seen)

    run(check())


def test_login_accepts_no_password_or_cookie_on_command_line():
    with pytest.raises(SystemExit):
        parser().parse_args(["login", "--password", "fixture"])
    with pytest.raises(SystemExit):
        parser().parse_args(["login", "--cookie", "fixture"])
    assert parser().parse_args(["login", "--browser"]).browser


def test_cli_auth_status_is_one_json_record(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XHH_OPERATOR_HOME", str(tmp_path / "session"))
    main(["auth", "status", "--offline"])
    output = capsys.readouterr()
    assert json.loads(output.out)["data"]["stored"] is False
    assert len(output.out.splitlines()) == 1
