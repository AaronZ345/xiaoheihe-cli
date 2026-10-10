import asyncio
import json
import time
from urllib.parse import parse_qs

import httpx
import pytest
from PIL import Image

from xhh_operator.article import prepare_article, semantic_html
from xhh_operator.comments import locate_comment
from xhh_operator.errors import OperatorError, ProtocolError
from xhh_operator.http import HeyboxAPI
from xhh_operator.media import LocalMedia, MediaUploader, inspect_image, media_url, same_asset
from xhh_operator.service import Operator
from xhh_operator.session import SessionStore


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "fixture.png"
    Image.new("RGB", (32, 24), "gray").save(path)
    return path


@pytest.fixture
def store(tmp_path):
    store = SessionStore(tmp_path / "session")
    store.save([{"name": "pkey", "value": "fixture-only", "domain": ".xiaoheihe.cn"}], "42")
    return store


def test_upload_uses_separate_cos_credentials_and_confirms_callback(image):
    steps = []
    key = "/fixture/image.png"

    def platform(request):
        steps.append(request.url.path)
        form = parse_qs(request.content.decode())
        if request.url.path.endswith("info/v2"):
            metadata = json.loads(form["file_infos"][0])[0]
            assert metadata["width"] == 32 and metadata["height"] == 24
            result = {"keys": [key], "bucket": "fixture-123456", "region": "ap-shanghai"}
        elif request.url.path.endswith("token/v2"):
            assert json.loads(form["keys"][0]) == [key]
            result = {
                "credentials": {
                    "tmpSecretId": "fixture-id",
                    "tmpSecretKey": "fixture-secret",
                    "sessionToken": "fixture-session",
                },
                "startTime": int(time.time()) - 10,
                "expiredTime": int(time.time()) + 600,
            }
        else:
            assert request.url.params["is_finished"] == "true"
            result = {"preview_urls": ["https://media.max-c.com/fixture.png"], "thumbs": [""]}
        return httpx.Response(200, json={"status": "ok", "result": result})

    async def storage(request):
        steps.append("cos.put")
        assert (
            request.method == "PUT"
            and request.url.host == "fixture-123456.cos.ap-shanghai.myqcloud.com"
        )
        assert "cookie" not in request.headers
        assert request.headers["x-cos-security-token"] == "fixture-session"
        assert "q-header-list=content-type;host" in request.headers["authorization"]
        assert await request.aread() == image.read_bytes()
        return httpx.Response(200)

    async def check():
        async with HeyboxAPI(
            [{"name": "pkey", "value": "fixture-only", "domain": ".xiaoheihe.cn"}],
            transport=httpx.MockTransport(platform),
            interval=0,
        ) as api:
            result = await MediaUploader(
                api, storage_transport=httpx.MockTransport(storage)
            ).upload(inspect_image(image))
        assert result["url"] == "https://media.max-c.com/fixture.png"
        assert "fixture-secret" not in json.dumps(result) and "fixture-session" not in json.dumps(
            result
        )

    asyncio.run(check())
    assert len(steps) == 4 and steps[-1].endswith("callback/v2")


def test_upload_timeout_never_repeats_put_or_submits_callback(image):
    seen = []

    def platform(request):
        seen.append(request.url.path)
        result = (
            {"keys": ["/image.png"], "bucket": "fixture-123", "region": "ap-shanghai"}
            if request.url.path.endswith("info/v2")
            else {
                "credentials": {
                    "tmpSecretId": "fixture-id",
                    "tmpSecretKey": "fixture-secret",
                    "sessionToken": "fixture-session",
                },
                "startTime": 1,
                "expiredTime": int(time.time()) + 600,
            }
        )
        return httpx.Response(200, json={"status": "ok", "result": result})

    def storage(request):
        seen.append("put")
        raise httpx.ReadTimeout("private transport data", request=request)

    async def check():
        async with HeyboxAPI(transport=httpx.MockTransport(platform), interval=0) as api:
            with pytest.raises(OperatorError, match="不会自动重发") as error:
                await MediaUploader(api, storage_transport=httpx.MockTransport(storage)).upload(
                    inspect_image(image)
                )
            assert "private" not in str(error.value)

    asyncio.run(check())
    assert len(seen) == 3 and seen.count("put") == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://media.max-c.com/a",
        "https://media.max-c.com.evil.test/a",
        "https://media.max-c.com/a?token=fixture",
    ],
)
def test_untrusted_or_credential_bearing_media_url_is_not_returned(url):
    with pytest.raises(ProtocolError):
        media_url(url)


