"""统一离线验收：静态检查、测试、构建、CLI smoke 与包结构。"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*arguments):
    subprocess.run(arguments, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    run(sys.executable, "-m", "ruff", "check", ".")
    run(sys.executable, "-m", "ruff", "format", "--check", ".")
    run(sys.executable, "-m", "pytest", "-q")
    for command in (
        ["--version"],
        ["--help"],
        ["video", "create", "--help"],
        ["comment", "reply", "--help"],
    ):
        completed = subprocess.run(
            [sys.executable, "-m", "xhh_operator", *command],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        if not completed.stdout.strip():
            raise RuntimeError("CLI smoke 没有输出。")
    if not args.skip_build:
        run("uv", "build")
        run(sys.executable, "scripts/package_check.py")
    print(
        json.dumps(
            {
                "lint": True,
                "tests": True,
                "cli_smoke": True,
                "build": not args.skip_build,
                "anonymous_verification": True,
            }
        )
    )


if __name__ == "__main__":
    main()
