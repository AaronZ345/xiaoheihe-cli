import csv
import io

import pytest

from xhh_operator.output import render


@pytest.mark.parametrize(
    "key", ["games", "game_list", "items", "topics", "links", "post_links", "comments"]
)
@pytest.mark.parametrize("format", ["table", "csv"])
def test_query_formats_display_records_inside_api_result(key, format, capsys):
    data = {"status": "ok", "result": {key: [{"name": "fixture game", "text": "完整查询正文"}]}}
    render(data, format=format)
    output = capsys.readouterr().out
    assert "fixture game" in output and "完整查询正文" in output
    if format == "csv":
        rows = list(csv.DictReader(io.StringIO(output)))
        assert rows == [{"name": "fixture game", "text": "完整查询正文"}]


def test_table_displays_single_post_instead_of_only_api_status(capsys):
    render(
        {"status": "ok", "result": {"link": {"title": "fixture title", "text": "正文"}}},
        format="table",
    )
    assert "fixture title" in capsys.readouterr().out


def test_table_prioritizes_name_and_personal_score_over_metadata(capsys):
    item = {**{f"metadata_{i}": i for i in range(10)}, "name": "fixture", "personal_score": 4}
    render({"result": {"games": [item]}}, format="table")
    header = capsys.readouterr().out.splitlines()[0]
    assert "name" in header and "personal_score" in header
