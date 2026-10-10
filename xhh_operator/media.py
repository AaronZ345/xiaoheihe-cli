"""小黑盒网页的 COS 上传协议；临时上传凭据不写入磁盘或输出。"""

import asyncio
import hashlib
import hmac
import json
import math
import mimetypes
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from PIL import Image

from .errors import AuthError, OperatorError, ProtocolError

UPLOAD_BASE = "/bbs/app/api/qcloud/cos/upload/"
MAX_UPLOAD_BYTES = 5 * 1024**3


@dataclass(frozen=True)
class LocalMedia:
    path: Path
    mimetype: str
    size: int
    width: int
    height: int
    duration: float | None = None

    def file_info(self):
        result = {
            "name": self.path.name,
            "mimetype": self.mimetype,
            "fsize": self.size,
            "width": self.width,
            "height": self.height,
        }
        if self.duration is not None:
            result["duration"] = self.duration
        return result

    def preview(self):
        return {"kind": "video" if self.duration is not None else "image", **self.file_info()}


def inspect_image(path):
    path = regular_file(path)
    try:
        with Image.open(path) as image:
            width, height = image.size
            mimetype = Image.MIME.get(image.format)
            image.verify()
        if not mimetype or not mimetype.startswith("image/") or width <= 0 or height <= 0:
            raise ValueError
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ValueError("图片无效或格式不受支持。") from None
    return LocalMedia(path, mimetype, path.stat().st_size, width, height)


def regular_file(path):
    try:
        path = Path(path).expanduser().resolve(strict=True)
        size = path.stat().st_size
        if not path.is_file() or not 0 < size <= MAX_UPLOAD_BYTES:
            raise ValueError
    except (OSError, ValueError):
        raise ValueError("媒体文件不存在、为空或超过 5 GiB 上传上限。") from None
    return path


async def inspect_video(path):
    path = regular_file(path)
    mimetype = mimetypes.guess_type(path.name)[0] or ""
    if not mimetype.startswith("video/"):
        raise ValueError("视频文件类型不受支持。")
    probe = shutil.which("ffprobe")
    if probe:

        def metadata():
            try:
                result = subprocess.run(
                    [
                        probe,
                        "-v",
                        "error",
                        "-show_entries",
                        "stream=codec_type,width,height:format=duration",
                        "-of",
                        "json",
                        str(path),
                    ],
                    capture_output=True,
                    timeout=30,
                    check=True,
                )
                data = json.loads(result.stdout)
                stream = next(s for s in data["streams"] if s.get("codec_type") == "video")
                return stream["width"], stream["height"], float(data["format"]["duration"])
            except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError):
                raise ValueError("无法解析视频的尺寸和时长。") from None

        width, height, duration = await asyncio.to_thread(metadata)
    else:
        # 桌面浏览器读取显式选择的本地文件，不读取浏览器个人资料。
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import async_playwright

        from .browsers import launch_browser

        async with async_playwright() as playwright:
            browser, _ = await launch_browser(playwright, headless=True)
            try:
                page = await browser.new_page()
                await page.goto(path.as_uri(), wait_until="domcontentloaded", timeout=30000)
                info = await page.evaluate("""async () => {
                    const video = document.querySelector('video');
                    if (!video) throw new Error('missing video');
                    if (video.readyState < 1) await new Promise((resolve, reject) => {
                        video.addEventListener('loadedmetadata', resolve, {once: true});
                        video.addEventListener('error', reject, {once: true});
                        setTimeout(() => reject(new Error('metadata timeout')), 15000);
                    });
                    return [video.videoWidth, video.videoHeight, video.duration];
                }""")
                width, height, duration = info
            except (PlaywrightError, ValueError, TypeError):
                raise ValueError("无法解析视频的尺寸和时长；可安装 ffprobe 后重试。") from None
            finally:
                await browser.close()
    if width <= 0 or height <= 0 or not math.isfinite(duration) or duration <= 0:
        raise ValueError("视频的尺寸或时长无效。")
    return LocalMedia(path, mimetype, path.stat().st_size, int(width), int(height), float(duration))


def media_url(value):
    if not isinstance(value, str):
        raise ProtocolError("媒体响应缺少地址。")
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not any(
            host == domain or host.endswith("." + domain)
            for domain in ("max-c.com", "xiaoheihe.cn", "myqcloud.com")
        )
        or any(
            key in parsed.query.lower()
            for key in ("token", "secret", "signature", "q-ak", "q-sign")
        )
    ):
        raise ProtocolError("平台返回了不受支持的媒体地址。")
    return value


def same_asset(left, right):
    if left == right:
        return True
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    parsed = [urlsplit(value) for value in (left, right)]
    if any(
        p.scheme != "https"
        or not any(
            (p.hostname or "") == domain or (p.hostname or "").endswith("." + domain)
            for domain in ("max-c.com", "xiaoheihe.cn", "myqcloud.com")
        )
        for p in parsed
    ):
        return False
    identifiers = [
        {
            value.lower()
            for value in re.findall(r"[a-fA-F0-9]{16,64}", p.path)
            if re.search(r"[a-fA-F]", value)
        }
        for p in parsed
    ]
    return bool(identifiers[0] & identifiers[1])


