import asyncio
import json
import re
from decimal import Decimal, InvalidOperation

from .auth import verify
from .errors import AuthError, OperatorError, ProtocolError
from .http import HeyboxAPI
from .session import SessionStore
from .signing import workshop_params


def identifier(value: str) -> str:
    value = str(value).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise ValueError("ID 只能包含字母、数字、下划线或短横线。")
    return value


def link_id(record) -> str | None:
    if not isinstance(record, dict):
        return None
    for key in ("link_id", "linkid"):
        if record.get(key):
            return str(record[key])
    for key in ("link", "comment", "data", "result"):
        if found := link_id(record.get(key)):
            return found
    return None


def review_record(value):
    if value in (None, {}, []):
        return None
    if not isinstance(value, dict):
        raise ProtocolError("本人评测的响应格式已变化。")
    if value.get("exists") is False:
        return None
    if link_id(value):
        return value
    raise ProtocolError("本人评测返回了非空数据，但缺少评测 ID。")


def find_field(record, names):
    if not isinstance(record, dict):
        return None
    for name in names:
        if record.get(name) is not None:
            return record[name]
    for key in ("link", "comment", "data"):
        if (value := find_field(record.get(key), names)) is not None:
            return value
    return None


def encode_text(content: str) -> str:
    if not content.strip():
        raise ValueError("正文不能为空。")
    return json.dumps(
        [{"type": "text", "text": content}], ensure_ascii=False, separators=(",", ":")
    )


def integer_score(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("请指定 1 到 5 的整数评分。") from None
    if not number.is_finite() or number != number.to_integral_value() or not 1 <= number <= 5:
        raise ValueError("请指定 1 到 5 的整数评分。")
    return int(number)


def present_review(data):
    result = data.get("result") or {}
    record = review_record(result)
    if not record:
        return {"exists": False, "appid": result.get("appid"), "name": result.get("name")}
    serialized = find_field(record, ("text",))
    try:
        blocks = json.loads(serialized)
    except (ValueError, TypeError):
        raise ProtocolError("短评原始正文格式已变化。") from None
    if not isinstance(blocks, list):
        raise ProtocolError("短评原始正文不是文本块数组。")
    return {
        "exists": True,
        "appid": result.get("appid") or find_field(record, ("appid",)),
        "name": result.get("name"),
        "review_id": link_id(record),
        "personal_score": find_field(record, ("impression_score", "score", "user_score")),
        "text": "\n".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ),
        "blocks": blocks,
        "created_at": find_field(record, ("create_at",)),
        "modified_at": find_field(record, ("modify_at",)),
    }


