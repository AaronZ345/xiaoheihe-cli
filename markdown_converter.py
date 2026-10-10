"""
小黑盒 Markdown 兼容格式转换器

将 Markdown/HTML 内容转换为小黑盒编辑器兼容的富文本格式。
解决小黑盒不原生支持代码块、表格等问题。

核心功能:
- 代码块 → Pillow+Pygments 语法高亮图片 (Base64)
- 表格 → Pillow 渲染图片 (Base64)
- 行内代码 `` `code` `` → **加粗** 降级
- 删除线 ~~text~~ → **加粗** 降级
- 外部链接标准化（内部链接保留）
- 本地/相对路径图片提示

用法:
    from markdown_converter import HeyBoxConverter

    converter = HeyBoxConverter()
    html = converter.convert(markdown_text)
    # 或直接从 HTML 输入
    html = converter.convert_html(raw_html)

依赖:
    - Pillow (PIL): 图片渲染
    - pygments: 代码语法高亮
"""

from __future__ import annotations

import base64
import html as html_lib
import io
import mimetypes
import os
import re
from dataclasses import dataclass
from typing import List, Optional

import requests

# 延迟导入，避免无 GUI 环境报错
_PIL_AVAILABLE = False
_PYGMENTS_AVAILABLE = False
_MARKDOWN_AVAILABLE = False


def _check_deps():
    """检查并标记可用依赖。"""
    global _PIL_AVAILABLE, _PYGMENTS_AVAILABLE, _MARKDOWN_AVAILABLE
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401

        _PIL_AVAILABLE = True
    except ImportError:
        pass
    try:
        import pygments  # noqa: F401
        from pygments.formatters import ImageFormatter  # noqa: F401
        from pygments.lexers import get_lexer_by_name  # noqa: F401

        _PYGMENTS_AVAILABLE = True
    except ImportError:
        pass
    try:
        import markdown  # noqa: F401

        _MARKDOWN_AVAILABLE = True
    except ImportError:
        pass


_check_deps()


@dataclass
class ConvertStats:
    """转换统计信息。"""

    code_blocks: int = 0  # 代码块转图片数量
    tables: int = 0  # 表格转图片数量
    inline_codes: int = 0  # 行内代码降级数量
    strikethroughs: int = 0  # 删除线降级数量
    links_fixed: int = 0  # 链接修复数量
    images_fixed: int = 0  # 图片修复数量
    images_embedded: int = 0  # 图片转为 data URL
    images_skipped: int = 0  # 图片无法内嵌

    def summary(self) -> str:
        parts = []
        if self.code_blocks:
            parts.append(f"代码块→{self.code_blocks}张图")
        if self.tables:
            parts.append(f"表格→{self.tables}张图")
        if self.inline_codes:
            parts.append(f"行内代码→{self.inline_codes}处加粗")
        if self.strikethroughs:
            parts.append(f"删除线→{self.strikethroughs}处加粗")
        if self.links_fixed:
            parts.append(f"链接修复{self.links_fixed}")
        if self.images_fixed:
            parts.append(f"图片修复{self.images_fixed}")
        if self.images_embedded:
            parts.append(f"图片内嵌{self.images_embedded}")
        if self.images_skipped:
            parts.append(f"图片降级{self.images_skipped}")
        return ", ".join(parts) if parts else "无需转换"


