"""
⚠️ 废弃 —— 此文件已被 cli.py 完全取代

迁移说明:
    旧命令: python crawler.py 179245676
    新命令: python cli.py get 179245676

保留此文件仅为向后兼容，新功能请使用 cli.py。
"""

import argparse
import asyncio
import json
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def _legacy_main():
    """兼容入口：将旧参数转发给新 CLI"""
    parser = argparse.ArgumentParser(
        description="[废弃] 小黑盒爬虫 CLI（已迁移至 python cli.py）",
        epilog="建议使用: python cli.py get <post_id>",
    )
    parser.add_argument("post_id", nargs="?", help="帖子ID或URL")
    parser.add_argument("--full", action="store_true", help="获取完整帖子")
    parser.add_argument("--output", "-o", help="输出文件路径")
    parser.add_argument("--batch", help="批量爬取：包含帖子ID列表的文本文件（每行一个）")
    parser.add_argument("--headless", action="store_true", default=True, help="无头模式")
    parser.add_argument("--no-headless", action="store_true", help="关闭无头模式")

    args = parser.parse_args()

    if not args.batch and not args.post_id:
        print("⚠️  crawler.py 已废弃，请改用:")
        print("    python cli.py get <post_id>")
        print("    python cli.py --help   # 查看所有命令")
        sys.exit(1)

    # 转发到新 CLI 的内部实现
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from api_client import XiaoheiheAPIClient
    from browser_manager import BrowserManager
    from data_parser import DataParser
    from utils import extract_link_id

    headless = not args.no_headless and args.headless

    link_ids: list[str] = []
    if args.batch:
        with open(args.batch, "r", encoding="utf-8") as f:
            link_ids = [extract_link_id(line) for line in f if line.strip()]
    else:
        link_ids = [extract_link_id(args.post_id)]

    logger.info("正在启动浏览器...")
    browser_manager = BrowserManager(headless=headless)
    await browser_manager.init()
    api_client = XiaoheiheAPIClient(page=browser_manager.api_page)
    api_client.set_heybox_id(browser_manager.heybox_id)

    try:
        results = []
        for i, lid in enumerate(link_ids):
            if i > 0:
                await asyncio.sleep(2.0)
            result = await (
                api_client.get_post_full(lid)
                if args.full
                else api_client.get_post_comments(lid, page_num=1, limit=20)
            )
            if not result:
                results.append({"error": "帖子不存在或Cookie已过期", "post_id": lid})
                continue
            post_meta, comments = DataParser.parse_comments_response(result)
            post = DataParser.parse_post_from_comments(
                lid, f"https://www.xiaoheihe.cn/app/bbs/link/{lid}", comments, post_meta=post_meta
            )
            results.append(post.model_dump())

        output_data = results[0] if len(results) == 1 else results
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            logger.info(f"数据已保存到 {args.output}")
        else:
            print(json.dumps(output_data, ensure_ascii=False, indent=2))
    finally:
        await api_client.close()
        await browser_manager.close()


if __name__ == "__main__":
    asyncio.run(_legacy_main())
