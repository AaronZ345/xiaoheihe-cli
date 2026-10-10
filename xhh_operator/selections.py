"""社区与话题按准确名称解析，不静默选择搜索结果中的第一项。"""

from .errors import OperatorError, ProtocolError


def validate_selections(communities=(), hashtags=()):
    if isinstance(communities, str) or isinstance(hashtags, str):
        raise ValueError("社区和话题应为名称列表。")
    communities, hashtags = list(communities or ()), list(hashtags or ())
    if len(communities) > 2 or len(hashtags) > 5:
        raise ValueError("每篇内容最多选择 2 个社区、5 个话题标签。")
    for values in (communities, hashtags):
        if any(not isinstance(v, str) or not v.strip() for v in values) or len(set(values)) != len(
            values
        ):
            raise ValueError("社区和话题名称不能为空或重复。")
    return communities, hashtags


async def resolve_selections(api, communities=(), hashtags=()):
    communities, hashtags = validate_selections(communities, hashtags)
    topics, tags = [], []
    for kind, names, target in (("topic", communities, topics), ("hashtag", hashtags, tags)):
        for name in names:
            response = await api.request(
                "/bbs/app/api/post_editor/topic_selection/search",
                params={"q": name, "only_hashtag": "0"},
            )
            items = (response.get("result") or {}).get("search_result")
            if not isinstance(items, list):
                raise ProtocolError("社区和话题搜索响应格式已变化。")
            matches = [
                item
                for item in items
                if item.get("search_type") == kind
                and (item.get("name") or item.get("title")) == name
            ]
            if len(matches) != 1:
                raise OperatorError(
                    "社区或话题不存在，或同名结果不唯一；请核对准确名称。", "selection"
                )
            item = matches[0]
            if kind == "topic" and not item.get("topic_id"):
                raise ProtocolError("社区搜索结果缺少 ID。")
            if (
                kind == "hashtag"
                and item.get("is_act_hashtag")
                and any(t.get("is_act_hashtag") for t in tags)
            ):
                raise ValueError("每篇内容最多选择一个活动话题。")
            target.append(item)
    return {
        "topic_ids": ",".join(str(item["topic_id"]) for item in topics),
        "hashtags": [item["name"] for item in tags],
    }
