"""
数据解析器：将 API JSON 响应转换为 Pydantic 模型

设计原则：
  - 所有公开方法返回 Pydantic 模型实例（非 raw dict）
  - 类型转换辅助函数提升为模块级，避免每次循环重新创建闭包
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, List, Optional, Tuple

from models import (
    Comment,
    CommentImage,
    CommentUser,
    CreatorArticleData,
    CreatorArticleList,
    CreatorListItem,
    CreatorStats,
    DailyTrend,
    Emoji,
    FlowSource,
    Medal,
    Post,
    PostAuthor,
    PostImage,
    PostStats,
)

logger = logging.getLogger(__name__)

# ==================== 类型转换工具 ====================


def _to_int(value: Any, default: int = 0) -> int:
    """安全转整数（API 字段类型不稳定）"""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _to_str(value: Any, default: str = "") -> str:
    """安全转字符串"""
    if value is None:
        return default
    return str(value)


# ==================== 解析器 ====================


class DataParser:
    """API 响应解析器"""

    EMOJI_PATTERN = re.compile(r"\[(cube_\S+?|heygirl_\S+?)\]")

    # ---------- 勋章 ----------

    @staticmethod
    def parse_medals(medals_data: list) -> List[Medal]:
        result: List[Medal] = []
        for item in medals_data or []:
            if not isinstance(item, dict):
                continue
            result.append(
                Medal(
                    medal_id=_to_int(item.get("medal_id")),
                    name=_to_str(item.get("name")),
                    description=_to_str(item.get("description")),
                    img_url=_to_str(item.get("img_url")),
                    level=_to_int(item.get("level")),
                    achieved=_to_int(item.get("achieved")),
                    wear=_to_int(item.get("wear")),
                )
            )
        return result

    @staticmethod
    def find_wearing_medal(medals: List[Medal]) -> Optional[Medal]:
        for m in medals:
            if m.wear == 1:
                return m
        return None

    # ---------- 用户 ----------

    @staticmethod
    def parse_user(user_data: dict) -> CommentUser:
        if not user_data or not isinstance(user_data, dict):
            return CommentUser()

        level_info = user_data.get("level_info", {})
        medals = DataParser.parse_medals(user_data.get("medals", []))

        return CommentUser(
            user_id=_to_str(user_data.get("userid")),
            name=user_data.get("username", "匿名用户"),
            level=f"Lv.{level_info.get('level', 0)}" if level_info.get("status") == 1 else "",
            avatar_url=user_data.get("avatar") or user_data.get("avartar", ""),
            medals=medals,
            wearing_medal=DataParser.find_wearing_medal(medals),
        )

    # ---------- 表情 ----------

    @staticmethod
    def build_emoji_map(emoji_list: list) -> dict:
        emoji_map: dict[str, dict] = {}
        for group in emoji_list or []:
            if not isinstance(group, dict):
                continue
            group_name = group.get("group_name", "")
            for emoji in group.get("emojis", []):
                if not isinstance(emoji, dict):
                    continue
                code = emoji.get("code", "")
                if code:
                    emoji_map[f"{group_name}_{code}"] = {
                        "sprite_url": emoji.get("img", ""),
                        "class": emoji.get("class", ""),
                    }
        return emoji_map

    @staticmethod
    def extract_emojis_from_text(text: str, emoji_map: dict) -> List[Emoji]:
        emojis: List[Emoji] = []
        if not text or not emoji_map:
            return emojis

        seen: set[str] = set()
        for match in DataParser.EMOJI_PATTERN.finditer(text):
            name = match.group(1)
            if name in seen:
                continue
            seen.add(name)

            info = emoji_map.get(name, {})
            sprite_url = info.get("sprite_url", "")
            cls = info.get("class", "")
            id_match = re.search(r"_(\d+)$", cls)
            emoji_id = id_match.group(1) if id_match else ""

            emojis.append(Emoji(name=name, emoji_id=emoji_id, sprite_url=sprite_url))

        return emojis

    # ---------- 时间 ----------

    @staticmethod
    def format_time(timestamp: int) -> str:
        """Unix 时间戳 → 可读文本"""
        if not timestamp:
            return ""

        now = int(time.time())
        diff = now - timestamp

        if diff < 60:
            return "刚刚"
        elif diff < 3600:
            return f"{diff // 60}分钟前"
        elif diff < 86400:
            return f"{diff // 3600}小时前"
        elif diff < 2592000:
            return f"{diff // 86400}天前"
        else:
            return time.strftime("%Y-%m-%d", time.localtime(timestamp))

    # ---------- 评论 ----------

    @staticmethod
    def parse_comment(comment_data: dict, emoji_map: dict) -> Optional[Comment]:
        if not comment_data or not isinstance(comment_data, dict):
            return None

        try:
            author = DataParser.parse_user(comment_data.get("user", {}))
            content = comment_data.get("text", "")
            emojis = DataParser.extract_emojis_from_text(content, emoji_map)

            reply_to = None
            ru = comment_data.get("replyuser", {})
            if ru and isinstance(ru, dict):
                reply_to = DataParser.parse_user(ru)

            images: List[CommentImage] = []
            for img_item in comment_data.get("imgs", []) or []:
                if isinstance(img_item, dict):
                    images.append(
                        CommentImage(
                            url=img_item.get("url", ""),
                            thumb=img_item.get("thumb"),
                            width=img_item.get("width"),
                            height=img_item.get("height"),
                        )
                    )

            return Comment(
                comment_id=_to_str(comment_data.get("commentid")),
                author=author,
                content=content,
                emojis=emojis,
                time=DataParser.format_time(_to_int(comment_data.get("create_at"))),
                location=_to_str(comment_data.get("ip_location")),
                likes=_to_int(comment_data.get("up")),
                floor_num=_to_int(comment_data.get("floor_num")),
                reply_to=reply_to,
                is_top=_to_int(comment_data.get("is_top")),
                has_more=_to_int(comment_data.get("has_more")),
                child_num=_to_int(comment_data.get("child_num")),
                images=images,
            )
        except Exception as e:
            logger.warning("解析评论失败: %s", e)
            return None

    # ---------- 帖子元数据 ----------

    @staticmethod
    def parse_comments_response(
        raw_data: dict, emoji_map: Optional[dict] = None
    ) -> Tuple[dict, List[Comment]]:
        """解析 /bbs/app/link/tree 响应 → (帖子元数据, 评论列表)"""
        if emoji_map is None:
            emoji_map = {}

        result = raw_data.get("result", {})
        post_meta = DataParser._parse_link_meta(result.get("link", {}))

        # 合并全部评论（full 模式）
        all_comments = result.get("_all_comments", [])
        if all_comments:
            comments_list = [
                c for cd in all_comments if (c := DataParser.parse_comment(cd, emoji_map))
            ]
            return post_meta, comments_list

        # 正常分页模式
        comments_list: List[Comment] = []
        for group in result.get("comments", []):
            arr = group.get("comment", [])
            if not arr or not isinstance(arr[0], dict):
                continue

            children: List[Comment] = []
            for child in arr[1:]:
                if isinstance(child, dict) and child.get("replyid"):
                    c = DataParser.parse_comment(child, emoji_map)
                    if c:
                        children.append(c)

            main = DataParser.parse_comment(arr[0], emoji_map)
            if main:
                main.child_comments = children
                comments_list.append(main)

        return post_meta, comments_list

    @staticmethod
    def _parse_link_meta(link_data: dict) -> dict:
        """从 result.link 解析帖子元数据"""
        if not link_data or not isinstance(link_data, dict):
            logger.warning("_parse_link_meta 收到空或非dict数据: type=%s", type(link_data))
            return {}

        create_at = link_data.get("create_at", 0)
        user_data = link_data.get("user", {})
        topics = link_data.get("topics", [])
        text_data = link_data.get("text", "")

        # 调试：记录原始 link 数据的 keys
        logger.debug(
            "link_data keys=%s, title='%s', user_keys=%s",
            list(link_data.keys())[:15],
            str(link_data.get("title", ""))[:50],
            list(user_data.keys())[:10] if isinstance(user_data, dict) else user_data,
        )

        content_text = ""
        images: List[dict] = []

        if isinstance(text_data, str) and text_data.startswith("["):
            try:
                items = json.loads(text_data)
                for item in items:
                    t = item.get("type")
                    if t == "text":
                        content_text += item.get("text", "")
                    elif t == "img":
                        images.append({"url": item.get("url", "")})
            except json.JSONDecodeError:
                content_text = text_data
        else:
            content_text = text_data

        return {
            "title": link_data.get("title", ""),
            "description": link_data.get("description", ""),
            "content": content_text,
            "create_at": create_at,
            "time": DataParser.format_time(create_at),
            "click": link_data.get("click", 0),
            "up": link_data.get("link_award_num", 0),
            "favour_count": link_data.get("favour_count", 0),
            "comment_num": link_data.get("comment_num", 0),
            "forward_num": link_data.get("forward_num", 0),
            "ip_location": link_data.get("ip_location", ""),
            "author_name": user_data.get("username", ""),
            "author_avatar": user_data.get("avatar", ""),
            "author_userid": _to_str(user_data.get("userid")),
            "author_medals": DataParser.parse_medals(user_data.get("medals", [])),
            "tags": [t.get("name", "") for t in topics if t.get("name")],
            "images": images,
        }

    @staticmethod
    def parse_post_from_comments(
        link_id: str,
        url: str,
        comments: List[Comment],
        post_meta: Optional[dict] = None,
    ) -> Post:
        meta = post_meta or {}

        author = PostAuthor(
            name=meta.get("author_name", "未知用户"),
            avatar_url=meta.get("author_avatar"),
            user_id=meta.get("author_userid"),
            medals=meta.get("author_medals", []),
            wearing_medal=DataParser.find_wearing_medal(meta.get("author_medals", [])),
        )

        stats = PostStats(
            views=_to_int(meta.get("click")),
            likes=_to_int(meta.get("up")),
            favorites=_to_int(meta.get("favour_count")),
            comments=_to_int(meta.get("comment_num"), len(comments)),
        )

        images = [PostImage(url=img["url"]) for img in meta.get("images", [])]

        return Post(
            post_id=link_id,
            url=url,
            title=_to_str(meta.get("title")),
            content=_to_str(meta.get("content")),
            description=_to_str(meta.get("description")),
            author=author,
            tags=meta.get("tags", []),
            images=images,
            stats=stats,
            time=_to_str(meta.get("time")),
            create_at=meta.get("create_at"),
            location=_to_str(meta.get("ip_location")),
            comments=comments,
        )

    # ---------- 创作者数据 ----------

    @staticmethod
    def parse_creator_response(raw_data: dict) -> CreatorStats:
        result = raw_data.get("result", {})

        article_raw = result.get("article", {})
        flow_sources = [
            FlowSource(text=_to_str(fs.get("text")), value=_to_int(fs.get("value")))
            for fs in article_raw.get("flow_source_info", []) or []
            if isinstance(fs, dict)
        ]

        article = CreatorArticleData(
            link_id=_to_int(article_raw.get("link_id")),
            title=_to_str(article_raw.get("title")),
            click=_to_int(article_raw.get("click")),
            exposure_count=_to_int(article_raw.get("exposure_count")),
            raw_view_time_count=_to_int(article_raw.get("raw_view_time_count")),
            view_time_count=_to_int(article_raw.get("view_time_count")),
            avg_time=_to_int(article_raw.get("avg_time")),
            new_follow=_to_int(article_raw.get("new_follow")),
            share_url=_to_str(article_raw.get("share_url")),
            has_video=_to_int(article_raw.get("has_video")),
            create_at=_to_int(article_raw.get("create_at")),
            article_desc=_to_str(article_raw.get("article_desc")),
            imgs=article_raw.get("imgs") or [],
            thumbs=article_raw.get("thumbs") or [],
            flow_source_info=flow_sources,
            statistic_data=article_raw.get("statistic_data") or {},
        )

        trends = [
            DailyTrend(
                timestamp=_to_int(td.get("timestamp")),
                click=_to_int(td.get("click")),
                comment=_to_int(td.get("comment")),
                share=_to_int(td.get("share")),
                favour=_to_int(td.get("favour")),
                award=_to_int(td.get("award")),
                battery=_to_int(td.get("battery")),
                follow=_to_int(td.get("follow")),
                new_follow=_to_int(td.get("new_follow")),
                lost_follow=_to_int(td.get("lost_follow")),
                avg_time=_to_int(td.get("avg_time")),
            )
            for td in result.get("data_trends", []) or []
            if isinstance(td, dict)
        ]

        return CreatorStats(article=article, data_trends=trends)

    # ---------- 文章列表 ----------

    @staticmethod
    def parse_article_list_response(raw_data: dict) -> CreatorArticleList:
        result = raw_data.get("result", {})

        articles: List[CreatorListItem] = []
        for item in result.get("articles", []) or []:
            if not isinstance(item, dict):
                continue

            thumbs_val = item.get("thumbs", 0)
            thumbs_count = len(thumbs_val) if isinstance(thumbs_val, list) else _to_int(thumbs_val)

            articles.append(
                CreatorListItem(
                    link_id=_to_int(item.get("link_id")),
                    title=_to_str(item.get("title")),
                    link_type=item.get("link_type"),
                    click=_to_int(item.get("click")),
                    thumbs=thumbs_count,
                    comment=_to_int(item.get("comment")),
                    create_at=_to_int(item.get("create_at")),
                    raw_view_time_count=_to_int(item.get("raw_view_time_count")),
                    new_follow=_to_int(item.get("new_follow")),
                    share_url=_to_str(item.get("share_url")),
                    has_video=_to_int(item.get("has_video")),
                    link_tag=item.get("link_tag"),
                    article_desc=_to_str(item.get("article_desc")),
                    award=_to_int(item.get("award")),
                    imgs=item.get("imgs") or [],
                )
            )

        sort_filters = _parse_filter_items(result.get("sort_filters", []))
        state_filters = _parse_filter_items(result.get("state_filters", []))

        return CreatorArticleList(
            articles=articles,
            total=len(articles),
            sort_filters=sort_filters,
            state_filters=state_filters,
        )


def _parse_filter_items(raw: list) -> List[str]:
    """统一处理 sort / state filter 列表"""
    out: List[str] = []
    for item in raw or []:
        if isinstance(item, dict):
            val = item.get("name") or item.get("value")
            if val is not None:
                out.append(str(val))
        elif isinstance(item, str):
            out.append(item)
    return out
