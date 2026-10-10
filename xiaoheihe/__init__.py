"""
小黑盒 SDK 核心客户端
支持上下文管理器和守护模式调用

用法:
    # 直接使用（自动管理浏览器生命周期）
    async with XiaoheiheClient() as client:
        post = await client.get_post("179245676")
        print(post["title"])

    # 守护模式调用
    client = XiaoheiheClient(daemon=True)
    post = await client.get_post("179245676")  # 自动连接守护进程
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket as stdlib_socket
from typing import Any, Dict, List, Optional

from api_client import XiaoheiheAPIClient
from browser_manager import BrowserManager
from config import get_cookie
from data_parser import DataParser
from utils import extract_link_id
from xhh_operator.service import Operator as Operator

logger = logging.getLogger(__name__)

# 守护进程通信地址
_DAEMON_HOST = "127.0.0.1"
_DAEMON_PORT = 19810


class XiaoheiheClient:
    """
    小黑盒爬虫统一客户端

    两种模式:
    - 直连模式: 管理 Playwright 浏览器实例
    - 守护模式: 通过 TCP 连接已运行的守护进程
    """

    def __init__(
        self,
        headless: bool = True,
        daemon: bool = False,
    ):
        self.headless = headless
        self.daemon_mode = daemon

        self._browser_manager: Optional[BrowserManager] = None
        self._api_client: Optional[XiaoheiheAPIClient] = None
        self._socket: Optional[stdlib_socket.socket] = None

    async def __aenter__(self) -> XiaoheiheClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # ==================== 连接管理 ====================

    async def connect(self):
        if self.daemon_mode:
            await self._connect_daemon()
        else:
            await self._connect_direct()

    async def connect_with_cookies(self, cookie_string: str):
        """
        用 Cookie 字符串直连（跳过登录/验证码）。
        适合从浏览器复制 Cookie 后快速初始化。
        """
        self._browser_manager = BrowserManager(headless=self.headless)
        await self._browser_manager.inject_cookies(cookie_string, persist=False)
        if not await self._browser_manager.validate_cookies(prepare_page=False):
            raise RuntimeError("认证失败，请执行 xiaoheihe login。")
        self._api_client = XiaoheiheAPIClient(
            page=self._browser_manager.api_page,
            cookies=getattr(self._browser_manager, "cookies", None),
            page_provider=getattr(self._browser_manager, "_ensure_api_page", None),
        )
        self._api_client.set_heybox_id(self._browser_manager.heybox_id)
        logger.info("Cookie 注入模式就绪 (heybox_id=%s)", self._browser_manager.heybox_id)

    async def login(self, phone: str, code_callback=None, password=None) -> bool:
        """
        手机号登录（支持密码或验证码模式）。
        """
        self._browser_manager = BrowserManager(headless=self.headless)
        result = await self._browser_manager.login_with_phone(
            phone=phone,
            code_callback=code_callback,
            password=password,
        )
        if result:
            await self._browser_manager.start_session()
            self._api_client = XiaoheiheAPIClient(
                page=self._browser_manager.api_page,
                cookies=getattr(self._browser_manager, "cookies", None),
                page_provider=getattr(self._browser_manager, "_ensure_api_page", None),
            )
            self._api_client.set_heybox_id(self._browser_manager.heybox_id)
        return result

    async def _connect_direct(self):
        """校验会话并准备 API 上下文；HTTP 查询不依赖首页导航。"""
        self._browser_manager = BrowserManager(headless=self.headless)
        cookie_string = get_cookie()
        if cookie_string:
            await self._browser_manager.inject_cookies(cookie_string, persist=False)
            if not await self._browser_manager.validate_cookies(prepare_page=False):
                raise RuntimeError("认证失败，请执行 xiaoheihe login。")
        else:
            await self._browser_manager.init()
        self._api_client = XiaoheiheAPIClient(
            page=self._browser_manager.api_page,
            cookies=getattr(self._browser_manager, "cookies", None),
            page_provider=getattr(self._browser_manager, "_ensure_api_page", None),
        )
        self._api_client.set_heybox_id(self._browser_manager.heybox_id)

    async def _connect_daemon(self):
        """守护模式：通过 TCP 连接"""
        self._socket = stdlib_socket.socket(stdlib_socket.AF_INET, stdlib_socket.SOCK_STREAM)
        self._socket.connect((_DAEMON_HOST, _DAEMON_PORT))
        self._socket.settimeout(30)
        logger.info("守护模式已连接")

    async def close(self):
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

        if self._api_client:
            await self._api_client.close()
            self._api_client = None

        if self._browser_manager:
            await self._browser_manager.close()
            self._browser_manager = None

    # ==================== 数据获取接口 ====================

    async def get_post(
        self,
        post_id: str,
        full: bool = False,
    ) -> Dict[str, Any]:
        link_id = extract_link_id(post_id)

        if self.daemon_mode:
            return await self._daemon_request(
                {"action": "get_post", "link_id": link_id, "full": full}
            )

        if full:
            result = await self._api_client.get_post_full(link_id)
        else:
            result = await self._api_client.get_post_comments(link_id, page_num=1, limit=20)

        if not result:
            raise RuntimeError(f"帖子不存在或Cookie已过期: {link_id}")

        post_meta, comments = DataParser.parse_comments_response(result)
        post = DataParser.parse_post_from_comments(
            link_id,
            f"https://www.xiaoheihe.cn/app/bbs/link/{link_id}",
            comments,
            post_meta=post_meta,
        )
        return post.model_dump()

    async def get_comments(
        self,
        post_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        link_id = extract_link_id(post_id)

        if self.daemon_mode:
            return await self._daemon_request(
                {
                    "action": "get_comments",
                    "link_id": link_id,
                    "page": page,
                    "page_size": page_size,
                }
            )

        result = await self._api_client.get_post_comments(
            link_id, page_num=page, limit=page_size, is_first=1
        )

        if not result:
            raise RuntimeError(f"帖子不存在或Cookie已过期: {link_id}")

        _, comments = DataParser.parse_comments_response(result)
        return {
            "comments": [c.model_dump() for c in comments],
            "page": page,
            "page_size": page_size,
        }

    async def batch_get(
        self,
        post_ids: List[str],
        full: bool = False,
        delay: float = 2.0,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for i, pid in enumerate(post_ids):
            if i > 0:
                await asyncio.sleep(delay)
            try:
                data = await self.get_post(pid, full=full)
                results.append(data)
            except Exception:
                raise RuntimeError(f"批量读取在帖子 {pid} 失败，已停止后续请求。") from None
        return results

    async def get_creator_data(self, post_id: str) -> Dict[str, Any]:
        link_id = extract_link_id(post_id)

        if self.daemon_mode:
            return await self._daemon_request({"action": "get_creator", "link_id": link_id})

        result = await self._api_client.get_creator_data(link_id)

        if not result:
            raise RuntimeError(f"无法获取创作者数据（可能非自己的帖子或Cookie已过期）: {link_id}")

        stats = DataParser.parse_creator_response(result)
        return stats.model_dump()

    async def get_my_articles(self) -> Dict[str, Any]:
        if self.daemon_mode:
            return await self._daemon_request({"action": "get_article_list"})

        result = await self._api_client.get_article_list()
        if not result:
            raise RuntimeError("无法获取文章列表（Cookie可能已过期或非创作者账号）")

        article_list = DataParser.parse_article_list_response(result)
        return article_list.model_dump()

    @staticmethod
    def render_article_content(
        content: str,
        source_format: str = "auto",
    ) -> tuple[str, str]:
        """
        将 Markdown/HTML/混合内容转换成更适合小黑盒发布的 HTML。

        Returns:
            (html_content, convert_stats_summary)
        """
        from markdown_converter import HeyBoxConverter

        converter = HeyBoxConverter()
        html_content = converter.convert(content, source_format=source_format)
        return html_content, converter.stats.summary()

    async def publish(
        self,
        title: str,
        html_content: str,
        link_tag: int = 11,
        draft: bool = True,
    ) -> Dict[str, Any]:
        """
        发布文章（或保存到草稿箱）。

        Args:
            title: 文章标题
            html_content: HTML 格式正文
            link_tag: 标签ID（默认11=校园生活）
            draft: True=草稿, False=正式发布

        Returns:
            PublishResult dict（含 success/link_id/message）
        """
        if self.daemon_mode:
            return await self._daemon_request(
                {
                    "action": "publish",
                    "title": title,
                    "html_content": html_content,
                    "link_tag": link_tag,
                    "draft": draft,
                }
            )

        result = await self._api_client.publish_article(
            title=title,
            html_content=html_content,
            link_tag=link_tag,
            draft=draft,
        )

        if not result:
            raise RuntimeError("发布失败（Cookie可能已过期或签名参数获取失败）")

        from models import PublishResult

        # API 可能返回 {"status":"ok","link_id":xxx,...} 或 {"status":"ok","result":{"link_id":xxx},...}
        lid = result.get("link_id")
        if not lid:
            lid = (result.get("result") or {}).get("link_id")
        raw_result = result.get("raw") if isinstance(result.get("raw"), dict) else result
        pr = PublishResult(
            success=bool(result.get("success")) or result.get("status") == "ok",
            link_id=lid,
            message=result.get("message") or result.get("msg", ""),
            is_draft=draft,
            raw=raw_result,
        )
        return pr.model_dump()

    async def publish_content(
        self,
        title: str,
        content: str,
        *,
        source_format: str = "auto",
        link_tag: int = 11,
        draft: bool = True,
    ) -> Dict[str, Any]:
        """
        先做格式转换，再发布内容。

        适合服务器侧接入，避免直接把 Markdown 当作 HTML 发给小黑盒。
        """
        html_content, convert_stats = self.render_article_content(
            content,
            source_format=source_format,
        )
        result = await self.publish(
            title=title,
            html_content=html_content,
            link_tag=link_tag,
            draft=draft,
        )
        result["convert_stats"] = convert_stats
        result["source_format"] = source_format
        return result

    async def publish_markdown(
        self,
        title: str,
        markdown_content: str,
        *,
        link_tag: int = 11,
        draft: bool = True,
    ) -> Dict[str, Any]:
        """将 Markdown 转成小黑盒兼容 HTML 后再发布。"""
        return await self.publish_content(
            title=title,
            content=markdown_content,
            source_format="markdown",
            link_tag=link_tag,
            draft=draft,
        )

    @staticmethod
    def _send(sock: stdlib_socket.socket, msg: str) -> None:
        sock.sendall((msg + "\n").encode("utf-8"))

    @staticmethod
    def _recv(sock: stdlib_socket.socket) -> str:
        data = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break
        return data.decode("utf-8").strip()

    async def _daemon_request(self, request: dict) -> dict:
        if not self._socket:
            await self._connect_daemon()

        try:
            msg = json.dumps(request, ensure_ascii=False)
            XiaoheiheClient._send(self._socket, msg)
            response_text = XiaoheiheClient._recv(self._socket)
            response = json.loads(response_text)
            self._socket.close()
            self._socket = None

            if response.get("status") == "error":
                raise RuntimeError(response.get("message", "未知错误"))
            return response.get("data", {})

        except (ConnectionResetError, ConnectionRefusedError, BrokenPipeError):
            raise RuntimeError("守护进程未运行。请先执行: xiaoheihe serve")
        except json.JSONDecodeError:
            raise RuntimeError("守护进程返回了无效的响应")


# ==================== 守护进程服务端 ====================


class DaemonServer:
    """小黑盒守护进程服务端 —— 保持浏览器常驻，监听 TCP 请求"""

    def __init__(self, host: str = "127.0.0.1", port: int = 19810, headless: bool = True):
        self.host = host
        self.port = port
        self.headless = headless
        self._browser_manager: Optional[BrowserManager] = None
        self._api_client: Optional[XiaoheiheAPIClient] = None
        self._running = False
        self._server: Optional[asyncio.Server] = None
        self._stop_lock = asyncio.Lock()

    async def start(self):
        self._browser_manager = BrowserManager(headless=self.headless)
        cookie_string = ""
        try:
            from config import get_cookie

            cookie_string = get_cookie()
        except Exception:
            cookie_string = ""

        if cookie_string:
            await self._browser_manager.inject_cookies(cookie_string, persist=False)
            if not await self._browser_manager.validate_cookies(prepare_page=False):
                raise RuntimeError("认证失败，请执行 xiaoheihe login。")
        else:
            await self._browser_manager.init()
        self._api_client = XiaoheiheAPIClient(
            page=self._browser_manager.api_page,
            cookies=getattr(self._browser_manager, "cookies", None),
            page_provider=getattr(self._browser_manager, "_ensure_api_page", None),
        )
        self._api_client.set_heybox_id(self._browser_manager.heybox_id)

        logger.info(f"守护进程就绪 (port={self.port}, heybox_id={self._browser_manager.heybox_id})")

        try:
            self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
            self._running = True
            addrs = ", ".join(str(s.getsockname()) for s in (self._server.sockets or []))
            logger.info(f"守护进程监听: {addrs}")
            async with self._server:
                try:
                    await self._server.serve_forever()
                except asyncio.CancelledError:
                    if self._running:
                        raise
        finally:
            await self.stop()

    async def stop(self):
        async with self._stop_lock:
            self._running = False
            if self._server:
                self._server.close()
                await self._server.wait_closed()
                self._server = None
            if self._api_client:
                await self._api_client.close()
                self._api_client = None
            if self._browser_manager:
                await self._browser_manager.close()
                self._browser_manager = None
            logger.info("守护进程已停止")

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        try:
            request_data = await reader.readline()
            if not request_data:
                writer.close()
                return

            request = json.loads(request_data.decode("utf-8").strip())

            handlers = {
                "get_post": self._handle_get_post,
                "get_comments": self._handle_get_comments,
                "batch_get": self._handle_batch_get,
                "get_creator": self._handle_get_creator,
                "get_article_list": self._handle_get_article_list,
                "publish": self._handle_publish,
                "health": self._handle_health,
                "stop": self._handle_stop,
            }
            handler = handlers.get(request.get("action"), self._handle_unknown)
            result = await handler(request)

            resp = json.dumps(result, ensure_ascii=False, default=str) + "\n"
            writer.write(resp.encode("utf-8"))
            await writer.drain()

        except json.JSONDecodeError:
            await self._send_error(writer, "无效的JSON")
        except Exception as e:
            await self._send_error(writer, str(e))
        finally:
            writer.close()

    @staticmethod
    async def _send_error(writer: asyncio.StreamWriter, message: str):
        error_resp = json.dumps({"status": "error", "message": message}) + "\n"
        writer.write(error_resp.encode("utf-8"))
        await writer.drain()

    # ---- 请求处理器 ----

    async def _handle_get_post(self, req: dict) -> dict:
        link_id = req.get("link_id", "")
        try:
            full = req.get("full", False)
            result = await (
                self._api_client.get_post_full(link_id)
                if full
                else self._api_client.get_post_comments(link_id, page_num=1, limit=20)
            )

            if not result:
                return {"status": "error", "message": f"帖子不存在或Cookie已过期: {link_id}"}

            post_meta, comments = DataParser.parse_comments_response(result)
            post = DataParser.parse_post_from_comments(
                link_id,
                f"https://www.xiaoheihe.cn/app/bbs/link/{link_id}",
                comments,
                post_meta=post_meta,
            )
            return {"status": "ok", "data": post.model_dump()}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def _handle_get_comments(self, req: dict) -> dict:
        link_id = req.get("link_id", "")
        try:
            result = await self._api_client.get_post_comments(
                link_id, page_num=req.get("page", 1), limit=req.get("page_size", 20), is_first=1
            )
            if not result:
                return {"status": "error", "message": f"帖子不存在或Cookie已过期: {link_id}"}

            _, comments = DataParser.parse_comments_response(result)
            return {
                "status": "ok",
                "data": {
                    "comments": [c.model_dump() for c in comments],
                    "page": req.get("page", 1),
                    "page_size": req.get("page_size", 20),
                },
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def _handle_batch_get(self, req: dict) -> dict:
        post_ids = req.get("post_ids", [])
        results: list = []
        for i, pid in enumerate(post_ids):
            if i > 0:
                await asyncio.sleep(2.0)
            try:
                full = req.get("full")
                result = await (
                    self._api_client.get_post_full(pid)
                    if full
                    else self._api_client.get_post_comments(pid, page_num=1, limit=20)
                )
                if not result:
                    raise RuntimeError("帖子不存在，批量读取已停止。")
                post_meta, comments = DataParser.parse_comments_response(result)
                post = DataParser.parse_post_from_comments(
                    pid,
                    f"https://www.xiaoheihe.cn/app/bbs/link/{pid}",
                    comments,
                    post_meta=post_meta,
                )
                results.append(post.model_dump())
            except Exception:
                raise RuntimeError(f"批量读取在帖子 {pid} 失败，已停止后续请求。") from None
        return {"status": "ok", "data": results}

    async def _handle_get_creator(self, req: dict) -> dict:
        link_id = req.get("link_id", "")
        try:
            result = await self._api_client.get_creator_data(link_id)
            if not result:
                return {
                    "status": "error",
                    "message": f"无法获取创作者数据（可能非自己的帖子）: {link_id}",
                }
            stats = DataParser.parse_creator_response(result)
            return {"status": "ok", "data": stats.model_dump()}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def _handle_get_article_list(self, _req: dict) -> dict:
        try:
            result = await self._api_client.get_article_list()
            if not result:
                return {"status": "error", "message": "无法获取文章列表（Cookie可能已过期）"}
            article_list = DataParser.parse_article_list_response(result)
            return {"status": "ok", "data": article_list.model_dump()}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def _handle_publish(self, req: dict) -> dict:
        try:
            result = await self._api_client.publish_article(
                title=req.get("title", ""),
                html_content=req.get("html_content", ""),
                link_tag=req.get("link_tag", 11),
                draft=req.get("draft", True),
            )
            if not result:
                return {
                    "status": "error",
                    "message": "发布失败（Cookie可能已过期或签名参数获取失败）",
                }

            from models import PublishResult

            lid = result.get("link_id")
            if not lid:
                lid = (result.get("result") or {}).get("link_id")
            pr = PublishResult(
                success=bool(result.get("success")) or result.get("status") == "ok",
                link_id=lid,
                message=result.get("message") or result.get("msg", ""),
                is_draft=req.get("draft", True),
                raw=result.get("raw") if isinstance(result.get("raw"), dict) else result,
            )
            return {"status": "ok", "data": pr.model_dump()}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def _handle_health(self, _req: dict) -> dict:
        bm = self._browser_manager
        return {
            "status": "ok",
            "data": {
                "service": "xiaoheihe-daemon",
                "version": "2.2.0",
                "cookies_valid": len(bm.cookies) > 0 if bm else False,
                "heybox_id": bm.heybox_id if bm else None,
            },
        }

    async def _handle_stop(self, _req: dict) -> dict:
        asyncio.create_task(self.stop())
        return {"status": "ok", "message": "守护进程正在关闭"}

    @staticmethod
    async def _handle_unknown(req: dict) -> dict:
        return {"status": "error", "message": f"未知操作: {req.get('action')}"}
