"""
小黑盒爬虫API服务器 - 重构版
使用浏览器获取 Cookie 持久化，直接调用后端 API
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import List, Optional

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from api_client import XiaoheiheAPIClient
from browser_manager import BrowserManager
from data_parser import DataParser
from xhh_operator.errors import OperatorError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

browser_manager: Optional[BrowserManager] = None
api_client: Optional[XiaoheiheAPIClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化浏览器和客户端"""
    global browser_manager, api_client

    headless = os.getenv("HEADLESS", "true").lower() == "true"
    port = os.getenv("PORT", "8010")

    logger.info("=" * 60)
    logger.info("小黑盒爬虫API服务器 v2.0")
    logger.info(f"HEADLESS={headless}, PORT={port}")
    logger.info("=" * 60)

    browser_manager = BrowserManager(headless=headless)
    await browser_manager.init()

    api_client = XiaoheiheAPIClient(page=browser_manager.api_page)
    api_client.set_heybox_id(browser_manager.heybox_id)

    logger.info("API服务器准备就绪")
    logger.info("=" * 60)

    yield

    logger.info("正在关闭...")
    if api_client:
        await api_client.close()
    if browser_manager:
        await browser_manager.close()
    logger.info("服务器已关闭")


app = FastAPI(
    title="小黑盒爬虫API",
    description="小黑盒帖子和评论爬取服务（Cookie持久化 + 后端API直连）",
    version="2.0.0",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8010", "http://localhost:8010"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BatchPostRequest(BaseModel):
    urls: List[str] = Field(..., description="帖子URL或ID列表")


class PostResponse(BaseModel):
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="消息")
    data: Optional[dict] = Field(None, description="帖子数据")


class CommentsResponse(BaseModel):
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="消息")
    data: Optional[dict] = Field(None, description="评论数据")
    total: int = Field(0, description="评论总数")


def _extract_link_id(value: str) -> str:
    """从 URL 或纯文本中提取帖子 ID"""
    if value.startswith("http"):
        import re

        match = re.search(r"/link/(\d+)", value)
        if match:
            return match.group(1)
    return value


def operator_http_error(error):
    status = {"auth": 401, "captcha": 428, "rate_limit": 429, "network": 503}.get(error.code, 502)
    return HTTPException(status_code=status, detail={"code": error.code, "message": str(error)})


@app.get("/", tags=["首页"])
async def root():
    """API根路径"""
    return JSONResponse(
        {
            "name": "小黑盒爬虫API",
            "version": "2.0.0",
            "status": "running",
            "auth": "cookie-persistent",
            "docs": "/docs",
            "endpoints": {
                "获取帖子": "GET /api/post/{post_id}",
                "获取评论": "GET /api/post/{post_id}/comments",
                "完整帖子": "GET /api/post/{post_id}/full",
                "批量爬取": "POST /api/posts/batch",
                "刷新Cookie": "POST /api/cookies/refresh",
            },
        }
    )


