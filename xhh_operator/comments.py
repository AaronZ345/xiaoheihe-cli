"""根评论与楼中楼的有界完整读取，供 CLI、SDK 和正文定位共用。"""

import html
from html.parser import HTMLParser

from .errors import OperatorError, ProtocolError


async def read_thread(api, link_id, *, page_size=20, max_pages=100):
    if not 1 <= page_size <= 100 or not 1 <= max_pages <= 100:
        raise ValueError("评论分页范围无效。")
    groups, seen, offset = [], set(), 0
    first = None
    for page in range(max_pages):
        data = await api.request(
            "/bbs/app/link/tree",
            params={
                "link_id": link_id,
                "page": page + 1,
                "is_first": 1 if page == 0 else 0,
                "index": 1,
                "owner_only": 0,
                "offset": offset,
                "limit": page_size,
                "sort_filter": "oldest",
            },
        )
        if first is None:
            first = data
        result = data.get("result") or {}
        page_groups = result.get("comments") or []
        if not page_groups and result.get("has_more_floors"):
            raise ProtocolError("空评论页仍标记为有下一页，结果不完整。")
        for group in page_groups:
            items = group.get("comment") or []
            if not items:
                continue
            root = str(items[0].get("commentid", ""))
            if not root or root in seen:
                raise ProtocolError("评论分页未推进，停止读取；结果不完整。")
            seen.add(root)
            if int(items[0].get("child_num") or 0) > len(items) - 1:
                cursor = str(items[-1].get("commentid") or "")
                cursors = {cursor} if cursor else set()
                child_ids = {str(item.get("commentid")) for item in items[1:]}
                for reply_page in range(max_pages):
                    replies = (
                        await api.request(
                            "/bbs/app/comment/sub/comments",
                            params={
                                "link_id": link_id,
                                "root_comment_id": root,
                                "limit": page_size,
                                **({"lastval": cursor} if cursor else {}),
                            },
                        )
                    ).get("result") or {}
                    for child in replies.get("comments") or []:
                        child_id = str(child.get("commentid"))
                        if child_id not in child_ids:
                            items.append(child)
                            child_ids.add(child_id)
                    if not replies.get("has_more"):
                        break
                    returned_comments = replies.get("comments") or []
                    cursor = str(
                        replies.get("lastval")
                        or (returned_comments[-1].get("commentid") if returned_comments else "")
                        or ""
                    )
                    if not cursor or cursor in cursors:
                        raise ProtocolError("楼中楼游标未推进，停止读取；结果不完整。")
                    cursors.add(cursor)
                else:
                    raise ProtocolError("楼中楼超过分页上限，结果不完整。")
                if len(items) - 1 < int(items[0].get("child_num") or 0):
                    raise ProtocolError("楼中楼数量不足，结果不完整。")
            groups.append(group)
        offset += len(page_groups)
        if not result.get("has_more_floors"):
            first["result"]["comments"] = groups
            first["result"]["full_comments"] = True
            first["result"]["has_more_floors"] = False
            return first
    raise ProtocolError("评论超过分页上限，结果不完整。")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.parts.append(dict(attrs).get("alt", ""))
        elif tag in ("br", "p", "div"):
            self.parts.append(" ")


def plain_text(value):
    parser = _Text()
    parser.feed(value)
    return " ".join(html.unescape("".join(parser.parts)).split())


def locate_comment(thread, target):
    target = plain_text(target)
    if not target:
        raise ValueError("目标评论正文不能为空。")
    matches = []
    for group in (thread.get("result") or {}).get("comments") or []:
        items = group.get("comment") or []
        for item in items:
            if plain_text(str(item.get("text") or "")) == target:
                matches.append(
                    {"reply_id": str(item["commentid"]), "root_id": str(items[0]["commentid"])}
                )
    if len(matches) != 1:
        raise OperatorError(
            "目标评论不存在或正文重复；请使用明确的 reply-id 和 root-id。", "target"
        )
    return matches[0]