def cos_authorization(credentials, method, path, headers, start, end):
    """COS SHA1 请求签名；只签真实发送的 Host 与 Content-Type。"""
    key_time = f"{start};{end}"
    canonical = {key.lower(): str(value) for key, value in headers.items()}
    names = sorted(canonical)
    header_text = "&".join(
        quote(key, safe="-_.~") + "=" + quote(canonical[key], safe="-_.~") for key in names
    )
    http_string = f"{method.lower()}\n{path}\n\n{header_text}\n"
    sign_key = hmac.new(
        credentials["tmpSecretKey"].encode(), key_time.encode(), hashlib.sha1
    ).hexdigest()
    to_sign = f"sha1\n{key_time}\n{hashlib.sha1(http_string.encode()).hexdigest()}\n"
    signature = hmac.new(sign_key.encode(), to_sign.encode(), hashlib.sha1).hexdigest()
    return (
        f"q-sign-algorithm=sha1&q-ak={credentials['tmpSecretId']}&q-sign-time={key_time}"
        f"&q-key-time={key_time}&q-header-list={';'.join(names)}&q-url-param-list=&q-signature={signature}"
    )


class MediaUploader:
    def __init__(self, api, *, storage_transport=None):
        self.api = api
        self.storage_transport = storage_transport

    async def upload(self, media):
        info = (
            await self.api.request(
                UPLOAD_BASE + "info/v2",
                form={
                    "file_infos": json.dumps([media.file_info()], ensure_ascii=False),
                    "scope": "bbs",
                    "need_cache": "0",
                },
            )
        ).get("result") or {}
        keys, bucket, region = (
            info.get("keys"),
            info.get("bucket"),
            info.get("region") or "ap-shanghai",
        )
        if (
            not isinstance(keys, list)
            or len(keys) != 1
            or not isinstance(keys[0], str)
            or not keys[0]
            or not isinstance(bucket, str)
            or not re.fullmatch(r"[a-z0-9-]+-\d+", bucket)
            or not isinstance(region, str)
            or not re.fullmatch(r"[a-z]+-[a-z0-9-]+", region)
        ):
            raise ProtocolError("上传信息响应格式已变化。")
        key = keys[0]
        if "?" in key or "#" in key or "\\" in key or ".." in key.split("/"):
            raise ProtocolError("上传对象路径无效。")
        token = (
            await self.api.request(
                UPLOAD_BASE + "token/v2",
                form={
                    "bucket": bucket,
                    "keys": json.dumps([key]),
                    "mimetypes": json.dumps([media.mimetype]),
                    "is_multipart_upload": "0",
                },
            )
        ).get("result") or {}
        credentials = token.get("credentials")
        if not isinstance(credentials, dict) or not all(
            isinstance(credentials.get(k), str) and credentials[k]
            for k in ("tmpSecretId", "tmpSecretKey", "sessionToken")
        ):
            raise ProtocolError("上传凭据响应格式已变化。")
        try:
            start, end = int(token["startTime"]), int(token["expiredTime"])
            if end <= start or end <= time.time():
                raise ValueError
        except (KeyError, ValueError, TypeError):
            raise ProtocolError("上传凭据的有效期无效。") from None
        host = f"{bucket}.cos.{region}.myqcloud.com"
        path = "/" + key.lstrip("/")
        signed_headers = {"host": host, "content-type": media.mimetype}
        headers = {
            **signed_headers,
            "Content-Length": str(media.size),
            "x-cos-security-token": credentials["sessionToken"],
            "Authorization": cos_authorization(
                credentials, "PUT", path, signed_headers, start, end
            ),
        }

        async def chunks():
            with media.path.open("rb") as file:
                while data := await asyncio.to_thread(file.read, 1024 * 1024):
                    yield data

        try:
            async with httpx.AsyncClient(
                transport=self.storage_transport, timeout=900, follow_redirects=False
            ) as storage:
                response = await storage.put(
                    "https://" + host + quote(path, safe="/-_.~"), headers=headers, content=chunks()
                )
        except (httpx.HTTPError, OSError):
            raise OperatorError("媒体上传结果未知，已停止；不会自动重发。", "network", 6) from None
        if response.status_code in (401, 403):
            raise AuthError("媒体上传认证失败，已停止上传。")
        if not response.is_success:
            raise OperatorError(f"媒体上传返回 HTTP {response.status_code}，已停止。")
        result = (
            await self.api.request(
                UPLOAD_BASE + "callback/v2",
                params={"is_finished": "true"},
                form={"keys": json.dumps([key])},
            )
        ).get("result") or {}
        urls = result.get("preview_urls")
        if not isinstance(urls, list) or len(urls) != 1:
            raise ProtocolError("上传完成响应缺少媒体地址；文件已上传，不会重发。")
        thumbs = result.get("thumbs") or []
        return {
            **media.preview(),
            "url": media_url(urls[0]),
            "thumb": media_url(thumbs[0]) if thumbs and thumbs[0] else None,
        }