class Operator:
    def __init__(
        self, store: SessionStore | None = None, *, api: HeyboxAPI | None = None, uploader=None
    ):
        self.store = store or SessionStore()
        self.session = self.store.load()
        self.api = api or HeyboxAPI((self.session or {}).get("cookies", []))
        self._verified = False
        self._uploader = uploader

    async def __aenter__(self):
        await self.api.__aenter__()
        return self

    async def __aexit__(self, *args):
        await self.api.__aexit__(*args)

    async def require_account(self):
        if not self.session:
            raise AuthError("尚未登录，请先执行 xiaoheihe login。")
        if not self._verified:
            await verify(self.api, self.session["user_id"])
            self._verified = True
        return self.session["user_id"]

    async def games(self, *, offset=0, limit=20, query=""):
        user = await self.require_account()
        return await self.api.request(
            "/account/game_list/",
            params={
                "userid": user,
                "offset": offset,
                "limit": limit,
                "sort": "time",
                **({"q": query} if query else {}),
            },
        )

    async def reviews(self, *, platform="steam", offset=0, limit=20, summary=False):
        user = await self.require_account()
        data = await self.api.request(
            "/account/my_comment_list",
            params={"userid": user, "platform": platform, "offset": offset, "limit": limit},
        )
        result = data.get("result") or {}
        games = result.get("game_list")
        if not isinstance(games, list):
            raise ProtocolError("个人评测列表缺少 game_list。")
        items = []
        for game in games:
            appid = str(game.get("appid") or game.get("steam_appid") or "")
            if not appid:
                raise ProtocolError("个人评测列表中的游戏缺少 ID。")
            if summary:
                # 'score' here is the community aggregate, not the account's rating.
                items.append(
                    {
                        "appid": appid,
                        "name": game.get("name"),
                        "personal_score": game.get("comment_score"),
                        "comment_created_at": game.get("comment_create_at"),
                    }
                )
            else:
                items.append(present_review(await self.review(appid)))
        return {
            "items": items,
            "platform": platform,
            "offset": offset,
            "limit": limit,
            "next_offset": offset + len(games) if games else None,
            "has_more": result.get("has_more"),
            "summary_only": summary,
        }

    async def review(self, appid):
        appid = identifier(appid)
        user = await self.require_account()
        data = await self.api.request("/bbs/app/link/game/comment/mine", params={"appid": appid})
        record = review_record(data.get("result"))
        if record:
            body = record.get("link") or record
            if not isinstance(body, dict):
                raise ProtocolError("本人评测数据格式已变化。")
            owner = body.get("userid") or (body.get("user") or {}).get("userid")
            for candidate in (record.get("appid"), body.get("appid")):
                if candidate is not None and str(candidate) != appid:
                    raise ProtocolError("本人评测的游戏 ID 与请求不一致。")
            if owner is not None and str(owner) != user:
                raise ProtocolError("本人评测作者与已登录账号不一致。")
            if owner is None or find_field(record, ("text",)) is None:
                review_id = link_id(record)
                full = ((await self.post(review_id, limit=1)).get("result") or {}).get("link") or {}
                if str(full.get("userid")) != user or link_id(full) != review_id:
                    raise ProtocolError("完整短评的作者或 ID 与本人记录不一致。")
                if full.get("appid") is not None and str(full["appid"]) != appid:
                    raise ProtocolError("完整短评的游戏 ID 与请求不一致。")
                if not isinstance(full.get("text"), str):
                    raise ProtocolError("完整短评缺少原始正文。")
                record["link"] = {**(record.get("link") or {}), **full}
        return data

    async def write_review(self, appid, *, score=None, content=None, edit=False, dry_run=False):
        appid = identifier(appid)
        if score is not None:
            score = integer_score(score)
        await self.require_account()
        old = review_record((await self.review(appid)).get("result"))
        old_id = link_id(old)
        if edit and not old_id:
            raise OperatorError("这款游戏没有本人的短评，请使用 review create。", "not_found")
        if not edit and old_id:
            raise OperatorError("这款游戏已经有本人的短评，请使用 review edit。", "conflict")
        if score is None:
            score = find_field(old, ("impression_score", "score", "user_score"))
        if content is None:
            text = find_field(old, ("text",))
            if not isinstance(text, str):
                raise ProtocolError("无法保留原正文，请同时指定 --text 或 --file。")
        else:
            text = encode_text(content)
        score = integer_score(score)
        form = {
            "appid": appid,
            "score": str(score),
            "text": text,
            "game_impression_post_type": "2",
            "link_tag": str(find_field(old, ("link_tag",)) or 3),
        }
        if edit:
            form.update({"edit": "1", "link_id": old_id})
        if dry_run:
            return {
                "dry_run": True,
                "operation": "review.edit" if edit else "review.create",
                "form": form,
            }
        receipt = await self.api.request("/bbs/app/api/link/post", form=form, extra=workshop_params)
        result = {
            "accepted": True,
            "operation": "review.edit" if edit else "review.create",
            "link_id": link_id(receipt) or old_id,
        }
        try:
            record = review_record((await self.review(appid)).get("result"))
            score_read = find_field(record, ("impression_score", "score", "user_score"))
            text_read = find_field(record, ("text",))
            id_matches = bool(link_id(record)) and (
                not result["link_id"] or link_id(record) == result["link_id"]
            )
            try:
                same_text = json.loads(text_read) == json.loads(text)
            except (ValueError, TypeError):
                same_text = False
            try:
                same_score = integer_score(score_read) == score
            except ValueError:
                same_score = False
            result["verified"] = bool(id_matches and same_score and same_text)
            result["readback"] = record
        except OperatorError as exc:
            result.update({"verified": False, "readback_error": exc.code})
        return result

    async def delete_review(self, appid, *, dry_run=False):
        record = review_record((await self.review(appid)).get("result"))
        current_id = link_id(record)
        if not current_id:
            raise OperatorError("这款游戏没有本人的短评。", "not_found")
        if dry_run:
            return {
                "dry_run": True,
                "operation": "review.delete",
                "link_id": current_id,
                "appid": appid,
            }
        await self.api.request(
            "/bbs/app/link/delete", form={"link_id": current_id}, extra=workshop_params
        )
        result = {"accepted": True, "operation": "review.delete", "link_id": current_id}
        try:
            result["verified"] = review_record((await self.review(appid)).get("result")) is None
        except OperatorError as exc:
            result.update({"verified": False, "readback_error": exc.code})
        return result

    async def search(self, keyword, *, kind="post", offset=0, limit=20):
        if not keyword.strip():
            raise ValueError("搜索词不能为空。")
        if kind not in ("post", "user", "topic", "game"):
            raise ValueError("搜索类型无效。")
        if kind == "game":
            path, params = "/game/search/", {"q": keyword}
        elif kind == "topic":
            path, params = "/bbs/app/api/search/topic", {"q": keyword}
        else:
            path, params = (
                "/bbs/app/api/general/search/v1",
                {"q": keyword, "search_type": "link" if kind == "post" else "user"},
            )
        return await self.api.request(path, params={**params, "offset": offset, "limit": limit})

    async def post(self, postid, *, offset=0, limit=20, sort="hot"):
        return await self.api.request(
            "/bbs/app/link/tree",
            params={
                "link_id": identifier(postid),
                "page": offset // limit + 1,
                "is_first": 1 if offset == 0 else 0,
                "index": 1,
                "owner_only": 0,
                "offset": offset,
                "limit": limit,
                "sort_filter": sort,
            },
        )

    async def posts(self, *, offset=0, limit=20):
        user = await self.require_account()
        return await self.api.request(
            "/bbs/app/profile/user/link/list_v2",
            params={"userid": user, "offset": offset, "limit": limit},
        )

    async def edit_info(self, postid):
        await self.require_account()
        return await self.api.request(
            "/bbs/app/link/edit/info", params={"link_id": identifier(postid)}
        )

    def uploader(self):
        from .media import MediaUploader

        if self._uploader is None:
            self._uploader = MediaUploader(self.api)
        return self._uploader

    async def upload_media(self, path, *, kind="image", dry_run=False):
        from .media import inspect_image, inspect_video

        if kind not in ("image", "video"):
            raise ValueError("媒体类型无效。")
        media = inspect_image(path) if kind == "image" else await inspect_video(path)
        await self.require_account()
        if dry_run:
            return {"dry_run": True, "operation": "media.upload", "media": media.preview()}
        return await self.uploader().upload(media)

    async def feed(self, *, offset=0, limit=20):
        return await self.api.request(
            "/bbs/app/feeds", params={"offset": offset, "limit": limit, "pull": "0", "dw": 604}
        )

    async def profile(self, *, limit=10):
        user = await self.require_account()
        result = (await self.posts(limit=limit)).get("result") or {}
        profile = result.get("user")
        if not isinstance(profile, dict) or str(profile.get("userid")) != user:
            raise ProtocolError("本人主页响应缺少匹配的身份。")
        return {"user": profile, "posts": result.get("post_links") or []}

    async def write_post(
        self,
        title,
        content,
        *,
        tag=11,
        draft=True,
        postid=None,
        dry_run=False,
        readback_attempts=4,
        images=(),
        communities=(),
        hashtags=(),
        post_kind="article",
        base_dir=None,
    ):
        from .article import prepare_article
        from .media import inspect_image
        from .selections import resolve_selections, validate_selections

        if not isinstance(readback_attempts, int) or not 1 <= readback_attempts <= 4:
            raise ValueError("读回次数需要为 1 到 4。")
        if (
            post_kind not in ("article", "image_text")
            or not title.strip()
            or not (content.strip() or images)
        ):
            raise ValueError("发布类型、标题或正文无效。")
        validate_selections(communities, hashtags)
        template = (
            prepare_article(content, images, base_dir=base_dir) if post_kind == "article" else None
        )
        media = template.images if template else [inspect_image(path) for path in images]
        await self.require_account()
        if postid:
            postid = identifier(postid)
            await self.require_own_post(postid)
        selection = await resolve_selections(self.api, communities, hashtags)
        if post_kind == "image_text" and not selection["topic_ids"]:
            selection["topic_ids"] = "58144"
        urls = [f"pending://image/{i}" for i in range(len(media))]
        if not dry_run:
            urls = [(await self.uploader().upload(item))["url"] for item in media]
        if template:
            blocks = [{"type": "html", "text": template.render(urls)}] + [
                {"type": "img", "url": url, "width": item.width, "height": item.height}
                for item, url in zip(media, urls)
            ]
        else:
            blocks = ([{"type": "text", "text": content}] if content else []) + [
                {"type": "img", "url": url, "width": item.width, "height": item.height}
                for item, url in zip(media, urls)
            ]
        form = {
            "title": title,
            "text": json.dumps(blocks, ensure_ascii=False),
            "post_type": "1",
            "link_tag": str(
                (21 if selection["topic_ids"] == "58144" else tag)
                if post_kind == "article"
                else (28 if selection["topic_ids"] == "58144" else 27)
            ),
            "draft": "1" if draft else "0",
            "view_limit": "1",
            "original": "1",
            "words_count": str(len(content)),
        }
        if selection["topic_ids"]:
            form["topic_ids"] = selection["topic_ids"]
        if selection["hashtags"]:
            form["hashtags"] = json.dumps(selection["hashtags"], ensure_ascii=False)
        if postid:
            form.update({"edit": "1", "link_id": postid})
        if dry_run:
            return {
                "dry_run": True,
                "operation": "post.edit" if postid else "post.create",
                "form": form,
                "uploads": [item.preview() for item in media],
            }
        return await self._submit_post(
            form,
            blocks,
            draft=draft,
            postid=postid,
            readback_attempts=readback_attempts,
            verify_topics=bool(communities),
        )

    async def write_video(
        self,
        title,
        path,
        *,
        content="",
        cover=None,
        draft=False,
        communities=(),
        hashtags=(),
        dry_run=False,
    ):
        from .media import inspect_image, inspect_video
        from .selections import resolve_selections, validate_selections

        if not title.strip():
            raise ValueError("视频标题不能为空。")
        if draft and not dry_run:
            raise ValueError("小黑盒不支持视频草稿；请先预览，再明确正式发布。")
        validate_selections(communities, hashtags)
        video = await inspect_video(path)
        image = inspect_image(cover) if cover else None
        await self.require_account()
        selection = await resolve_selections(self.api, communities, hashtags)
        media = (
            {"url": "pending://video", "thumb": None}
            if dry_run
            else await self.uploader().upload(video)
        )
        thumbnail = "pending://cover" if image else media.get("thumb")
        if image and not dry_run:
            thumbnail = (await self.uploader().upload(image))["url"]
        if not thumbnail and not dry_run:
            raise ProtocolError("视频上传没有返回封面，请显式提供封面图片。")
        seconds = max(1, round(video.duration))
        duration = f"{seconds // 60}:{seconds % 60:02d}"
        blocks = [{"type": "text", "text": content}]
        form = {
            "title": title,
            "text": content,
            "desc": content,
            "link_tag": "1",
            "post_type": "4",
            "original": "1",
            "view_limit": "1",
            "draft": "1" if draft else "0",
            "video_url": media["url"],
            "video_thumb": thumbnail or "pending://automatic-cover",
            "video_duration": duration,
            "video_duration_desc": duration,
            "video_cos_provider": "tencent",
        }
        if selection["topic_ids"]:
            form["topic_ids"] = selection["topic_ids"]
        if selection["hashtags"]:
            form["hashtags"] = json.dumps(selection["hashtags"], ensure_ascii=False)
        if dry_run:
            return {
                "dry_run": True,
                "operation": "video.create",
                "form": form,
                "uploads": [m.preview() for m in (video, image) if m],
            }
        return await self._submit_post(
            form, blocks, draft=draft, endpoint="/bbs/app/api/video-link/post"
        )

    async def _submit_post(
        self,
        form,
        blocks,
        *,
        draft,
        postid=None,
        readback_attempts=4,
        endpoint="/bbs/app/api/link/post",
        verify_topics=True,
    ):
        from .article import semantic_html
        from .media import same_asset

        title = form["title"]
        receipt = await self.api.request(endpoint, form=form, extra=workshop_params)
        result = {
            "accepted": True,
            "is_draft": draft,
            "link_id": link_id(receipt) or postid,
            "verified": False,
        }
        if result["link_id"]:
            try:
                for attempt in range(readback_attempts):
                    if attempt:
                        await asyncio.sleep(2**attempt)
                    record = (
                        await self.edit_info(result["link_id"])
                        if draft
                        else await self.post(result["link_id"])
                    )
                    returned = record.get("result") or {}
                    returned_link = returned.get("link") or {}
                    try:
                        returned_blocks = json.loads(returned_link.get("text", ""))
                        expected_body = [
                            dict(block) for block in blocks if block.get("type") != "img"
                        ]
                        actual_body = [
                            dict(block) for block in returned_blocks if block.get("type") != "img"
                        ]
                        expected_images = [
                            block["url"] for block in blocks if block.get("type") == "img"
                        ]
                        actual_images = [
                            block.get("url")
                            for block in returned_blocks
                            if block.get("type") == "img"
                        ]
                        actual_images.extend(
                            image.get("url")
                            for image in (returned.get("images") or [])
                            if isinstance(image, dict)
                        )
                        for values in (actual_body, expected_body):
                            for block in values:
                                if block.get("type") == "html":
                                    block["text"] = semantic_html(block["text"], expected_images)
                        same_blocks = actual_body == expected_body and all(
                            any(same_asset(expected, actual) for actual in actual_images)
                            for expected in expected_images
                        )
                        if form.get("video_url"):
                            same_blocks = bool(
                                actual_body and actual_body[0].get("text") == form["text"]
                            )
                    except (ValueError, TypeError):
                        same_blocks = bool(
                            form.get("video_url") and returned_link.get("text") == form["text"]
                        )
                    result["verified"] = bool(
                        same_blocks
                        and returned_link.get("title") == title
                        and link_id(returned_link) == str(result["link_id"])
                        and str(returned_link.get("userid")) == self.session["user_id"]
                    )
                    if result["verified"] and form.get("topic_ids") and verify_topics:
                        implicit_dynamic = form["topic_ids"] == "58144" and str(
                            returned_link.get("link_tag")
                        ) in ("28", "21")
                        result["verified"] = implicit_dynamic or set(
                            form["topic_ids"].split(",")
                        ).issubset(
                            {
                                str(t.get("topic_id"))
                                for t in (returned_link.get("topics") or [])
                                if isinstance(t, dict)
                            }
                        )
                    if result["verified"] and form.get("hashtags"):
                        result["verified"] = set(json.loads(form["hashtags"])).issubset(
                            {
                                t.get("name") if isinstance(t, dict) else t
                                for t in (returned_link.get("hashtags") or [])
                            }
                        )
                    if result["verified"] and form.get("video_url"):
                        info = returned_link.get("video_info") or {}
                        result["verified"] = (
                            returned_link.get("video_url") or info.get("url")
                        ) == form["video_url"] and (
                            returned_link.get("video_thumb") or info.get("thumb")
                        ) == form["video_thumb"]
                    result["readback"] = record
                    if result["verified"]:
                        break
            except OperatorError as exc:
                result["readback_error"] = exc.code
        return result

    async def require_own_post(self, postid):
        user = await self.require_account()
        result = (await self.edit_info(postid)).get("result") or {}
        record = result.get("link") or result
        author = record.get("user") or record.get("author") or {}
        owner = author.get("userid") or author.get("heybox_id") or record.get("userid")
        if str(owner) != user:
            raise OperatorError(
                "只能修改或删除当前账号自己的帖子；无法确认作者时停止操作。", "ownership"
            )

    async def delete_post(self, postid, *, dry_run=False, draft=False):
        postid = identifier(postid)
        await self.require_own_post(postid)
        if dry_run:
            return {"dry_run": True, "operation": "post.delete", "link_id": postid}
        await self.api.request(
            "/bbs/app/link/delete",
            params={"draft": "1"} if draft else None,
            form={"link_id": postid},
            extra=workshop_params,
        )
        return {"accepted": True, "operation": "post.delete", "link_id": postid, "verified": False}

    async def comment(
        self,
        postid,
        content,
        *,
        reply_id="-1",
        root_id="-1",
        target_text=None,
        images=(),
        dry_run=False,
        max_pages=100,
    ):
        from .media import inspect_image, same_asset

        media = [inspect_image(path) for path in images]
        await self.require_account()
        if not content.strip() and not media:
            raise ValueError("评论不能为空。")
        if target_text is not None:
            if reply_id != "-1" or root_id != "-1":
                raise ValueError("按正文定位和显式评论 ID 不能同时使用。")
            from .comments import locate_comment, read_thread

            target = locate_comment(
                await read_thread(self.api, identifier(postid), max_pages=max_pages), target_text
            )
            reply_id, root_id = target["reply_id"], target["root_id"]
        elif (reply_id == "-1") != (root_id == "-1"):
            raise ValueError("回复需要同时提供 reply-id 和 root-id。")
        form = {
            "link_id": identifier(postid),
            "text": content,
            "root_id": identifier(root_id),
            "reply_id": identifier(reply_id),
            "is_cy": "0",
        }
        if media:
            urls = (
                [f"pending://image/{i}" for i in range(len(media))]
                if dry_run
                else [(await self.uploader().upload(item))["url"] for item in media]
            )
            form["imgs"] = ";".join(urls)
        if dry_run:
            return {
                "dry_run": True,
                "uploads": [item.preview() for item in media],
                "operation": "comment.reply" if reply_id != "-1" else "comment.create",
                "form": form,
            }
        receipt = await self.api.request(
            "/bbs/app/comment/create", form=form, extra=workshop_params
        )
        result = {
            "accepted": True,
            "comment_id": receipt.get("commentid")
            or (receipt.get("result") or {}).get("commentid"),
            "result": receipt.get("result"),
            "verified": False,
        }
        if result["comment_id"]:
            try:
                if reply_id == "-1":
                    readback = await self.post(postid, sort="latest")
                else:
                    readback = await self.api.request(
                        "/bbs/app/comment/sub/comments",
                        params={"link_id": postid, "root_comment_id": root_id, "limit": 20},
                    )

                def matches(value):
                    if isinstance(value, dict):
                        if str(value.get("commentid")) == str(result["comment_id"]):
                            images = value.get("imgs") or value.get("images") or []
                            if isinstance(images, str):
                                returned_urls = set(images.split(";"))
                            else:
                                returned_urls = {
                                    item.get("url") if isinstance(item, dict) else item
                                    for item in images
                                }
                            return (
                                value.get("text") == content
                                and str(value.get("userid")) == self.session["user_id"]
                                and (
                                    not form.get("imgs")
                                    or all(
                                        any(
                                            same_asset(expected, actual) for actual in returned_urls
                                        )
                                        for expected in form["imgs"].split(";")
                                    )
                                )
                            )
                        return any(matches(v) for v in value.values())
                    if isinstance(value, list):
                        return any(matches(v) for v in value)
                    return False

                result["verified"] = matches(readback)
            except OperatorError as exc:
                result["readback_error"] = exc.code
        return result
