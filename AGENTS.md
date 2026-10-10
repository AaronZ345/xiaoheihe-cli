# xiaoheihe-cli

Maintain a focused Xiaoheihe CLI, Python SDK, REST API and optional MCP service. Preserve the copyright and permission notices in LICENSE.

- Keep account and publishing behavior in `xhh_operator`; interfaces call the same operations.
- Tests use synthetic files, account responses and local servers. Default verification must not read real sessions or contact the platform.
- Writes submit once, then read back. Never retry an unknown write, publish after an upload failure, silently select a duplicate name, or label an incomplete read complete.
- Retain unspecified review fields; confirm author and record identity before edits and deletion.
- Keep browser profiles, session files, exports and media outside Git and release packages.
- Temporary artifacts belong in ignored `tmp/` or `output/`; remove them before delivery.
- Run `uv run --extra dev --extra mcp python scripts/verify.py`, relevant browser checks and `git diff --check`.
- Browser launch tests and synthetic DOM tests do not establish real login or publishing success. Document the validation boundary.
