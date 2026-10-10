"""检查发行包结构与运行时文件排除；不读取用户登录文件。"""

import argparse
import hashlib
import json
import tarfile
import zipfile
from pathlib import Path


def check_packages(directory):
    directory = Path(directory)
    artifacts = sorted(
        [*directory.glob("xiaoheihe_cli-*.whl"), *directory.glob("xiaoheihe_cli-*.tar.gz")]
    )
    if not artifacts:
        raise ValueError("没有找到发行包。")
    forbidden = {"tmp", "output", "session", ".venv", ".git", "profiles", "profile", "__pycache__"}
    checked = []
    for artifact in artifacts:
        if artifact.suffix == ".whl":
            with zipfile.ZipFile(artifact) as archive:
                names = archive.namelist()
                required = (
                    "xhh_operator/cli.py",
                    "xhh_operator/service.py",
                    "xhh_operator/media.py",
                    "xhh_operator/mcp_server.py",
                    "xiaoheihe/__init__.py",
                    "api_server.py",
                )
                if any(name not in names for name in required):
                    raise ValueError("wheel 缺少运行模块。")
                entry = next(
                    (name for name in names if name.endswith(".dist-info/entry_points.txt")), None
                )
                if not entry or "xiaoheihe-cli =" not in archive.read(entry).decode():
                    raise ValueError("wheel 缺少主命令入口。")
            if not any(name.endswith("/skills/xiaoheihe-cli/SKILL.md") for name in names):
                raise ValueError("wheel 缺少技能文件。")
        else:
            with tarfile.open(artifact) as archive:
                names = archive.getnames()
            required = (
                "README.md",
                "LICENSE",
                "AGENTS.md",
                "docs/MCP.md",
                "scripts/verify.py",
                "skills/xiaoheihe-cli/SKILL.md",
            )
            if any(not any(name.endswith("/" + item) for name in names) for item in required):
                raise ValueError("源码包缺少必要文件。")
        for name in names:
            parts = Path(name).parts
            if any(part in forbidden or part.startswith(".env") for part in parts) or Path(
                name
            ).name in ("cookies.json", "session.json", "daemon.pid"):
                raise ValueError("发行包包含运行时或登录文件。")
        checked.append(
            {"file": artifact.name, "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}
        )
    return checked


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", default="dist")
    args = parser.parse_args()
    print(json.dumps({"packages": check_packages(args.directory), "runtime_files_excluded": True}))
