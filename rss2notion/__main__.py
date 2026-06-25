"""
命令行入口：python -m rss2notion
"""

import logging

from .utils.config import Config
from .notion.article import Article
from .notion.subscription import Subscription

from .sync import fetch_subscription, process_subscription

from .notion.client import NotionClient
from .notion.subscription import get_avaliable_subscriptions
from .notion.validation import SchemaValidationError, validate_notion_setup
from concurrent.futures import ThreadPoolExecutor, as_completed

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)
config = Config.from_env()


if __name__ == "__main__":
    client = NotionClient(
        api_key=config.notion_api_key,
        retry_times=config.retry_times,
        retry_delay=config.retry_delay,
        notion_user_id=config.notion_user_id,
    )

    try:
        validate_notion_setup(client, config)
    except SchemaValidationError as e:
        log.error(str(e))
        exit(1)

    # ── 階段零：Notion 獲取訂閲清單──
    try:
        subscriptions = get_avaliable_subscriptions(client, 
            config.subscriptions_datasource_id)
    except Exception as e:
        log.error(f"讀取訂閲數據庫失敗: {e}")
        exit(0)

    if not subscriptions:
        log.warning("沒有可用訂閲，推出")
        exit(0)
    
    # ── 階段一：並發拉取所有 RSS（純網絡 I/O）──
    successed_subscriptions: list[tuple[Subscription, list[Article]]] = []
    max_workers = min(len(subscriptions), 10)  # 避免開太多線程
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_subscription, sub): sub for sub in subscriptions}
        for future in as_completed(futures):
            fetched_subscirption, fetch_result = future.result()

            status_str = ""
            error_str = ""
            if isinstance(fetch_result, Exception):
                status_str = "✗"
                error_str = f" ⚠️  {fetch_result}"
            else: # 成功獲取 FeedResult
                status_str = "✓"
                successed_subscriptions.append((fetched_subscirption, fetch_result))
            
            log.info(f"   RSS 拉取 {status_str} : {fetched_subscirption.name}{error_str}")
            if isinstance(fetch_result, Exception):
                fetched_subscirption.mark_error(client, str(fetch_result))

    # ── 階段二 & 三：串行寫入 Notion 及清理（受速率限制）──
    total_written = total_skipped = total_failed = total_deleted = 0

    for subscription, articles in successed_subscriptions:
        written, skipped, failed, deleted = process_subscription(client, subscription, articles)
        total_written += written
        total_skipped += skipped
        total_failed += failed
        total_deleted += deleted

    log.info(
        f"\n全部完成 — 写入: {total_written}  跳过: {total_skipped}  失败: {total_failed}  刪除: {total_deleted}"
    )
