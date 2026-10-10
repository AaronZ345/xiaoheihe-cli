# 开发指南

## 环境与统一验收

```bash
uv sync --extra dev --extra mcp --frozen
uv run --extra dev --extra mcp python scripts/verify.py
```

macOS／Linux 也可以用 `make verify`。统一入口依次检查 Ruff、测试、CLI smoke、构建和包结构；默认不接触真实账号或平台。仅做代码检查时可加 `--skip-build`。

单独执行：

```bash
uv run --extra dev --extra mcp pytest -q
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv build
uv run python scripts/package_check.py
```

浏览器测试启动真实引擎，但请求全部路由到合成页面和模拟账号：

```bash
uv run playwright install chromium firefox webkit
XHH_RUN_BROWSER_TESTS=1 uv run --extra dev --extra mcp pytest -q -m browser
```

Windows 可先在当前 PowerShell 设置 `$env:XHH_RUN_BROWSER_TESTS='1'`。未安装的运行时明确跳过，不能据此宣称真实登录或跨平台发布通过。

原生 Firefox／Safari 测试另设 `XHH_RUN_NATIVE_TESTS=1`，要求对应浏览器和驱动已就绪。测试使用本机临时页面和模拟账号；CI 的 `XHH_REQUIRE_NATIVE_TESTS=1` 会把应有运行时缺失视为失败。

## 目录

- `xhh_operator/`：命令、账号与社区操作、评论、媒体上传、诊断、MCP 和技能安装。
- `xiaoheihe/`：Python 客户端及 `Operator` 导出。
- 根目录兼容模块：CLI、解析、格式转换和 REST 入口。
- `skills/xiaoheihe-cli/`：自包含技能与界面元数据。
- `scripts/`：验收、发包检查、技能安装和容器 smoke。
- `tests/`：合成接口、媒体、协议、会话隔离、命令和浏览器测试。
- `docs/`：用户文档、参数、兼容性和验证记录。

所有接口复用同一操作层。修复应以真实接口契约或复现为依据，为分页、媒体、身份校验和无重复提交等行为补充有意义的测试。

## 发布

包名、Skill 和主入口为 `xiaoheihe-cli`，命令别名为 `xiaoheihe`。wheel 包含运行模块和技能；源码包包含文档、测试、许可和维护脚本。

检查版本后推送 `v<version>` 标签会触发 Release 工作流。工作流校验标签、执行验收，并附加 wheel、源码包和 SHA256 校验文件；不自动发布到 PyPI。未发布的本地工作不应使用虚构的 Release 或 CI 徽章。

真实登录材料、个人记录、媒体、浏览器资料、环境文件和调试输出不进入 Git 或发行包。临时文件放在忽略目录，完成前清理。保留许可与必要的版权声明。
