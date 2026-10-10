import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from xhh_operator.cli import parser

REFERENCE_TOOLS = {
    "check_login_status",
    "interactive_login",
    "get_login_qr_code",
    "get_user_profile",
    "get_home_content",
    "search_content",
    "get_post_detail",
    "publish_content",
    "publish_article",
    "publish_video",
    "post_comment",
    "reply_comment",
}


def test_cli_exposes_media_video_community_and_text_reply_options():
    arguments = parser().parse_args(
        [
            "post",
            "create",
            "--title",
            "fixture",
            "--kind",
            "image_text",
            "--image",
            "fixture.png",
            "--community",
            "one",
            "--community",
            "two",
            "--hashtag",
            "topic",
            "--dry-run",
        ]
    )
    assert arguments.community == ["one", "two"] and arguments.hashtag == ["topic"]
    assert arguments.image == [Path("fixture.png")] and arguments.dry_run
    video = parser().parse_args(
        ["video", "create", "fixture.mp4", "--title", "fixture", "--cover", "cover.png"]
    )
    assert (
        video.path == Path("fixture.mp4") and video.cover == Path("cover.png") and not video.publish
    )
    reply = parser().parse_args(
        ["comment", "reply", "900", "--target-text", "target", "--text", "reply"]
    )
    assert reply.target_text == "target" and reply.reply_id is None


def test_rest_preserves_all_new_publication_fields(monkeypatch):
    import api_server

    seen = []

    async def call(method, *args, **kwargs):
        seen.append((method, args, kwargs))
        return {"ok": True, "data": {"accepted": True}}

    monkeypatch.setattr(api_server, "operator_call", call)
    client = TestClient(api_server.app)
    data = {
        "title": "fixture",
        "images": ["fixture.png"],
        "communities": ["one", "two"],
        "hashtags": ["topic"],
        "post_kind": "image_text",
        "dry_run": True,
    }
    assert client.post("/api/posts", json=data).status_code == 200
    assert seen[-1][2]["communities"] == ["one", "two"] and seen[-1][2]["images"] == ["fixture.png"]
    assert (
        client.post(
            "/api/videos",
            json={"title": "fixture", "path": "fixture.mp4", "cover": "cover.png", "dry_run": True},
        ).status_code
        == 200
    )
    assert seen[-1][0] == "write_video" and seen[-1][2]["cover"] == "cover.png"
    assert (
        client.post(
            "/api/posts/900/comments",
            json={"images": ["fixture.png"], "target_text": "target", "dry_run": True},
        ).status_code
        == 200
    )
    assert seen[-1][2]["target_text"] == "target" and seen[-1][2]["images"] == ["fixture.png"]
    assert client.get("/api/feed").status_code == 200 and seen[-1][0] == "feed"
    assert client.get("/api/profile").status_code == 200 and seen[-1][0] == "profile"


def test_mcp_tool_catalog_covers_reference_http_and_stdio_tools():
    pytest.importorskip("mcp")
    from xhh_operator.mcp_server import create_server

    async def check():
        tools = {tool.name: tool for tool in await create_server().list_tools()}
        assert REFERENCE_TOOLS.issubset(tools)
        assert tools["publish_video"].inputSchema["properties"]["coverImagePath"]
        assert tools["publish_content"].inputSchema["properties"]["communities"]
        assert tools["post_comment"].inputSchema["properties"]["images"]
        assert tools["reply_comment"].inputSchema["properties"]["targetCommentContent"]
        assert tools["get_post_detail"].annotations.readOnlyHint
        assert not tools["publish_content"].annotations.readOnlyHint

    asyncio.run(check())


