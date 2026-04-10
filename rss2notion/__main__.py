"""
命令行入口：python -m rss2notion
"""

import logging

import time
from datetime import datetime, timedelta

from .utils.config import Config
from .utils.html2notion_block import html_to_notion_blocks

from .models import Subscription, RSSEntry

from .sync import fetch_subscription, fetch_failed, fetch_success

from .notion.client import NotionClient
from .notion.cleanup import cleanup_expired_articles
from .notion.subscription import get_avaliable_subscriptions

from concurrent.futures import ThreadPoolExecutor, as_completed

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

if __name__ == "__main__":
    config = Config.from_env()
    log = logging.getLogger(__name__)
    """主同步流程"""
    client = NotionClient(
        api_key=config.notion_api_key,
        retry_times=config.retry_times,
        retry_delay=config.retry_delay,
    )

    # 获取所有活跃订阅
    try:
        subscriptions = get_avaliable_subscriptions(client, 
            config.feeds_database_id, 
            config.entries_database_id)
    except Exception as e:
        log.error(f"读取订阅数据库失败: {e}")
        exit(0)

    if not subscriptions:
        log.warning("没有活跃的订阅，退出")
        exit(0)
    
    # ── 階段一：並發拉取所有 RSS（純網絡 I/O）──
    successed_subscriptions: list[tuple[Subscription, list[RSSEntry]]] = []
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
                fetch_failed(client, fetched_subscirption, str(fetch_result))

    # ── 階段二：串行寫入 Notion（受速率限制）──
    total_written = total_skipped = total_failed = total_deleted = 0

    for subscription, entries in successed_subscriptions:
        log.info(f"── 处理订阅: {subscription.name or subscription.url}")

        before_filter = len(entries)

        # 时间粗筛：减少进入 URL 去重阶段的条目数
        import_days = 1
        is_overwrite_str = ""
        if (subscription.fetch_days is not None) and len(subscription.existing_articles)>0:
            import_days = subscription.fetch_days
            is_overwrite_str = " (覆寫默認) "
        else:
            import_days = config.cleanup_days

        import_msg = ""
        if import_days > 0:
            cutoff = (datetime.now(config.timezone) - timedelta(days=import_days)).replace(hour=0,minute=0,second=0, microsecond=0)
            entries = [e for e in entries if e.published >= cutoff]
            import_msg = f"{is_overwrite_str}最近 {import_days} 天 (自 {cutoff})"
        else: # 無時限時限定導入的最大數量 (避免全量導入)
            import_msg = f"歷史 {config.max_import_count} 篇"
            entries = entries[:config.max_import_count]

        if subscription.fetch_amount: # 根據訂閱源配置再篩最新的指定篇數
            entries = entries[:subscription.fetch_amount]
            import_msg += f" 最近 {subscription.fetch_amount} 篇"

        if not entries:
            log.info("   没有新文章，跳过")
            fetch_success(client, subscription)
            continue
        else:
            log.info(f"   導入文章：{import_msg} ({before_filter} → {len(entries)})")

        written = skipped = failed = 0
        failed_entries: list[dict] = []  # 收集失败的文章信息（标题 + 错误消息）

        for idx, entry in enumerate(entries, 1):
            log.debug(f"   [{idx}/{len(entries)}] {entry.title[:60]}")

            skip_msg = ""
            # URL 去重
            if entry.url and entry.url in subscription.existing_articles:
                skip_msg = "Notion 已存在相同文章"

            # 去除標題或URL 含有關鍵字的 entry
            for keyword in subscription.filterout_keywords:
                if keyword in (entry.title + entry.url): 
                    skip_msg = f"匹配到關鍵字: [{keyword}]"
                    log.info(f"   {entry.title} {skip_msg}，跳過") # dev test info
                    break

            if skip_msg: 
                log.debug(f"   跳過: {skip_msg}")
                skipped += 1
                continue

            try:
                # 默認獲取 Feed 内提供的 content 或 summery 内容
                # all_blocks = entry_to_notion_blocks(entry)
                all_blocks = []
                first_batch = []
                rest_blocks = []
                if entry.content_html:
                    all_blocks = html_to_notion_blocks(entry.content_html)
                    first_batch = all_blocks[:config.notion_block_limit]
                    rest_blocks = all_blocks[config.notion_block_limit:]

                    img_count = sum(1 for b in all_blocks if b.get("type") == "image")
                    log.debug(f"    blocks: {len(all_blocks)} 个（含 {img_count} 张图片）")

                page = client.create_page(
                    database_id=config.entries_database_id,
                    entry=entry,
                    source_page_id=subscription.page_id,
                    blocks=first_batch,
                )
                page_id = page["id"]

                if rest_blocks:
                    client.append_blocks(page_id, rest_blocks)
                
                client.lock_page(page_id) # Auto lock to prevent accidental modification in database UI

                log.info(f"    ✓ 写入: {entry.title}")
                log.info(f"    ------- {page['url']}")
                subscription.existing_articles.append(entry.url)
                written += 1

                time.sleep(0.334)  # 控制 Notion API 速率，免費版 3 requests/second

            except Exception as e:
                log.error(f"    ✗ 写入失败: {e}")
                failed_entries.append({
                    "title": entry.title[:60],
                    "error": str(e)[:100],  # 截断错误消息
                })
                failed += 1

        total_written += written
        total_skipped += skipped
        total_failed += failed

        # ── 写入后状态处理 ─────────────────────────────────
        if failed > 0: # 汇总失败的文章信息
            error_summary = f"文章写入失败 ({failed}/{len(entries)})"
            for entry_info in failed_entries[:3]:  # 最多显示前 3 个失败
                error_summary += f"\n- {entry_info['title']}: {entry_info['error']}"
            if len(failed_entries) > 3:
                error_summary += f"\n... 等 {len(failed_entries) - 3} 个失败"

            if written == 0: # 全部失败：走与 RSS 拉取失败相同的错误计数逻辑
                fetch_failed(client, subscription, error_summary)
            else: # 部分失败：视为成功（清空错误块），但仍追加本次错误记录
                fetch_success(client, subscription)
                client.append_error_block(subscription.page_id, error_summary)
        else: # 完全成功：清空历史错误块并置 Active
            fetch_success(client, subscription)

        # ── 階段三：處理往期文章 ──
        # 每個訂閲源可獨立覆寫 cleanup_days 值，未設定則沿用全局默認值
        # cleanup_days <= 0：手動管理往期文章，不自動刪除
        # cleanup_days >  0：自動刪除指定期限以前的往期文章
        deleted = 0
        if import_days > 0:
            log.debug(f"   清理 {import_days} 天{is_overwrite_str}前的未星號文章")

            deleted = cleanup_expired_articles(
                client,
                database_id=config.entries_database_id,
                cleanup_days=import_days + 1,
                tz=config.timezone,
                source_page_id=subscription.page_id,
            )
            if deleted:
                log.info(f"   ✓ 已刪除 {deleted} 篇過期文章")
        total_deleted += deleted

        write_str = f" 寫入: {written} " if written > 0 else ""
        skip_str = f" 跳過: {skipped} " if skipped > 0 else ""
        failed_str = f" 失敗: {failed} " if failed > 0 else ""
        deleted_str = f" 刪除: {deleted} " if deleted > 0 else ""
        log.info(f"   處理完成 —{write_str}{skip_str}{failed_str}{deleted_str}")

    log.info(
        f"\n全部完成 — 写入: {total_written}  跳过: {total_skipped}  失败: {total_failed}  刪除: {total_deleted}"
    )
