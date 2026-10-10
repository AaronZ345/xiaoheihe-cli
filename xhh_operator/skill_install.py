"""安装随源码包与 wheel 提供的本地技能，不修改 MCP 或全局程序配置。"""

import os
import re
import shutil
import sysconfig
from pathlib import Path


def skill_source():
    source = Path(__file__).resolve().parent.parent / "skills/xiaoheihe-cli"
    if not source.is_dir():
        source = Path(sysconfig.get_path("data")) / "share/xiaoheihe-cli/skills/xiaoheihe-cli"
    if not (source / "SKILL.md").is_file():
        raise ValueError("发行包缺少技能文件。")
    return source


def install_skill(destination=None):
    root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    destination = Path(destination).expanduser() if destination else root / "skills/xiaoheihe-cli"
    if destination.is_symlink() or (destination / "SKILL.md").is_symlink():
        raise ValueError("技能目标不能是符号链接。")
    if destination.exists():
        try:
            current = (destination / "SKILL.md").read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise ValueError("目标目录已有其他内容，未覆盖。") from None
        if not all(
            re.search(pattern, current, re.M)
            for pattern in (
                r"^name: xiaoheihe-cli\s*$",
                r"^  origin: local\s*$",
                r"^  owner: aaron\s*$",
            )
        ):
            raise ValueError("已存在其他来源的技能，未覆盖。")
    source = skill_source()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True)
    return {"installed": True, "skill": "xiaoheihe-cli"}
