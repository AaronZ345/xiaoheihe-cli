"""
小黑盒后端 API 调用层。

帖子、评论和创作者查询通过签名 HTTP 请求获取数据；少量辅助接口保留页面拦截。
发布接口直接调用后端接口保存草稿或发布内容。
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import logging
import os
import re
import urllib.parse
from contextlib import asynccontextmanager
from typing import Optional

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.xiaoheihe.cn"
_API_BASE = "https://api.xiaoheihe.cn"
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)


class XiaoheiheAPIClient:
    """小黑盒后端 API 客户端。"""

    def __init__(self, page):
        self._page = page
        self._heybox_id: Optional[str] = None

    async def close(self):
        """关闭客户端（页面生命周期由 BrowserManager 管理）。"""

    def set_heybox_id(self, heybox_id: str):
        self._heybox_id = heybox_id

    async def get_post_comments(
        self, link_id: str, page_num: int = 1, limit: int = 20, is_first: int = 1
    ) -> Optional[dict]:
        from xhh_operator.http import HeyboxAPI

        cookies = await self._page.context.cookies()
        async with HeyboxAPI(cookies) as api:
            return await api.request(
                "/bbs/app/link/tree",
                params={
                    "link_id": link_id,
                    "page": page_num,
                    "is_first": 1 if page_num == 1 and is_first else 0,
                    "index": 1,
                    "owner_only": 0,
                    "offset": (page_num - 1) * limit,
                    "limit": limit,
                    "sort_filter": "oldest",
                },
            )

    async def get_post_full(self, link_id: str, page_size: int = 20) -> Optional[dict]:
        from xhh_operator.comments import read_thread
        from xhh_operator.http import HeyboxAPI

        cookies = await self._page.context.cookies()
        async with HeyboxAPI(cookies) as api:
            return await read_thread(api, link_id, page_size=page_size)

    async def get_emojis(self) -> Optional[dict]:
        return await self._navigate_and_intercept(
            link_id="1",
            api_pattern="/bbs/app/api/emojis/list",
            url=f"{_BASE_URL}/app/bbs/home",
        )

    async def get_related_posts(self, link_id: str) -> Optional[dict]:
        return await self._navigate_and_intercept(
            link_id=link_id,
            api_pattern="/bbs/app/link/related/recommend_web",
        )

    async def get_creator_data(self, link_id: str) -> Optional[dict]:
        return await self._read_api(
            "/bbs/app/author/concept/article/data", params={"link_id": link_id}
        )

    async def get_article_list(self) -> Optional[dict]:
        return await self._read_api(
            "/bbs/app/author/concept/article/list",
            params={
                "article_type": "all",
                "artilce_state": "all",
                "sort_filter": "create_at",
                "offset": 0,
                "limit": 20,
            },
        )

    async def _read_api(self, path: str, *, params: dict):
        from xhh_operator.http import HeyboxAPI

        cookies = await self._page.context.cookies()
        async with HeyboxAPI(cookies) as api:
            return await api.request(path, params=params)

    async def publish_article(
        self,
        title: str,
        html_content: str,
        link_tag: int = 11,
        draft: bool = True,
        edit_link_id: Optional[str] = None,
    ) -> Optional[dict]:
        from xhh_operator.http import HeyboxAPI
        from xhh_operator.session import safe_result
        from xhh_operator.signing import workshop_params

        cookies = await self._page.context.cookies()
        form = {
            "title": title,
            "text": json.dumps(self._build_editor_blocks(html_content), ensure_ascii=False),
            "post_type": "1",
            "link_tag": str(link_tag),
            "draft": "1" if draft else "0",
            "original": "1",
            "view_limit": "1",
            "words_count": str(len(html_content)),
        }
        if edit_link_id:
            form.update({"edit": "1", "link_id": edit_link_id})
        async with HeyboxAPI(cookies) as api:
            result = await api.request("/bbs/app/api/link/post", form=form, extra=workshop_params)
        return {
            "success": True,
            "link_id": result.get("link_id") or (result.get("result") or {}).get("link_id"),
            "message": "提交成功",
            "is_draft": draft,
            "raw": safe_result(result),
        }

    @staticmethod
    def _env_flag(name: str) -> bool:
        value = os.environ.get(name, "").strip().lower()
        return value in {"1", "true", "yes", "on"}

    @staticmethod
    def _build_editor_blocks(html_content: str) -> list[dict]:
        normalized = XiaoheiheAPIClient._unwrap_image_only_paragraphs(html_content or "")
        blocks: list[dict] = []
        last_index = 0

        for match in _IMG_TAG_RE.finditer(normalized):
            if XiaoheiheAPIClient._is_inside_text_container(normalized, match.start()):
                continue

            img_block = XiaoheiheAPIClient._img_tag_to_block(match.group(0))
            if not img_block:
                continue

            XiaoheiheAPIClient._append_html_block(blocks, normalized[last_index : match.start()])
            blocks.append(img_block)
            last_index = match.end()

        XiaoheiheAPIClient._append_html_block(blocks, normalized[last_index:])
        return blocks or [{"text": html_content or "", "type": "html"}]

    @staticmethod
    def _append_html_block(blocks: list[dict], fragment: str) -> None:
        fragment = re.sub(r"<p>\s*</p>", "", (fragment or ""), flags=re.IGNORECASE).strip()
        if not fragment:
            return

        if blocks and blocks[-1].get("type") == "html":
            blocks[-1]["text"] = f"{blocks[-1]['text']}{fragment}"
        else:
            blocks.append({"text": fragment, "type": "html"})

    @staticmethod
    def _unwrap_image_only_paragraphs(html_content: str) -> str:
        def replace_paragraph(match):
            inner = match.group(1)
            stripped = re.sub(r"<img\b[^>]*>", "", inner, flags=re.IGNORECASE)
            stripped = re.sub(r"<br\s*/?>", "", stripped, flags=re.IGNORECASE)
            if stripped.strip():
                return match.group(0)
            return inner.strip()

        return re.sub(
            r"<p>([\s\S]*?)</p>",
            replace_paragraph,
            html_content or "",
            flags=re.IGNORECASE,
        )

    @staticmethod
    def _img_tag_to_block(tag: str) -> Optional[dict]:
        src_match = re.search(r"\bsrc=(['\"])(.*?)\1", tag, flags=re.IGNORECASE)
        if not src_match:
            return None

        src = html_lib.unescape(src_match.group(2)).strip()
        if not src or not XiaoheiheAPIClient._is_supported_editor_image(src):
            return None

        return {"url": src, "width": None, "height": None, "type": "img"}

    @staticmethod
    def _is_supported_editor_image(src: str) -> bool:
        if src.startswith("data:image/"):
            return True

        host = (urllib.parse.urlparse(src).hostname or "").lower()
        return any(
            host == domain or host.endswith("." + domain)
            for domain in ("xiaoheihe.cn", "max-c.com", "myqcloud.com")
        )

    @staticmethod
    def _is_inside_text_container(html_content: str, index: int) -> bool:
        container_tags = ("p", "li", "blockquote", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6")
        for tag in container_tags:
            last_open = html_content.rfind(f"<{tag}", 0, index)
            last_close = html_content.rfind(f"</{tag}>", 0, index)
            if last_open > last_close:
                return True
        return False

    async def _get_signature_query_params(
        self,
        *,
        url: str,
        api_pattern: str = "/bbs/app/",
    ) -> Optional[dict]:
        """拦截一条已签名 GET 请求，提取完整 query 参数。"""
        captured = [None]
        ready = asyncio.Event()

        async def on_response(resp):
            if api_pattern in resp.url and resp.request.method == "GET":
                try:
                    parsed = urllib.parse.urlparse(resp.url)
                    qs = urllib.parse.parse_qs(parsed.query)
                    if qs.get("hkey") and qs.get("_time") and qs.get("nonce"):
                        captured[0] = {key: values[0] for key, values in qs.items() if values}
                        ready.set()
                except Exception:
                    pass

        self._page.on("response", on_response)
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
            try:
                await asyncio.wait_for(ready.wait(), timeout=8.0)
            except asyncio.TimeoutError:
                await asyncio.sleep(2)
        except Exception as e:
            logger.warning("签名获取导航异常: %s", e)
        finally:
            try:
                self._page.remove_listener("response", on_response)
            except Exception:
                pass

        return captured[0]

    async def call_api(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        body: Optional[dict] = None,
        base_url: str = _API_BASE,
    ) -> Optional[dict]:
        url = f"{base_url}{endpoint}"
        try:
            result = await self._page.evaluate(
                """async ({url, method, bodyStr}) => {
                    const options = {
                        method,
                        credentials: 'include',
                        headers: { 'Content-Type': 'application/json' },
                    };
                    if (method !== 'GET' && bodyStr) {
                        options.body = bodyStr;
                    }
                    const resp = await fetch(url, options);
                    return await resp.json();
                }""",
                {
                    "url": url,
                    "method": method.upper(),
                    "bodyStr": json.dumps(body) if body else None,
                },
            )
            if isinstance(result, dict):
                if result.get("status") == "show_captcha":
                    logger.error("Cookie 失效 (验证码): %s", endpoint)
                    return None
                if result.get("status") != "ok":
                    logger.warning("API 返回异常 (status=%s): %s", result.get("status"), endpoint)
                return result
            return None
        except Exception as e:
            logger.error("fetch API 失败 (%s %s): %s", method, url, e)
            return None

    @asynccontextmanager
    async def _intercept(self, api_pattern: str):
        captured: list[Optional[dict]] = [None]
        received = asyncio.Event()

        async def on_response(response):
            if api_pattern in response.url:
                try:
                    captured[0] = json.loads(await response.text())
                    received.set()
                except Exception:
                    pass

        self._page.on("response", on_response)
        try:
            yield captured, received
        finally:
            try:
                self._page.remove_listener("response", on_response)
            except Exception:
                pass

    async def _navigate_and_intercept(
        self,
        link_id: str,
        api_pattern: str,
        url: Optional[str] = None,
    ) -> Optional[dict]:
        if url is None:
            url = f"{_BASE_URL}/app/bbs/link/{link_id}"

        try:
            async with self._intercept(api_pattern) as (captured, received):
                await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    await asyncio.wait_for(received.wait(), timeout=10.0)
                except asyncio.TimeoutError:
                    await asyncio.sleep(2)

            data = captured[0]
            if data is None:
                logger.error("未捕获到有效 API 响应 (url=%s)", url)
                return None
            if data.get("status") == "show_captcha":
                logger.error("Cookie 被验证码拦截，当前链路不可用: %s", url)
                return None
            return data
        except Exception as e:
            logger.error("API 请求失败 (url=%s): %s", url, e)
            return None
