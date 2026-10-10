"""保留兼容命令和输出格式；个人操作使用新的命令组。"""

import sys

from .errors import OperatorError

LEGACY_COMMANDS = {
    "get",
    "g",
    "comments",
    "c",
    "batch",
    "b",
    "creator",
    "cr",
    "list",
    "ls",
    "pub",
    "publish",
    "serve",
    "s",
    "status",
    "st",
}


def legacy_command(argv):
    position = 0
    while position < len(argv):
        token = argv[position]
        if token in ("-f", "--format", "-o", "--output", "--cookie-file"):
            position += 2
        elif (
            token.startswith(("--format=", "--output=", "--cookie-file="))
            or (token.startswith(("-f", "-o")) and len(token) > 2)
            or token in ("--headless", "--no-headless")
        ):
            position += 1
        else:
            return token if token in LEGACY_COMMANDS else None
    return None


def run_legacy(argv):
    if any(
        a in ("--cookie", "--password", "--cookie-string")
        or a.startswith(("--cookie=", "--password=", "--cookie-string="))
        for a in argv
    ):
        raise OperatorError(
            "请使用 login、官方网页登录或 --cookie-file；不接受命令行凭据。", "input"
        )
    import cli as upstream

    original = sys.argv
    sys.argv = ["xiaoheihe", *argv]
    try:
        upstream.main()
    finally:
        sys.argv = original