@app.get("/docs", include_in_schema=False)
async def custom_docs():
    """自定义API文档页面（RapiDoc）"""
    html = """
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>小黑盒爬虫API文档</title>
        <script type="module" src="https://unpkg.com/rapidoc/dist/rapidoc-min.js"></script>
    </head>
    <body>
        <rapi-doc
            spec-url="/openapi.json"
            theme="dark"
            bg-color="#1a1a1a"
            text-color="#ffffff"
            primary-color="#4CAF50"
            nav-bg-color="#252525"
            nav-text-color="#ffffff"
            nav-hover-bg-color="#333333"
            render-style="view"
            layout="column"
            schema-style="table"
            show-header="true"
            allow-try="true"
            allow-server-selection="false"
            allow-authentication="false"
            heading-text="小黑盒爬虫API - Cookie持久化 + API直连"
            show-method-in-nav-bar="as-colored-text"
            use-path-in-nav-bar="true"
        >
            <div slot="overview">
                <h2>爬虫API v2.0</h2>
                <p>Cookie持久化：首次浏览器登录，之后复用</p>
                <p>API直连：绕过前端渲染，直接调用后端接口</p>
                <p>评论分页：支持大量评论的分页获取</p>
                <p>纯JSON输出：标准RESTful API</p>
            </div>
        </rapi-doc>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/api/post/{post_id}", response_model=PostResponse, tags=["帖子"])
async def get_post(post_id: str):
    """
    获取单个帖子（评论作为摘要）

    参数：
    - post_id: 帖子ID（例如：179245676）或完整URL

    示例：
    - http://localhost:8010/api/post/179245676
    """
    link_id = _extract_link_id(post_id)

    try:
        result = await api_client.get_post_comments(link_id, page_num=1, limit=20)

        if not result:
            raise HTTPException(status_code=404, detail="帖子不存在或Cookie已过期")

        post_meta, comments = DataParser.parse_comments_response(result)
        post = DataParser.parse_post_from_comments(
            link_id,
            f"https://www.xiaoheihe.cn/app/bbs/link/{link_id}",
            comments,
            post_meta=post_meta,
        )

        return PostResponse(
            success=True,
            message="成功获取帖子",
            data=post.model_dump(),
        )

    except HTTPException:
        raise
    except OperatorError as error:
        raise operator_http_error(error) from None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@app.get("/api/post/{post_id}/comments", response_model=CommentsResponse, tags=["评论"])
async def get_post_comments(
    post_id: str,
    page: int = Query(1, ge=1, description="页码（从1开始）"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量（最多100）"),
):
    """
    获取帖子的评论列表（分页）

    参数：
    - post_id: 帖子ID
    - page: 页码（默认1）
    - page_size: 每页数量（默认20，最多100）

    示例：
    - http://localhost:8010/api/post/179245676/comments
    - http://localhost:8010/api/post/179245676/comments?page=1&page_size=10
    """
    link_id = _extract_link_id(post_id)

    try:
        result = await api_client.get_post_comments(
            link_id, page_num=page, limit=page_size, is_first=1
        )

        if not result:
            raise HTTPException(status_code=404, detail="帖子不存在或Cookie已过期")

        _, comments = DataParser.parse_comments_response(result)

        total = len(comments)

        return CommentsResponse(
            success=True,
            message=f"成功获取评论（第{page}页）",
            data={
                "comments": [c.model_dump() for c in comments],
                "page": page,
                "page_size": page_size,
            },
            total=total,
        )

    except HTTPException:
        raise
    except OperatorError as error:
        raise operator_http_error(error) from None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@app.get("/api/post/{post_id}/full", tags=["帖子"])
async def get_post_with_comments(post_id: str):
    """
    获取完整帖子（包含所有评论）

    会自动分页获取全部评论数据

    示例：
    - http://localhost:8010/api/post/179245676/full
    """
    link_id = _extract_link_id(post_id)

    try:
        result = await api_client.get_post_full(link_id)

        if not result:
            raise HTTPException(status_code=404, detail="帖子不存在或Cookie已过期")

        post_meta, comments = DataParser.parse_comments_response(result)
        post = DataParser.parse_post_from_comments(
            link_id,
            f"https://www.xiaoheihe.cn/app/bbs/link/{link_id}",
            comments,
            post_meta=post_meta,
        )

        return PostResponse(
            success=True,
            message=f"成功获取完整帖子（{len(comments)} 条评论）",
            data=post.model_dump(),
        )

    except HTTPException:
        raise
    except OperatorError as error:
        raise operator_http_error(error) from None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@app.post("/api/posts/batch", tags=["帖子"])
async def batch_crawl_posts(request: BatchPostRequest, background_tasks: BackgroundTasks):
    """串行读取帖子并返回结果；任一失败即停。"""
    from xhh_operator.session import safe_result

    if not 1 <= len(request.urls) <= 100:
        raise HTTPException(status_code=400, detail="批量读取需要 1 到 100 个帖子。")
    results = []
    try:
        for index, url in enumerate(request.urls):
            if index:
                await asyncio.sleep(2)
            response = await api_client.get_post_comments(
                _extract_link_id(url), page_num=1, limit=20
            )
            if not response:
                raise HTTPException(status_code=502, detail="帖子读取失败，已停止后续请求。")
            results.append(safe_result(response))
        return {
            "success": True,
            "message": "批量读取完成",
            "task_count": len(results),
            "data": results,
        }
    except OperatorError as exc:
        raise operator_http_error(exc) from None


@app.post("/api/cookies/refresh", tags=["系统"])
async def refresh_cookies():
    """
    刷新Cookie

    会重新打开浏览器，让用户重新通过验证码登录
    """
    global browser_manager, api_client

    try:
        if browser_manager:
            await browser_manager.refresh_cookies()

            api_client = XiaoheiheAPIClient(page=browser_manager.api_page)
            api_client.set_heybox_id(browser_manager.heybox_id)

            return JSONResponse(
                {
                    "success": True,
                    "message": "Cookie已刷新",
                    "heybox_id": browser_manager.heybox_id,
                }
            )
        else:
            raise HTTPException(status_code=500, detail="服务器未初始化")

    except HTTPException:
        raise
    except OperatorError as error:
        raise operator_http_error(error) from None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@app.get("/health", tags=["系统"])
async def health_check():
    """健康检查"""
    return JSONResponse(
        {
            "status": "healthy",
            "service": "xiaoheihe-crawler-api",
            "version": "2.0.0",
            "cookies_valid": len(browser_manager.cookies) > 0 if browser_manager else False,
            "heybox_id": browser_manager.heybox_id if browser_manager else None,
        }
    )


class ReviewWriteRequest(BaseModel):
    score: int = Field(..., ge=1, le=5, strict=True)
    text: str = Field(..., min_length=1)
    dry_run: bool = False


class ReviewEditRequest(BaseModel):
    score: Optional[int] = Field(None, ge=1, le=5, strict=True)
    text: Optional[str] = Field(None, min_length=1)
    dry_run: bool = False


async def operator_call(method, *args, **kwargs):
    from xhh_operator.service import Operator
    from xhh_operator.session import safe_result

    try:
        async with Operator() as operator:
            result = await getattr(operator, method)(*args, **kwargs)
        return {"ok": True, "data": safe_result(result)}
    except OperatorError as exc:
        raise operator_http_error(exc) from None
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的操作参数。") from None


@app.get("/api/games")
async def personal_games(offset: int = 0, limit: int = 20):
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(status_code=400, detail="分页参数无效。")
    return await operator_call("games", offset=offset, limit=limit)


@app.get("/api/reviews")
async def personal_reviews(
    platform: str = "steam", offset: int = 0, limit: int = 20, summary: bool = False
):
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(status_code=400, detail="分页参数无效。")
    return await operator_call(
        "reviews", platform=platform, offset=offset, limit=limit, summary=summary
    )


@app.get("/api/reviews/{appid}")
async def personal_review(appid: str):
    from xhh_operator.service import present_review

    result = await operator_call("review", appid)
    result["data"] = present_review(result["data"])
    return result


@app.post("/api/reviews/{appid}")
async def create_personal_review(appid: str, body: ReviewWriteRequest):
    return await operator_call(
        "write_review", appid, score=body.score, content=body.text, dry_run=body.dry_run
    )


@app.patch("/api/reviews/{appid}")
async def edit_personal_review(appid: str, body: ReviewEditRequest):
    if body.score is None and body.text is None:
        raise HTTPException(status_code=400, detail="请提供评分或正文。")
    return await operator_call(
        "write_review", appid, score=body.score, content=body.text, edit=True, dry_run=body.dry_run
    )


@app.delete("/api/reviews/{appid}")
async def delete_personal_review(appid: str, dry_run: bool = False):
    return await operator_call("delete_review", appid, dry_run=dry_run)


class ArticleWriteRequest(BaseModel):
    title: str = Field(..., min_length=1)
    text: str = ""
    tag: int = 11
    draft: bool = True
    dry_run: bool = False
    images: List[str] = Field(default_factory=list)
    communities: List[str] = Field(default_factory=list)
    hashtags: List[str] = Field(default_factory=list)
    post_kind: str = "article"


class VideoWriteRequest(BaseModel):
    title: str = Field(..., min_length=1)
    path: str
    text: str = ""
    cover: Optional[str] = None
    draft: bool = False
    dry_run: bool = True
    communities: List[str] = Field(default_factory=list)
    hashtags: List[str] = Field(default_factory=list)


class MediaUploadRequest(BaseModel):
    path: str
    kind: str = "image"
    dry_run: bool = False


class CommentWriteRequest(BaseModel):
    text: str = ""
    reply_id: str = "-1"
    root_id: str = "-1"
    dry_run: bool = False
    target_text: Optional[str] = None
    images: List[str] = Field(default_factory=list)


@app.get("/api/search")
async def community_search(keyword: str, kind: str = "post", offset: int = 0, limit: int = 20):
    if kind not in ("post", "game", "topic", "user") or offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(status_code=400, detail="搜索参数无效。")
    return await operator_call("search", keyword, kind=kind, offset=offset, limit=limit)


@app.get("/api/posts")
async def own_posts(offset: int = 0, limit: int = 20):
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(status_code=400, detail="分页参数无效。")
    return await operator_call("posts", offset=offset, limit=limit)


@app.post("/api/posts")
async def create_article(body: ArticleWriteRequest):
    if not body.text.strip() and not body.images:
        raise HTTPException(status_code=400, detail="正文或图片不能为空。")
    return await operator_call(
        "write_post",
        body.title,
        body.text,
        tag=body.tag,
        draft=body.draft,
        dry_run=body.dry_run,
        images=body.images,
        communities=body.communities,
        hashtags=body.hashtags,
        post_kind=body.post_kind,
    )


@app.patch("/api/posts/{post_id}")
async def edit_article(post_id: str, body: ArticleWriteRequest):
    return await operator_call(
        "write_post",
        body.title,
        body.text,
        tag=body.tag,
        draft=body.draft,
        postid=post_id,
        dry_run=body.dry_run,
        images=body.images,
        communities=body.communities,
        hashtags=body.hashtags,
        post_kind=body.post_kind,
    )


@app.delete("/api/posts/{post_id}")
async def delete_article(post_id: str, dry_run: bool = False, draft: bool = False):
    return await operator_call("delete_post", post_id, dry_run=dry_run, draft=draft)


@app.post("/api/posts/{post_id}/comments")
async def create_community_comment(post_id: str, body: CommentWriteRequest):
    if not body.text.strip() and not body.images:
        raise HTTPException(status_code=400, detail="评论正文或图片不能为空。")
    if body.target_text is not None and (body.reply_id != "-1" or body.root_id != "-1"):
        raise HTTPException(status_code=400, detail="按正文定位和显式评论 ID 不能同时使用。")
    if (body.reply_id == "-1") != (body.root_id == "-1"):
        raise HTTPException(status_code=400, detail="回复需要同时提供 reply_id 和 root_id。")
    return await operator_call(
        "comment",
        post_id,
        body.text,
        reply_id=body.reply_id,
        root_id=body.root_id,
        dry_run=body.dry_run,
        target_text=body.target_text,
        images=body.images,
    )


@app.get("/api/feed")
async def home_feed(offset: int = 0, limit: int = 20):
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(status_code=400, detail="分页参数无效。")
    return await operator_call("feed", offset=offset, limit=limit)


@app.get("/api/profile")
async def own_profile(limit: int = 10):
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=400, detail="分页参数无效。")
    return await operator_call("profile", limit=limit)


@app.post("/api/media/upload")
async def upload_media(body: MediaUploadRequest):
    return await operator_call("upload_media", body.path, kind=body.kind, dry_run=body.dry_run)


@app.post("/api/videos")
async def create_video(body: VideoWriteRequest):
    return await operator_call(
        "write_video",
        body.title,
        body.path,
        content=body.text,
        cover=body.cover,
        draft=body.draft,
        dry_run=body.dry_run,
        communities=body.communities,
        hashtags=body.hashtags,
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8010"))

    logger.info("服务地址：")
    logger.info(f"  - API文档: http://localhost:{port}/docs")
    logger.info(f"  - 健康检查: http://localhost:{port}/health")
    logger.info(f"  - 获取帖子: http://localhost:{port}/api/post/179245676")
    logger.info(f"  - 刷新Cookie: curl -X POST http://localhost:{port}/api/cookies/refresh")

    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=port, log_level="info")