def test_article_preserves_local_image_positions_and_deduplicates_upload(image):
    article = prepare_article(f"before\n\n![sample]({image})\n\nafter", [image])
    assert len(article.images) == 1
    rendered = article.render(["https://media.max-c.com/fixture.png"])
    assert rendered.index("before") < rendered.index("fixture.png") < rendered.index("after")
    assert str(image) not in rendered


def test_platform_cdn_aliases_match_only_the_same_strong_resource_identifier():
    key = "abcdef0123456789abcdef0123456789"
    assert same_asset(
        f"https://media.max-c.com/tmp/{key}.png",
        f"https://img.xiaoheihe.cn/bbs/{key}.jpg?imageMogr2/thumbnail/256x",
    )
    assert not same_asset(f"https://media.max-c.com/{key}.png", f"https://evil.test/{key}.png")
    assert not same_asset("https://media.max-c.com/image.png", "https://img.xiaoheihe.cn/image.png")


def test_article_readback_compares_semantics_without_ignoring_changed_body():
    key = "abcdef0123456789abcdef0123456789"
    original = f"https://media.max-c.com/{key}.png"
    alias = f"https://img.xiaoheihe.cn/{key}.jpg?imageMogr2/thumbnail/256x"
    left = f'<p>body</p><img src="{original}" data-original="{original}" data-width="256">'
    right = f'<p>body</p><img data-width="256" src="{alias}" data-original="{alias}" />'
    assert semantic_html(left, [original]) == semantic_html(right, [original])
    assert semantic_html(left, [original]) != semantic_html(
        right.replace("body", "changed"), [original]
    )


def test_article_bare_absolute_image_path_is_uploaded_but_code_example_is_not(image):
    article = prepare_article(f"before\n\n{image}\n\nafter\n\n`{image}`")
    assert len(article.images) == 1
    assert "xhh-upload:0" in article.rendered
    assert str(image) in article.rendered


def test_missing_image_is_rejected_before_any_account_request(tmp_path, store):
    requests = []

    async def check():
        async with Operator(
            store,
            api=HeyboxAPI(transport=httpx.MockTransport(lambda r: requests.append(r)), interval=0),
        ) as operator:
            with pytest.raises(ValueError):
                await operator.write_post("title", "body", images=[tmp_path / "missing.png"])

    asyncio.run(check())
    assert requests == []


class Uploader:
    def __init__(self):
        self.files = []

    async def upload(self, media):
        self.files.append(media)
        return {
            "url": "https://media.max-c.com/" + media.path.name,
            "thumb": "https://media.max-c.com/auto-cover.png",
        }


def test_images_communities_hashtags_and_post_readback_are_all_checked(image, store):
    writes, saved = [], {}
    uploader = Uploader()

    def handler(request):
        if request.url.path == "/account/restore_login":
            result = {"profile": {"heybox_id": "42"}}
        elif "topic_selection/search" in request.url.path:
            name = request.url.params["q"]
            result = {
                "search_result": [
                    {
                        "search_type": "topic" if name.startswith("community") else "hashtag",
                        "name": name,
                        "topic_id": "100" if name.endswith("1") else "200",
                    }
                ]
            }
        elif request.method == "POST":
            writes.append(request)
            saved.update(
                {
                    k: v[0]
                    for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()
                }
            )
            return httpx.Response(200, json={"status": "ok", "result": {"link_id": "900"}})
        else:
            result = {
                "link": {
                    "linkid": "900",
                    "userid": "42",
                    "title": saved["title"],
                    "text": saved["text"],
                    "topics": [{"topic_id": "100"}, {"topic_id": "200"}],
                    "hashtags": [{"name": "topic"}],
                }
            }
        return httpx.Response(200, json={"status": "ok", "result": result})

    async def check():
        async with Operator(
            store,
            api=HeyboxAPI(transport=httpx.MockTransport(handler), interval=0),
            uploader=uploader,
        ) as operator:
            plan = await operator.write_post(
                "title",
                "body",
                images=[image],
                communities=["community1", "community2"],
                hashtags=["topic"],
                post_kind="image_text",
                dry_run=True,
            )
            assert plan["dry_run"] and not uploader.files and not writes
            result = await operator.write_post(
                "title",
                "body",
                images=[image],
                communities=["community1", "community2"],
                hashtags=["topic"],
                post_kind="image_text",
            )
            assert result["accepted"] and result["verified"]

    asyncio.run(check())
    assert len(writes) == 1 and len(uploader.files) == 1
    assert saved["link_tag"] == "27" and saved["topic_ids"] == "100,200"
    assert json.loads(saved["hashtags"]) == ["topic"]
    assert any(block.get("url", "").endswith("fixture.png") for block in json.loads(saved["text"]))


