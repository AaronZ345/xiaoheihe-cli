"""Container-only offline smoke checks; no account or platform requests."""

import json
import os
import stat
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from xhh_operator.session import SessionStore


def main():
    if os.getuid() == 0:
        raise SystemExit("Container smoke test requires the non-root application user.")
    root = Path(os.environ["XHH_OPERATOR_HOME"])
    with tempfile.TemporaryDirectory(prefix=".validation-", dir=root) as directory:
        store = SessionStore(Path(directory) / "fixture")
        store.save([{"name": "pkey", "value": "fixture-only", "domain": ".xiaoheihe.cn"}], "42")
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
        assert store.load()["user_id"] == "42"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content("<title>Container smoke fixture</title><button>ready</button>")
            assert page.title() == "Container smoke fixture"
            assert page.get_by_role("button", name="ready").count() == 1
        finally:
            browser.close()
    print(json.dumps({"non_root": True, "managed_session_writable": True, "chromium": True}))


if __name__ == "__main__":
    main()