def test_mcp_publication_tools_route_to_shared_operator_and_redact_session(monkeypatch):
    pytest.importorskip("mcp")
    from xhh_operator import mcp_server

    seen = []

    class FakeOperator:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def __getattr__(self, method):
            async def call(*args, **kwargs):
                seen.append((method, args, kwargs))
                return {"accepted": True, "pkey": "fixture-private", "token": "fixture-private"}

            return call

    monkeypatch.setattr(mcp_server, "Operator", FakeOperator)

    async def check():
        server = mcp_server.create_server()
        result = await server.call_tool(
            "publish_content",
            {
                "title": "fixture",
                "content": "body",
                "images": ["fixture.png"],
                "communities": ["one"],
                "tags": ["topic"],
                "dry_run": True,
            },
        )
        assert "fixture-private" not in str(result)
        assert seen[-1][0] == "write_post" and seen[-1][2]["post_kind"] == "image_text"
        await server.call_tool(
            "publish_video",
            {
                "title": "fixture",
                "videoPath": "fixture.mp4",
                "coverImagePath": "cover.png",
                "dry_run": True,
            },
        )
        assert seen[-1][0] == "write_video" and seen[-1][2]["cover"] == "cover.png"
        await server.call_tool(
            "reply_comment",
            {"postId": "900", "targetCommentContent": "target", "content": "body", "dry_run": True},
        )
        assert seen[-1][0] == "comment" and seen[-1][2]["target_text"] == "target"

    asyncio.run(check())


def test_mcp_write_defaults_are_previews_and_personal_score_rejects_boolean(monkeypatch):
    pytest.importorskip("mcp")
    from xhh_operator import mcp_server

    seen = []

    class Fake:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def comment(self, *args, **kwargs):
            seen.append(kwargs)
            return {"dry_run": kwargs["dry_run"]}

    monkeypatch.setattr(mcp_server, "Operator", Fake)

    async def check():
        server = mcp_server.create_server()
        await server.call_tool("post_comment", {"postId": "900", "content": "fixture"})
        assert seen[-1]["dry_run"]
        with pytest.raises(Exception):
            await server.call_tool(
                "create_personal_review", {"appid": "570", "score": True, "text": "fixture"}
            )
        assert len(seen) == 1

    asyncio.run(check())


def test_real_mcp_stdio_initialize_discovery_and_readonly_call(tmp_path):
    pytest.importorskip("mcp")
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def check():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "xhh_operator", "mcp"],
            env={"XHH_OPERATOR_HOME": str(tmp_path / "empty-session")},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                assert REFERENCE_TOOLS.issubset(
                    {tool.name for tool in (await client.list_tools()).tools}
                )
                response = await client.call_tool("check_login_status", {})
                assert not response.isError
                body = json.loads(response.content[0].text)
                assert body["authenticated"] is False

    asyncio.run(check())


def test_mcp_qr_image_is_returned_before_confirmation(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    from xhh_operator import mcp_server

    async def login(store, *, timeout, on_ready):
        from PIL import Image

        path = tmp_path / "fixture.png"
        Image.new("RGB", (8, 8)).save(path)
        await on_ready(path)
        await asyncio.sleep(0.01)
        path.unlink()

    monkeypatch.setattr(mcp_server, "login_qr", login)

    async def check():
        result = await mcp_server.create_server().call_tool("get_login_qr_code", {"timeout": 1})
        assert any(item.type == "image" and item.mimeType == "image/png" for item in result)
        await asyncio.sleep(0.02)

    asyncio.run(check())
    assert not (tmp_path / "fixture.png").exists()


def test_real_mcp_http_transport_initializes_and_lists_tools(tmp_path):
    pytest.importorskip("mcp")
    import os
    import socket
    import subprocess
    import sys
    import time

    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    environment = dict(os.environ, XHH_OPERATOR_HOME=str(tmp_path / "empty-session"))
    with (tmp_path / "server.log").open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "xhh_operator",
                "mcp",
                "--transport",
                "streamable-http",
                "--port",
                str(port),
            ],
            env=environment,
            stdout=log,
            stderr=log,
        )
    try:
        for _ in range(60):
            if process.poll() is not None:
                raise AssertionError("MCP HTTP server exited during startup")
            with socket.socket() as probe:
                probe.settimeout(0.1)
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.1)
        else:
            raise AssertionError("MCP HTTP startup timeout")

        async def check():
            async with streamable_http_client(f"http://127.0.0.1:{port}/mcp") as (read, write, _):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    assert REFERENCE_TOOLS.issubset(
                        {tool.name for tool in (await client.list_tools()).tools}
                    )
                    result = await client.call_tool("check_login_status", {})
                    assert not result.isError

        asyncio.run(check())
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
