"""小黑盒 MCP：提供发布、查询、登录和个人评测工具，复用同一操作层。"""

import asyncio
import base64
import logging

from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, ToolAnnotations
from pydantic import StrictInt

from .auth import identity, login_browser, login_qr
from .errors import AuthError, OperatorError
from .http import HeyboxAPI
from .service import Operator, present_review
from .session import SessionStore, safe_result


def create_server(*, port=8001):
    if not 1 <= port <= 65535:
        raise ValueError("MCP 端口无效。")
    server = FastMCP("xiaoheihe-cli", host="127.0.0.1", port=port, json_response=True)
    readonly = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
    )
    writing = ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
    )
    qr_state = {"task": None, "error": None}

    async def call(method, *args, **kwargs):
        try:
            async with Operator() as operator:
                result = await getattr(operator, method)(*args, **kwargs)
            return safe_result(result)
        except OperatorError as error:
            if error.code == "auth":
                logging.getLogger(__name__).error("认证失败，操作已停止。")
            raise
        except (OSError, ValueError):
            raise ValueError("操作参数或本地文件无效。") from None

    @server.tool(name="check_login_status", annotations=readonly)
    async def check_login_status() -> dict:
        """核实当前账号登录状态；不回传认证材料。"""
        session = SessionStore().load()
        if not session:
            return {
                "stored": False,
                "authenticated": False,
                "qr_pending": bool(qr_state["task"] and not qr_state["task"].done()),
                "login_error": qr_state["error"],
            }
        async with HeyboxAPI(session["cookies"]) as api:
            response = await api.request("/account/restore_login")
            user = identity(response)
        if user != session["user_id"]:
            raise AuthError("当前账号与保存账号不一致，请重新登录。")
        result = response.get("result") or {}
        profile = result.get("profile") or result.get("account_detail") or {}
        return {
            "stored": True,
            "authenticated": True,
            "user_id": user,
            "username": profile.get("username") or profile.get("nickname"),
        }

    @server.tool(name="interactive_login", annotations=writing)
    async def interactive_login(
        browser: str = "auto",
        timeout: int = 300,
        executable_path: str | None = None,
        driver_path: str | None = None,
    ) -> dict:
        """打开独立的官方登录窗口，由用户完成登录和验证码。"""
        if not 1 <= timeout <= 600:
            raise ValueError("登录等待时间无效。")
        return await login_browser(
            SessionStore(),
            timeout=timeout,
            browser_name=browser,
            executable_path=executable_path,
            driver_path=driver_path,
        )

    @server.tool(name="get_login_qr_code", annotations=writing)
    async def get_login_qr_code(timeout: int = 180):
        """立即返回二维码图片，后台等待 App 确认；随后用 check_login_status 核实。"""
        if not 1 <= timeout <= 600:
            raise ValueError("登录等待时间无效。")
        old = qr_state["task"]
        if old and not old.done():
            old.cancel()
            await asyncio.gather(old, return_exceptions=True)
        ready = asyncio.Event()
        data = {}

        async def on_ready(path):
            data["png"] = base64.b64encode(path.read_bytes()).decode()
            ready.set()

        async def wait_for_login():
            try:
                await login_qr(SessionStore(), timeout=timeout, on_ready=on_ready)
            except OperatorError as error:
                qr_state["error"] = error.code
                if error.code == "auth":
                    logging.getLogger(__name__).error("认证失败，登录已停止。")
            finally:
                ready.set()

        qr_state["error"] = None
        task = asyncio.create_task(wait_for_login())
        qr_state["task"] = task
        await ready.wait()
        if "png" not in data:
            await task
            raise OperatorError("无法生成登录二维码。", qr_state["error"] or "upstream")
        return ImageContent(type="image", data=data["png"], mimeType="image/png")

    @server.tool(name="get_user_profile", annotations=readonly)
    async def get_user_profile(pageSize: int = 10) -> dict:
        """读取本人主页信息及动态，不把用户内容保存到仓库。"""
        if not 1 <= pageSize <= 100:
            raise ValueError("分页大小无效。")
        return await call("profile", limit=pageSize)

    @server.tool(name="get_home_content", annotations=readonly)
    async def get_home_content(limit: int = 20, offset: int = 0) -> dict:
        """读取小黑盒首页内容。"""
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("分页参数无效。")
        return await call("feed", limit=limit, offset=offset)

    @server.tool(name="search_content", annotations=readonly)
    async def search_content(
        keyword: str, kind: str = "post", limit: int = 20, offset: int = 0
    ) -> dict:
        """搜索帖子、游戏、用户或话题。"""
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("分页参数无效。")
        return await call("search", keyword, kind=kind, limit=limit, offset=offset)

    @server.tool(name="get_post_detail", annotations=readonly)
    async def get_post_detail(postId: str) -> dict:
        """按 ID 读取帖子或文章正文、图片和评论。"""
        return await call("post", postId)

    @server.tool(name="publish_content", annotations=writing)
    async def publish_content(
        title: str,
        content: str,
        images: list[str] | None = None,
        communities: list[str] | None = None,
        tags: list[str] | None = None,
        draft: bool = True,
        dry_run: bool = True,
    ) -> dict:
        """发布图文；默认仅预览。实际提交需 dry_run=false，draft=false 正式发布。"""
        return await call(
            "write_post",
            title,
            content,
            post_kind="image_text",
            images=images or [],
            communities=communities or [],
            hashtags=tags or [],
            draft=draft,
            dry_run=dry_run,
        )

    @server.tool(name="publish_article", annotations=writing)
    async def publish_article(
        title: str,
        content: str,
        communities: list[str] | None = None,
        tags: list[str] | None = None,
        images: list[str] | None = None,
        draft: bool = True,
        dry_run: bool = True,
    ) -> dict:
        """文章默认预览；支持 Markdown、HTML 图片及正文中的本地图片绝对路径。"""
        return await call(
            "write_post",
            title,
            content,
            post_kind="article",
            images=images or [],
            communities=communities or [],
            hashtags=tags or [],
            draft=draft,
            dry_run=dry_run,
        )

    @server.tool(name="publish_video", annotations=writing)
    async def publish_video(
        videoPath: str,
        title: str,
        content: str = "",
        coverImagePath: str | None = None,
        communities: list[str] | None = None,
        tags: list[str] | None = None,
        draft: bool = False,
        dry_run: bool = True,
    ) -> dict:
        """上传视频和可选封面，默认仅预览；平台不支持视频草稿；不自动重复上传或发布。"""
        return await call(
            "write_video",
            title,
            videoPath,
            content=content,
            cover=coverImagePath,
            communities=communities or [],
            hashtags=tags or [],
            draft=draft,
            dry_run=dry_run,
        )

    @server.tool(name="post_comment", annotations=writing)
    async def post_comment(
        postId: str, content: str, images: list[str] | None = None, dry_run: bool = True
    ) -> dict:
        """发表文字或图片评论；dry_run 只预检。"""
        return await call("comment", postId, content, images=images or [], dry_run=dry_run)

    @server.tool(name="reply_comment", annotations=writing)
    async def reply_comment(
        postId: str, targetCommentContent: str, content: str, dry_run: bool = True
    ) -> dict:
        """按正文定位目标并回复；正文重复时拒绝自动选择。"""
        return await call(
            "comment", postId, content, target_text=targetCommentContent, dry_run=dry_run
        )

    @server.tool(name="get_personal_games", annotations=readonly)
    async def get_personal_games(limit: int = 20, offset: int = 0, query: str = "") -> dict:
        """读取本人的游戏记录，可按名称查询。"""
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("分页参数无效。")
        return await call("games", limit=limit, offset=offset, query=query)

    @server.tool(name="list_personal_reviews", annotations=readonly)
    async def list_personal_reviews(
        limit: int = 20, offset: int = 0, summary: bool = False
    ) -> dict:
        """读取本人评分和完整短评；summary 仅取摘要。"""
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("分页参数无效。")
        return await call("reviews", limit=limit, offset=offset, summary=summary)

    @server.tool(name="get_personal_review", annotations=readonly)
    async def get_personal_review(appid: str) -> dict:
        """读取单款游戏的本人评分与完整短评。"""
        return present_review(await call("review", appid))

    @server.tool(name="create_personal_review", annotations=writing)
    async def create_personal_review(
        appid: str, score: StrictInt, text: str, dry_run: bool = True
    ) -> dict:
        """创建个人评分与短评；已有记录时拒绝覆盖。"""
        return await call("write_review", appid, score=score, content=text, dry_run=dry_run)

    @server.tool(name="edit_personal_review", annotations=writing)
    async def edit_personal_review(
        appid: str, score: StrictInt | None = None, text: str | None = None, dry_run: bool = True
    ) -> dict:
        """修改个人评分或短评，未提供的字段保留原值。"""
        if score is None and text is None:
            raise ValueError("请提供评分或正文。")
        return await call(
            "write_review", appid, score=score, content=text, edit=True, dry_run=dry_run
        )

    @server.tool(
        name="delete_personal_review",
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True
        ),
    )
    async def delete_personal_review(appid: str, dry_run: bool = True) -> dict:
        """删除本人短评，先核实作者和游戏身份。"""
        return await call("delete_review", appid, dry_run=dry_run)

    return server


def serve(*, transport="stdio", port=8001):
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    create_server(port=port).run(transport=transport)
