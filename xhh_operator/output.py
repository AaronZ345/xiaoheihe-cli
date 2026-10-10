import csv
import io
import json

from .session import safe_result


def query_rows(result):
    if isinstance(result, list):
        return result
    if not isinstance(result, dict):
        return [result]
    data = result.get("result")
    data = data if isinstance(data, dict) else result
    for key in (
        "items",
        "game_list",
        "games",
        "topics",
        "users",
        "links",
        "link_list",
        "post_links",
        "comments",
        "articles",
    ):
        if isinstance(data.get(key), list):
            return data[key]
    if isinstance(data.get("link"), dict):
        return [data["link"]]
    return [data]


def render(result, *, format="json", output=None):
    result = safe_result(result)
    if format == "json":
        text = json.dumps({"ok": True, "data": result}, ensure_ascii=False) + "\n"
    else:
        rows = query_rows(result)
        rows = [row if isinstance(row, dict) else {"value": row} for row in rows]
        fields = list(dict.fromkeys(key for row in rows for key in row))
        normalized = [
            {
                k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                for k, v in row.items()
            }
            for row in rows
        ]
        stream = io.StringIO()
        if format == "csv":
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(normalized)
        else:
            preferred = (
                "name",
                "title",
                "appid",
                "post_id",
                "linkid",
                "link_id",
                "personal_score",
                "comment_score",
                "text",
            )
            fields = [key for key in preferred if key in fields] + [
                key
                for key in fields
                if key not in preferred and key not in ("blocks", "result", "readback")
            ]
            fields = fields[:8]
            stream.write("\t".join(fields) + "\n")
            for row in normalized:
                stream.write(
                    "\t".join(
                        str(row.get(key, "")).replace("\n", " ").replace("\t", " ")
                        for key in fields
                    )
                    + "\n"
                )
        text = stream.getvalue()
    if output:
        output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
