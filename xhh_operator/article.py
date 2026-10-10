"""文章本地图片的预检、位置保留和上传地址替换。"""

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import markdown

from .media import inspect_image, same_asset

_IMG = re.compile(r"<img\b[^>]*>", re.I)
_SRC = re.compile(r"\bsrc=([\"'])(.*?)\1", re.I)
_BARE = re.compile(
    r"(?<![\w\"'=(:/])(?:[A-Za-z]:\\|/)[^\s<>\"']+\.(?:png|jpe?g|gif|webp|bmp)(?=$|[\s<>)])", re.I
)


def semantic_html(value, image_urls=()):
    class Canonical(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.tokens = []

        def handle_starttag(self, tag, attrs):
            attributes = []
            for name, content in attrs:
                if name == "data-original":
                    continue
                if name == "src" and tag == "img":
                    for index, url in enumerate(image_urls):
                        if same_asset(content, url):
                            content = f"image:{index}"
                            break
                attributes.append((name, content))
            self.tokens.append(("start", tag, sorted(attributes)))

        def handle_endtag(self, tag):
            if tag not in ("img", "br", "hr", "input", "meta", "link"):
                self.tokens.append(("end", tag))

        def handle_data(self, data):
            if data:
                self.tokens.append(("text", data))

    parser = Canonical()
    parser.feed(value)
    return parser.tokens


@dataclass
class ArticleTemplate:
    rendered: str
    images: list

    def render(self, urls):
        if len(urls) != len(self.images):
            raise ValueError("图片上传结果数量不一致。")

        def tag(match):
            index = None

            def source(src):
                nonlocal index
                value = html.unescape(src[2])
                if not value.startswith("xhh-upload:"):
                    return src[0]
                index = int(value.split(":", 1)[1])
                return f'src="{html.escape(urls[index], quote=True)}"'

            rendered = _SRC.sub(source, match[0])
            if index is not None:
                image = self.images[index]
                rendered = re.sub(
                    r"\sdata-(?:original|type|width|height)=([\"\x27]).*?\1",
                    "",
                    rendered,
                    flags=re.I,
                )
                rendered = (
                    rendered.rstrip(">").rstrip("/").rstrip()
                    + f' data-original="{html.escape(urls[index], quote=True)}" data-type="image" data-width="{image.width}" data-height="{image.height}">'
                )
            return rendered

        return _IMG.sub(tag, self.rendered)


def prepare_article(content, images=(), *, base_dir=None):
    base = Path(base_dir) if base_dir else Path.cwd()
    segments = re.split(r"(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`]*`)", content)
    for i in range(0, len(segments), 2):
        segments[i] = _BARE.sub(lambda m: f"![local image](<{m[0]}>)", segments[i])
    rendered = markdown.markdown("".join(segments), extensions=["fenced_code", "tables"])
    assets, paths = [], {}

    def add(path):
        media = inspect_image(path)
        if media.path not in paths:
            paths[media.path] = len(assets)
            assets.append(media)
        return f"xhh-upload:{paths[media.path]}"

    def tag(match):
        def source(src):
            value = html.unescape(src[2])
            parsed = urlsplit(value)
            if parsed.scheme in ("http", "https", "data"):
                return src[0]
            if parsed.scheme == "file":
                if parsed.netloc not in ("", "localhost"):
                    raise ValueError("本地图片地址无效。")
                path = Path(unquote(parsed.path))
            else:
                path = Path(unquote(value))
                if not path.is_absolute():
                    path = base / path
            return f'src="{add(path)}"'

        return _SRC.sub(source, match[0])

    rendered = _IMG.sub(tag, rendered)
    for path in images or ():
        path = Path(path).expanduser()
        if not path.is_absolute():
            path = base / path
        original_count = len(assets)
        marker = add(path)
        if len(assets) > original_count:
            rendered += f'<img src="{marker}">'
    return ArticleTemplate(rendered, assets)