def test_missing_community_stops_before_upload_or_publish(image, store):
    requests = []
    uploader = Uploader()

    def handler(request):
        requests.append(request)
        result = (
            {"profile": {"heybox_id": "42"}}
            if request.url.path == "/account/restore_login"
            else {"search_result": []}
        )
        return httpx.Response(200, json={"status": "ok", "result": result})

    async def check():
        async with Operator(
            store,
            api=HeyboxAPI(transport=httpx.MockTransport(handler), interval=0),
            uploader=uploader,
        ) as operator:
            with pytest.raises(OperatorError, match="不存在"):
                await operator.write_post("title", "body", images=[image], communities=["missing"])

    asyncio.run(check())
    assert not uploader.files and all(request.method == "GET" for request in requests)


def test_video_and_explicit_cover_use_video_endpoint_and_readback(
    image, store, tmp_path, monkeypatch
):
    video = tmp_path / "fixture.mp4"
    video.write_bytes(b"fixture-video")

    async def metadata(path):
        return LocalMedia(video, "video/mp4", video.stat().st_size, 640, 360, 65.0)

    monkeypatch.setattr("xhh_operator.media.inspect_video", metadata)
    saved, writes = {}, []

    def handler(request):
        if request.url.path == "/account/restore_login":
            result = {"profile": {"heybox_id": "42"}}
        elif request.method == "POST":
            writes.append(request)
            saved.update(
                {
                    k: v[0]
                    for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()
                }
            )
            return httpx.Response(200, json={"status": "ok", "link_id": "900"})
        else:
            result = {
                "link": {
                    "linkid": "900",
                    "userid": "42",
                    **saved,
                    "text": json.dumps([{"type": "text", "text": saved["text"]}]),
                }
            }
        return httpx.Response(200, json={"status": "ok", "result": result})

    uploader = Uploader()

    async def check():
        async with Operator(
            store,
            api=HeyboxAPI(transport=httpx.MockTransport(handler), interval=0),
            uploader=uploader,
        ) as operator:
            preview = await operator.write_video("title", video, cover=image, dry_run=True)
            assert preview["dry_run"] and not writes and not uploader.files
            result = await operator.write_video("title", video, cover=image)
            assert result["verified"]

    asyncio.run(check())
    assert len(writes) == 1 and writes[0].url.path.endswith("video-link/post")
    assert saved["video_duration"] == "1:05" and saved["video_thumb"].endswith("fixture.png")


def test_unsupported_video_draft_is_rejected_before_upload_or_account_access(store):
    requests = []

    async def check():
        async with Operator(
            store,
            api=HeyboxAPI(transport=httpx.MockTransport(lambda r: requests.append(r)), interval=0),
        ) as operator:
            with pytest.raises(ValueError, match="不支持视频草稿"):
                await operator.write_video("fixture", "unused.mp4", draft=True)

    asyncio.run(check())
    assert requests == []


def test_image_comment_sends_imgs_and_verifies_returned_images(image, store):
    writes = []

    def handler(request):
        if request.url.path == "/account/restore_login":
            result = {"profile": {"heybox_id": "42"}}
        elif request.method == "POST":
            writes.append(request)
            assert parse_qs(request.content.decode())["imgs"] == [
                "https://media.max-c.com/fixture.png"
            ]
            result = {"commentid": "300"}
        else:
            result = {
                "comments": [
                    {
                        "comment": [
                            {
                                "commentid": "300",
                                "userid": "42",
                                "text": "body",
                                "imgs": [{"url": "https://media.max-c.com/fixture.png"}],
                            }
                        ]
                    }
                ]
            }
        return httpx.Response(200, json={"status": "ok", "result": result})

    async def check():
        async with Operator(
            store,
            api=HeyboxAPI(transport=httpx.MockTransport(handler), interval=0),
            uploader=Uploader(),
        ) as operator:
            result = await operator.comment("900", "body", images=[image])
            assert result["accepted"] and result["verified"]

    asyncio.run(check())
    assert len(writes) == 1


def test_reply_by_text_locates_child_comment_and_duplicate_text_is_rejected(store):
    thread = {
        "result": {
            "comments": [
                {
                    "comment": [
                        {"commentid": 10, "text": "root"},
                        {"commentid": 11, "text": "<p>target &amp; text</p>"},
                    ]
                }
            ]
        }
    }
    assert locate_comment(thread, "target & text") == {"reply_id": "11", "root_id": "10"}
    thread["result"]["comments"][0]["comment"].append({"commentid": 12, "text": "target & text"})
    with pytest.raises(OperatorError, match="重复"):
        locate_comment(thread, "target & text")