class HeyBoxConverter:
    """
    小黑盒兼容格式转换器。

    将 Markdown 或 HTML 内容转换为小黑盒编辑器可正确渲染的格式。
    """

    # ---- 配置常量 ----

    # 表格最大宽度（像素）
    TABLE_MAX_WIDTH = 560

    # 单元格内边距
    TABLE_CELL_PADDING = 10

    # 基准行高
    TABLE_LINE_HEIGHT = 36

    # 颜色方案
    COLOR_BG = "#ffffff"
    COLOR_TABLE_HEADER = "#f5f5f5"
    COLOR_TABLE_BORDER = "#e0e0e0"
    COLOR_TEXT = "#333333"
    COLOR_CODE_BG = "#f6f8fa"
    MAX_INLINE_IMAGE_BYTES = 5 * 1024 * 1024
    REMOTE_IMAGE_TIMEOUT = 12
    INTERNAL_IMAGE_HOST_SUFFIXES = ("xiaoheihe.cn", "max-c.com")

    def __init__(self):
        self.stats = ConvertStats()

    def convert(self, text: str, source_format: str = "auto") -> str:
        """
        转换文本为小黑盒兼容 HTML。

        Args:
            text: 输入内容（Markdown 或 HTML）
            source_format: 'auto' | 'markdown' | 'html'

        Returns:
            兼容小黑盒的 HTML 字符串
        """
        self.stats = ConvertStats()

        if not text or not text.strip():
            return ""

        # 自动检测格式
        if source_format == "auto":
            source_format = self._detect_format(text)

        if source_format == "markdown":
            return self._convert_markdown(text)
        else:
            return self._convert_html(text)

    def convert_html(self, html: str) -> str:
        """从 HTML 输入转换的快捷方法。"""
        return self.convert(html, source_format="html")

    def convert_markdown(self, md: str) -> str:
        """从 Markdown 输入转换的快捷方法。"""
        return self.convert(md, source_format="markdown")

    # ==================== 格式检测 ====================

    @staticmethod
    def _detect_format(text: str) -> str:
        """简单启发式检测输入是 Markdown 还是 HTML。"""
        stripped = text.strip()
        if stripped.startswith("<") and any(
            tag in stripped[:50].lower()
            for tag in ("<p>", "<div>", "<h", "<br", "<img", "<table", "<pre", "<code")
        ):
            return "html"
        return "markdown"

    @staticmethod
    def _render_markdown_html(md_text: str) -> str:
        """
        将 Markdown 转成基础 HTML。
        优先使用 python-markdown，与参考编辑器的“先解析 Markdown 再导出 HTML”思路保持一致。
        """
        if _MARKDOWN_AVAILABLE:
            import markdown

            return markdown.markdown(
                md_text,
                extensions=[
                    "extra",
                    "sane_lists",
                    "nl2br",
                ],
                output_format="xhtml",
            )

        # 兜底：保留旧行为，至少能输出基础段落结构
        return HeyBoxConverter._wrap_paragraphs(md_text)

    # ==================== Markdown 转换主流程 ====================

    def _convert_markdown(self, md: str) -> str:
        """Markdown → 小黑盒兼容 HTML 的完整流水线。"""
        result = md

        # Phase 1: 代码块 → 图片
        result = self._process_code_blocks(result)

        # Phase 2: 表格 → 图片
        result = self._process_tables(result)

        # Phase 3: 本地图片处理
        result = self._process_local_images(result)

        # Phase 4: 格式标准化（行内代码、删除线、链接等）
        result = self._normalize_markdown_format(result)

        # Phase 5: Markdown → HTML
        html = self._render_markdown_html(result)

        # Phase 6: 再走 HTML 兼容化，输出更接近编辑器复制出的结构
        return self._convert_html(html)

    # ==================== HTML 转换主流程 ====================

    def _convert_html(self, html: str) -> str:
        """HTML → 小黑盒兼容 HTML 的完整流水线。"""
        result = html

        # Phase 1: <pre><code> 代码块 → 图片
        result = self._process_html_code_blocks(result)

        # Phase 2: <table> 表格 → 图片
        result = self._process_html_tables(result)

        # Phase 3: 尽量将站外图/本地图转成 data URL，减少发稿后失效
        result = self._inline_html_images(result)

        # Phase 4: <code> 行内代码 → 加粗
        result = self._process_html_inline_code(result)

        # Phase 5: <del>/<s> 删除线 → 加粗
        result = self._process_html_strikethrough(result)

        # Phase 6: 链接标准化
        result = self._normalize_links(result)

        # Phase 7: 输出结构收敛为更保守的 HTML 子集
        result = self._normalize_html_structure(result)

        return result.strip()

    # ================================================================
    #  代码块处理（Markdown 和 HTML 两套路径）
    # ================================================================

    def _process_code_blocks(self, text: str) -> str:
        """
        Markdown 代码块 ``` ... ``` → Base64 图片。
        支持指定语言：```python, ```javascript 等。
        """

        def replace_code_block(match):
            lang = match.group(1) or ""
            code_content = match.group(2).rstrip("\n")

            if not code_content.strip():
                return ""

            img_html = self._render_code_image(code_content, lang)
            if "<img " in img_html:
                self.stats.code_blocks += 1
            return img_html

        # 匹配 fenced code block: ```lang\n...\n```
        return re.sub(
            r"```(\w*)\n([\s\S]*?)```",
            replace_code_block,
            text,
            flags=re.MULTILINE,
        )

    def _process_html_code_blocks(self, html: str) -> str:
        """HTML <pre><code>...</code></pre> → Base64 图片。"""

        def replace_pre_block(match):
            pre_content = match.group(1)
            # 提取语言标识（通常在 class 里）
            lang = ""
            lang_match = re.search(r"language-(\w+)", pre_content)
            if lang_match:
                lang = lang_match.group(1)

            # 提取纯代码内容（去掉标签）
            code_match = re.search(r"<code[^>]*>([\s\S]*?)</code>", pre_content)
            code_content = code_match.group(1) if code_match else pre_content
            # HTML 解码常见实体
            code_content = code_content.replace("&lt;", "<").replace("&gt;", ">")
            code_content = code_content.replace("&amp;", "&").replace("&quot;", '"')

            if not code_content.strip():
                return match.group(0)  # 保持原样

            img_html = self._render_code_image(code_content, lang)
            if "<img " in img_html:
                self.stats.code_blocks += 1
            return img_html

        return re.sub(
            r"<pre\b[^>]*>([\s\S]*?)</pre>",
            replace_pre_block,
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )

    # ================================================================
    #  表格处理
    # ================================================================

    def _process_tables(self, text: str) -> str:
        """
        Markdown 表格 → Base64 图片。

        匹配标准 GFM 表格:
        | Header1 | Header2 |
        |---------|---------|
        | Cell1   | Cell2   |
        """

        def find_table_end(start_idx: int, lines: List[str]) -> int:
            """找到表格结束位置（连续表格行之后）。"""
            i = start_idx
            while i < len(lines):
                line = lines[i].strip()
                if line.startswith("|") or (
                    line.startswith("-") or line.startswith(":") and "|" in line
                ):
                    i += 1
                else:
                    break
            return i

        lines = text.split("\n")
        result_lines: List[str] = []
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            # 检测表头行（至少包含一个 | 且非分隔符行）
            if "|" in line and not re.match(r"^[\s|:\-]+$", line):
                # 检查下一行是否是分隔符
                if i + 1 < len(lines) and re.match(r"^[\s|:\-]+$", lines[i + 1].strip()):
                    # 找到表格结束位置
                    table_end = find_table_end(i + 2, lines)
                    table_lines = lines[i:table_end]
                    table_md = "\n".join(table_lines)

                    img_html = self._render_table_image(table_md)
                    if img_html:
                        result_lines.append(img_html)
                        self.stats.tables += 1
                    else:
                        result_lines.extend(table_lines)

                    i = table_end
                    continue

            result_lines.append(lines[i])
            i += 1

        return "\n".join(result_lines)

    def _process_html_tables(self, html: str) -> str:
        """HTML <table>...</table> → Base64 图片。"""

        def replace_table(match):
            table_content = match.group(0)
            img_html = self._render_table_from_html(table_content)
            if img_html:
                self.stats.tables += 1
                return img_html
            return match.group(0)  # 渲染失败则保持原样

        return re.sub(
            r"<table\b[\s\S]*?</table>",
            replace_table,
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )

    # ================================================================
    #  格式降级与标准化
    # ================================================================

    def _normalize_markdown_format(self, text: str) -> str:
        """Markdown 格式降级处理。"""

        # 行内代码 `code` → **code**
        def replace_inline_code(m):
            self.stats.inline_codes += 1
            return f"**{m.group(1)}**"

        text = re.sub(r"`([^`\n]+)`", replace_inline_code, text)

        # 删除线 ~~text~~ → **text**
        def replace_strikethrough(m):
            self.stats.strikethroughs += 1
            return f"**{m.group(1)}**"

        text = re.sub(r"~~([^~]+)~~", replace_strikethrough, text)

        # 链接处理
        text = self._normalize_links(text)

        return text

    def _process_html_inline_code(self, html: str) -> str:
        """HTML <code>（非 pre 内）→ <strong>。"""

        def replace(m):
            content = m.group(1)
            # 跳过已经在 pre 块内的（已由 _process_html_code_blocks 处理）
            last_pre_open = html.rfind("<pre", 0, m.start())
            last_pre_close = html.rfind("</pre>", 0, m.start())
            if last_pre_open != -1 and last_pre_open > last_pre_close:
                return m.group(0)
            self.stats.inline_codes += 1
            return f"<strong>{content}</strong>"

        return re.sub(r"<code\b[^>]*>([\s\S]*?)</code>", replace, html, flags=re.IGNORECASE)

    def _process_html_strikethrough(self, html: str) -> str:
        """HTML <del>/<s> → <strong>。"""

        def replace(m):
            self.stats.strikethroughs += 1
            return f"<strong>{m.group(1)}</strong>"

        html = re.sub(r"<del>([\s\S]*?)</del>", replace, html, flags=re.DOTALL)
        html = re.sub(r"<s>([\s\S]*?)</s>", replace, html, flags=re.DOTALL | re.IGNORECASE)
        return html

    def _normalize_links(self, text: str) -> str:
        """链接标准化：保留小黑盒内部链接，外部链接展开。"""

        def process_markdown_link(m):
            is_image = m.group(1) == "!"
            link_text = m.group(2)
            url = m.group(3).strip()

            if is_image:
                return m.group(0)

            if re.match(r"https?://www\.xiaoheihe\.cn/app/bbs/link/", url, re.IGNORECASE):
                return m.group(0)

            self.stats.links_fixed += 1
            clean_url = url.split("?")[0]
            return f"**{link_text}**（{clean_url}）"

        def process_html_link(m):
            url = html_lib.unescape(m.group(3).strip())
            inner = m.group(4)

            if re.match(r"https?://www\.xiaoheihe\.cn/app/bbs/link/", url, re.IGNORECASE):
                safe_href = html_lib.escape(url, quote=True)
                return f'<a href="{safe_href}">{inner}</a>'

            self.stats.links_fixed += 1
            clean_url = url.split("?")[0]
            link_text = re.sub(r"<[^>]+>", "", inner).strip() or clean_url
            safe_text = html_lib.escape(link_text)
            safe_url = html_lib.escape(clean_url)
            return f"<strong>{safe_text}</strong>（{safe_url}）"

        result = re.sub(r"(!?)\[([^\]]*)\]\(([^)]+)\)", process_markdown_link, text)
        result = re.sub(
            r"<a\b([^>]*?)href=(['\"])(.*?)\2[^>]*>([\s\S]*?)</a>",
            process_html_link,
            result,
            flags=re.IGNORECASE,
        )

        return result

    def _process_local_images(self, text: str) -> str:
        """将 Markdown 图片尽量转换为小黑盒更容易接受的形式。"""

        def replace_markdown_img(match):
            alt = (match.group(1) or "图片").strip()
            src = (match.group(2) or "").strip()
            resolved_src = self._resolve_image_source(src)

            if resolved_src:
                if resolved_src != src:
                    self.stats.images_fixed += 1
                return f"![{alt}]({resolved_src})"

            self.stats.images_fixed += 1
            return f"\n（图片：{alt} {src}）\n"

        return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_markdown_img, text)

    @staticmethod
    def _wrap_paragraphs(text: str) -> str:
        """将裸文本段落包裹在 <p> 标签中。"""
        lines = text.split("\n")
        result: List[str] = []
        current_para: List[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_para:
                    result.append(f"{''.join(current_para)}")
                    current_para = []
                continue

            # 已经是 HTML 标签的行直接保留
            if stripped.startswith("<") and not stripped.startswith("**"):
                if current_para:
                    result.append(f"{''.join(current_para)}")
                    current_para = []
                result.append(stripped)
                continue

            current_para.append(line)

        if current_para:
            result.append(f"{''.join(current_para)}")

        return "\n".join(result)

    @staticmethod
    def _normalize_html_structure(html: str) -> str:
        """将 HTML 收敛到更适合小黑盒的保守标签集合。"""
        result = html or ""
        result = re.sub(r"<!--[\s\S]*?-->", "", result)

        # 常见块容器压成段落，尽量贴近编辑器复制出的结构
        result = re.sub(r"<div\b[^>]*>", "<p>", result, flags=re.IGNORECASE)
        result = re.sub(r"</div>", "</p>", result, flags=re.IGNORECASE)
        result = re.sub(r"</?(?:span|font)\b[^>]*>", "", result, flags=re.IGNORECASE)

        # 标准化换行与分隔
        result = re.sub(r"<br\s*/?>", "<br />", result, flags=re.IGNORECASE)
        result = re.sub(r"<hr\b[^>]*>", "<hr />", result, flags=re.IGNORECASE)

        # 图片只保留 src / alt
        result = re.sub(
            r"<img\b[^>]*>",
            HeyBoxConverter._sanitize_img_tag,
            result,
            flags=re.IGNORECASE,
        )

        # 内部链接只保留 href
        result = re.sub(
            r"<a\b[^>]*href=(['\"])(.*?)\1[^>]*>",
            HeyBoxConverter._sanitize_anchor_open_tag,
            result,
            flags=re.IGNORECASE,
        )

        # 常见标签去掉 style/class 等属性
        simple_tags = (
            "p",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "ul",
            "ol",
            "li",
            "blockquote",
            "strong",
            "em",
            "code",
            "pre",
            "table",
            "thead",
            "tbody",
            "tr",
            "td",
            "th",
        )
        result = re.sub(
            rf"<({'|'.join(simple_tags)})\b[^>]*>",
            lambda m: f"<{m.group(1).lower()}>",
            result,
            flags=re.IGNORECASE,
        )

        result = re.sub(r"<p>\s*</p>", "", result, flags=re.IGNORECASE)
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()

    @staticmethod
    def _sanitize_img_tag(match) -> str:
        tag = match.group(0)
        src_match = re.search(r"\bsrc=(['\"])(.*?)\1", tag, flags=re.IGNORECASE)
        if not src_match:
            return ""

        alt_match = re.search(r"\balt=(['\"])(.*?)\1", tag, flags=re.IGNORECASE)
        src = html_lib.escape(html_lib.unescape(src_match.group(2)), quote=True)
        alt = (
            html_lib.escape(html_lib.unescape(alt_match.group(2)), quote=True) if alt_match else ""
        )
        return f'<img src="{src}" alt="{alt}" />'

    @staticmethod
    def _sanitize_anchor_open_tag(match) -> str:
        href = html_lib.escape(html_lib.unescape(match.group(2)), quote=True)
        return f'<a href="{href}">'

    def _inline_html_images(self, html: str) -> str:
        """将 HTML 中的图片地址尽量转成可直接发布的 data URL。"""

        def replace_img(match):
            tag = match.group(0)
            src_match = re.search(r"\bsrc=(['\"])(.*?)\1", tag, flags=re.IGNORECASE)
            if not src_match:
                return ""

            raw_src = html_lib.unescape(src_match.group(2)).strip()
            alt_match = re.search(r"\balt=(['\"])(.*?)\1", tag, flags=re.IGNORECASE)
            alt = html_lib.unescape(alt_match.group(2)).strip() if alt_match else "图片"
            resolved_src = self._resolve_image_source(raw_src)

            if not resolved_src:
                self.stats.images_fixed += 1
                safe_alt = html_lib.escape(alt)
                safe_src = html_lib.escape(raw_src)
                return f"<p>（图片：{safe_alt} {safe_src}）</p>"

            if resolved_src != raw_src:
                self.stats.images_fixed += 1

            safe_src = html_lib.escape(resolved_src, quote=True)
            safe_alt = html_lib.escape(alt, quote=True)
            return f'<img src="{safe_src}" alt="{safe_alt}" />'

        return re.sub(r"<img\b[^>]*>", replace_img, html, flags=re.IGNORECASE)

    def _resolve_image_source(self, src: str) -> Optional[str]:
        src = html_lib.unescape((src or "").strip())
        if not src:
            return None

        if src.startswith("data:image/"):
            return src

        if self._is_internal_image_url(src):
            return src

        if re.match(r"^https?://", src, re.IGNORECASE):
            return self._download_remote_image_as_data_url(src)

        return self._read_local_image_as_data_url(src)

    def _read_local_image_as_data_url(self, src: str) -> Optional[str]:
        path_str = src
        if src.startswith("file://"):
            path_str = re.sub(r"^file://", "", src, flags=re.IGNORECASE)
            if os.name == "nt" and re.match(r"^/[A-Za-z]:", path_str):
                path_str = path_str[1:]

        path_str = os.path.expanduser(path_str)
        if not os.path.isabs(path_str):
            path_str = os.path.join(os.getcwd(), path_str)

        if not os.path.isfile(path_str):
            self.stats.images_skipped += 1
            return None

        try:
            if os.path.getsize(path_str) > self.MAX_INLINE_IMAGE_BYTES:
                self.stats.images_skipped += 1
                return None

            mime_type = mimetypes.guess_type(path_str)[0] or "application/octet-stream"
            if not mime_type.startswith("image/"):
                self.stats.images_skipped += 1
                return None

            with open(path_str, "rb") as f:
                raw = f.read()

            self.stats.images_embedded += 1
            return f"data:{mime_type};base64,{base64.b64encode(raw).decode('ascii')}"
        except OSError:
            self.stats.images_skipped += 1
            return None

    def _download_remote_image_as_data_url(self, src: str) -> Optional[str]:
        try:
            response = requests.get(
                src,
                timeout=self.REMOTE_IMAGE_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()
        except Exception:
            self.stats.images_skipped += 1
            return None

        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            self.stats.images_skipped += 1
            return None

        content = response.content
        if len(content) > self.MAX_INLINE_IMAGE_BYTES:
            self.stats.images_skipped += 1
            return None

        self.stats.images_embedded += 1
        return f"data:{content_type};base64,{base64.b64encode(content).decode('ascii')}"

    def _is_internal_image_url(self, src: str) -> bool:
        match = re.match(r"^https?://([^/]+)", src, re.IGNORECASE)
        if not match:
            return False

        host = match.group(1).lower()
        return any(host.endswith(suffix) for suffix in self.INTERNAL_IMAGE_HOST_SUFFIXES)

    # ================================================================
    #  图片渲染引擎（需要 Pillow + Pygments）
    # ================================================================

    def _render_code_image(self, code: str, lang: str = "") -> str:
        """
        将代码渲染为带语法高亮的 PNG 图片，返回 HTML <img> 标签。
        如果依赖不可用则回退到 <pre> 文本块。
        """
        if not (_PIL_AVAILABLE and _PYGMENTS_AVAILABLE):
            escaped = html_lib.escape(code)
            return f"<pre><code>{escaped}</code></pre>"

        import pygments
        from pygments.formatters import ImageFormatter
        from pygments.lexers import get_lexer_by_name, guess_lexer

        try:
            # 选择词法分析器
            if lang:
                try:
                    lexer = get_lexer_by_name(lang, stripall=True)
                except Exception:
                    lexer = guess_lexer(code)
            else:
                lexer = guess_lexer(code)

            # 配置图片格式化器
            formatter = ImageFormatter(
                style="friendly",
                linenos=False,
                font_size=14,
                line_padding=4,
                image_pad=16,
                background_color=self.COLOR_CODE_BG,
            )

            # 渲染
            png_data = pygments.highlight(code, lexer, formatter)

            # 转 Base64
            b64 = base64.b64encode(png_data).decode("ascii")
            return f'<img src="data:image/png;base64,{b64}" alt="代码块" />'

        except Exception:
            escaped = html_lib.escape(code)
            return f"<pre><code>{escaped}</code></pre>"

    def _render_table_image(self, table_md: str) -> Optional[str]:
        """
        将 Markdown 表格渲染为 PNG 图片，返回 HTML <img> 标签。
        返回 None 表示渲染失败。
        """
        if not _PIL_AVAILABLE:
            return None

        parsed = self._parse_markdown_table(table_md)
        if not parsed:
            return None

        headers, rows = parsed
        return self._draw_table(headers, rows)

    def _render_table_from_html(self, table_html: str) -> Optional[str]:
        """将 HTML 表格渲染为 PNG 图片。"""
        if not _PIL_AVAILABLE:
            return None

        headers, rows = self._parse_html_table(table_html)
        if not rows and not headers:
            return None

        return self._draw_table(headers, rows)

    # ================================================================
    #  表格解析器
    # ================================================================

    @staticmethod
    def _parse_markdown_table(md_text: str):
        """
        解析 Markdown GFM 表格。
        返回 (headers: list[str], rows: list[list[str]]) 或 None。
        """
        lines = md_text.strip().split("\n")
        if len(lines) < 2:
            return None

        def parse_row(line: str) -> List[str]:
            cells = line.split("|")
            cells = [c.strip() for c in cells]
            # 去掉首尾空单元格
            if cells and cells[0] == "":
                cells.pop(0)
            if cells and cells[-1] == "":
                cells.pop()
            return cells

        headers = parse_row(lines[0])

        # 跳过分隔符行
        data_lines = [line for line in lines[1:] if not re.match(r"^[\s|:\-]+$", line)]
        rows = [parse_row(line) for line in data_lines if line.strip()]

        if not headers:
            return None

        return headers, rows

    @staticmethod
    def _parse_html_table(html: str):
        """解析 HTML 表格。"""
        headers: List[str] = []
        rows: List[List[str]] = []

        # 提取表头
        th_matches = re.findall(r"<th[^>]*>([\s\S]*?)</th>", html, re.IGNORECASE)
        headers = [re.sub(r"<[^>]+>", "", h).strip() for h in th_matches if h.strip()]

        # 提取行
        tr_matches = re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", html, re.IGNORECASE)
        is_header_row = True
        for tr in tr_matches:
            td_matches = re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", tr, re.IGNORECASE)
            cells = [re.sub(r"<[^>]+>", "", cell).strip() for cell in td_matches if cell.strip()]
            if not is_header_row and cells:
                rows.append(cells)
            is_header_row = False

        return headers, rows

    # ================================================================
    #  表格绘制引擎（Pillow）
    # ================================================================

    def _draw_table(self, headers: List[str], rows: List[List[str]]) -> Optional[str]:
        """用 Pillow 绘制表格并返回 Base64 HTML img 标签。"""
        from PIL import Image, ImageDraw, ImageFont

        try:
            # 尝试加载字体
            font = self._load_font(size=14)
            bold_font = self._load_font(size=14, bold=True)
            if not font or not bold_font:
                font = bold_font = ImageFont.load_default()

            all_rows = [headers] + rows

            # 计算列宽
            num_cols = max((len(row) for row in all_rows), default=0)
            col_widths = [0] * num_cols

            for row in all_rows:
                for idx, cell in enumerate(row):
                    if idx < num_cols:
                        wrapped = self._wrap_text(cell, font, self.TABLE_MAX_WIDTH // num_cols)
                        w = (
                            max(HeyBoxConverter._get_text_size(font, line)[0] for line in wrapped)
                            if wrapped
                            else 0
                        )
                        col_widths[idx] = max(col_widths[idx], w)

            # 加上内边距
            col_widths = [w + self.TABLE_CELL_PADDING * 2 for w in col_widths]

            total_width = min(sum(col_widths), self.TABLE_MAX_WIDTH)
            header_h = self.TABLE_LINE_HEIGHT
            row_h = self.TABLE_LINE_HEIGHT
            total_height = header_h + row_h * len(rows) + 2  # 边框

            # 创建画布
            img = Image.new("RGB", (total_width, total_height), self.COLOR_BG)
            draw = ImageDraw.Draw(img)

            # 绘制表头背景
            draw.rectangle([0, 0, total_width, header_h], fill=self.COLOR_TABLE_HEADER)
            draw.line([0, header_h, total_width, header_h], fill=self.COLOR_TABLE_BORDER, width=1)

            y = 0
            for row_idx, row in enumerate(all_rows):
                x = 0
                f = bold_font if row_idx == 0 else font
                for col_idx, cell in enumerate(row):
                    if col_idx >= num_cols:
                        break
                    cw = col_widths[col_idx]
                    # 文字绘制（左对齐，垂直居中）
                    text_y = (
                        y
                        + (header_h if row_idx == 0 else row_h) // 2
                        - (HeyBoxConverter._get_text_size(f, cell)[1] // 2)
                    )
                    draw.text(
                        (x + self.TABLE_CELL_PADDING, text_y),
                        cell,
                        fill=self.COLOR_TEXT,
                        font=f,
                    )
                    # 列分隔线
                    x += cw
                    if col_idx < num_cols - 1:
                        draw.line(
                            [x, y, x, y + (header_h if row_idx == 0 else row_h)],
                            fill=self.COLOR_TABLE_BORDER,
                            width=1,
                        )

                y += header_h if row_idx == 0 else row_h
                # 行分隔线
                if row_idx > 0:
                    draw.line([0, y, total_width, y], fill=self.COLOR_TABLE_BORDER, width=1)

            # 外边框
            draw.rectangle(
                [0, 0, total_width - 1, total_height - 1], outline=self.COLOR_TABLE_BORDER, width=1
            )

            # 导出为 Base64
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")

            return f'<img src="data:image/png;base64,{b64}" alt="表格" />'

        except Exception as e:
            logger_error = __import__("logging").getLogger(__name__).error
            logger_error("表格渲染失败: %s", e)
            return None

    @staticmethod
    def _get_text_size(font, text: str) -> tuple[int, int]:
        """兼容 Pillow 9/10 的文字尺寸获取。"""
        try:
            # Pillow 9.x
            return font.getsize(text)
        except AttributeError:
            # Pillow 10+: 用 textbbox
            bbox = font.getbbox(text)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]

    @staticmethod
    def _load_font(size: int = 14, bold: bool = False):
        """尝试加载系统字体，失败返回 None。"""
        from PIL import ImageFont

        font_names = []
        import platform

        system = platform.system()

        if system == "Windows":
            font_names = ["msyh.ttc", "simhei.ttf"]  # 微软雅黑 / 黑体
        elif system == "Darwin":  # macOS
            font_names = ["PingFang SC.ttc", "Arial Unicode.ttf"]
        else:  # Linux
            font_names = [
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "DejaVuSans.ttf",
            ]

        for name in font_names:
            try:
                return ImageFont.truetype(name, size)
            except (IOError, OSError):
                continue

        return None

    @staticmethod
    def _wrap_text(text: str, font, max_width: int) -> List[str]:
        """按像素宽度自动折行（支持 CJK 字符）。"""
        if not text:
            return []

        chars = list(text)
        lines: List[str] = []
        current_line = ""
        current_width = 0

        for char in chars:
            char_w = HeyBoxConverter._get_text_size(font, char)[0]
            # CJK 字符宽度约等于 2 个 ASCII 字符
            char_w = char_w if ord(char) > 127 else char_w

            if current_width + char_w > max_width and current_line:
                lines.append(current_line)
                current_line = char
                current_width = char_w
            else:
                current_line += char
                current_width += char_w

        if current_line:
            lines.append(current_line)

        return lines if lines else [text]
