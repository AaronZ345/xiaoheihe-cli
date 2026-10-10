import asyncio
from pathlib import Path

import pytest

from xhh_operator.doctor import diagnose
from xhh_operator.session import SessionStore
from xhh_operator.skill_install import install_skill


def test_doctor_default_does_not_read_login_contents(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "session")
    store.save([{"name": "pkey", "value": "fixture-only", "domain": ".xiaoheihe.cn"}], "42")

    def forbidden(*args, **kwargs):
        raise AssertionError("default doctor must not read a session")

    monkeypatch.setattr(SessionStore, "load", forbidden)
    result = asyncio.run(diagnose(store=store))
    assert not result["checked_login"] and result["session"]["present"]
    assert "user_id" not in result and "cookies" not in result


def test_skill_installer_copies_valid_skill_without_overwriting_unknown_owner(tmp_path):
    target = tmp_path / "installed"
    result = install_skill(target)
    assert result["installed"] and (target / "SKILL.md").is_file()
    assert "owner: aaron" in (target / "SKILL.md").read_text(encoding="utf-8")
    assert install_skill(target)["installed"]
    (target / "SKILL.md").write_text("name: someone-else\n", encoding="utf-8")
    with pytest.raises(ValueError, match="未覆盖"):
        install_skill(target)
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "name: someone-else\n"


def test_product_identifiers_and_published_docs_are_consistent():
    root = Path(__file__).resolve().parent.parent
    import tomllib

    package = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert package["project"]["name"] == "xiaoheihe-cli"
    assert (
        package["project"]["scripts"]["xiaoheihe-cli"] == package["project"]["scripts"]["xiaoheihe"]
    )
    assert not (root / "SKILL.md").exists()
    for name in ("README.md", "docs/cli.md", "docs/MCP.md", "CONTRIBUTING.md"):
        text = (root / name).read_text(encoding="utf-8")
        assert "dots-xiaoheihe-cli" not in text
        assert all(word not in text for word in ("opxqo", "wsmxd", "shadowfish", "基于 ["))


def test_cli_help_is_utf8_with_non_utf8_process_locale(tmp_path):
    import os
    import subprocess
    import sys

    environment = dict(
        os.environ,
        PYTHONIOENCODING="cp1252",
        XHH_OPERATOR_HOME=str(tmp_path / "empty-session"),
    )
    completed = subprocess.run(
        [sys.executable, "-m", "xhh_operator", "--help"],
        env=environment,
        capture_output=True,
        check=True,
    )
    assert "小黑盒" in completed.stdout.decode("utf-8")
