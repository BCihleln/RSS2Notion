"""
主同步流程编排
"""

import logging
import time
from datetime import datetime, timedelta

from .config import Config
from .converter import entry_to_notion_blocks
from .notion.client import NotionClient
from .notion.cleanup import cleanup_expired_articles
from .notion.subscription import fetch_active_subscriptions, update_subscription_status
from .notion.schema import StatusValues
from .rss import parse_rss

log = logging.getLogger(__name__)


def run(config: Config) -> None:
    """主同步流程"""
    client = NotionClient(
        api_key=config.notion_api_key,
        retry_times=config.retry_times,
        retry_delay=config.retry_delay,
    )

    # 获取所有活跃订阅
    try:
        subscriptions = fetch_active_subscriptions(client, config.feeds_database_id)
    except Exception as e:
        log.error(f"读取订阅数据库失败: {e}")
        return

    if not subscriptions:
        log.warning("没有活跃的订阅，退出")
        return

    total_written = total_skipped = total_failed = 0

    for subscription in subscriptions:
        log.info(f"── 处理订阅: {subscription.name or subscription.url}")

        # 解析 RSS
        try:
            feed_result = parse_rss(subscription)
        except Exception as e:
            log.error(f"  RSS 解析失败: {e}")
            update_subscription_status(
                client, subscription, status=StatusValues.ERROR, error_msg=str(e)
            )
            continue

        entries = feed_result.entries
        before_filter = len(entries)

        # 时间粗筛：减少进入 URL 去重阶段的条目数
        if config.cleanup_days >= 0:
            # 默认只导入 cleanup_days 天内的文章，避免历史数据全量涌入
            cutoff = (datetime.now(config.timezone) - timedelta(days=config.cleanup_days)).replace(hour=0,minute=0,second=0, microsecond=0)
            entries = [e for e in entries if e.published >= cutoff]
            log.info(f"   导入最近 {config.cleanup_days} 天的文章 (自 {cutoff})：{before_filter} → {len(entries)} 条")
        else:
            # cleanup_days=-1：首次运行写入全部历史数据
            log.info(f"   首次运行，导入全部历史数据（{len(entries)} 条）")

        if not entries:
            log.info("   没有新文章，跳过")
            update_subscription_status(
                client, subscription,
                status=StatusValues.ACTIVE,
                feed_title=feed_result.feed_title,
                feed_icon_url=feed_result.feed_icon_url,
            )
            continue

        # 批量查询已存在的 URL（去重）
        existing_urls: set[str] = set()
        try:
            existing_urls = client.query_pages_by_source(
                config.entries_database_id, subscription.page_id
            )
            log.info(f"   已存在 {len(existing_urls)} 条记录（用于去重）")
        except Exception as e:
            log.warning(f"   批量去重查询失败，将逐条跳过: {e}")

        written = skipped = failed = 0
        failed_entries = []  # 收集失败的文章信息（标题 + 错误消息）

        for idx, entry in enumerate(entries, 1):
            entry_info_text = f"   [{idx}/{len(entries)}] {entry.title[:60]}"
            log.debug(entry_info_text)

            # URL 去重
            if entry.url and entry.url in existing_urls:
                log.debug("    → 已存在，跳过")
                skipped += 1
                continue

            try:
                # 默認獲取 Feed 内提供的 content 或 summery 内容
                all_blocks = entry_to_notion_blocks(entry)
                first_batch = all_blocks[:config.notion_block_limit]
                rest_blocks = all_blocks[config.notion_block_limit:]

                img_count = sum(1 for b in all_blocks if b.get("type") == "image")
                log.info(f"    blocks: {len(all_blocks)} 个（含 {img_count} 张图片）")

                page = client.create_page(
                    database_id=config.entries_database_id,
                    entry=entry,
                    source_page_id=subscription.page_id,
                    blocks=first_batch,
                )
                page_id = page["id"]

                if rest_blocks:
                    client.append_blocks(page_id, rest_blocks)

                if subscription.full_text_enabled:
                    # TODO: 進階獲取網頁全文模式
                    pass
                
                client.lock_page(page_id) # Auto lock to prevent accidental modification in database UI

                log.info(f"    ✓ 写入: {entry.title}")
                log.info(f"    ------- {page['url']}")
                existing_urls.add(entry.url)  # 防止同一次运行中重复写入
                written += 1

            except Exception as e:
                log.error(f"    ✗ 写入失败: {e}")
                failed_entries.append({
                    "title": entry.title[:60],
                    "error": str(e)[:100],  # 截断错误消息
                })
                failed += 1

            time.sleep(0.4)  # 控制 Notion API 速率

        log.info(f"订阅完成 — 写入: {written}  跳过: {skipped}  失败: {failed}")
        total_written += written
        total_skipped += skipped
        total_failed += failed

        # 处理文章写入失败情况
        subscription_status = StatusValues.ACTIVE
        error_msg = None
        
        if failed > 0:
            # 汇总失败的文章信息
            error_summary = f"文章写入失败 ({failed}/{len(entries)})"
            for entry_info in failed_entries[:3]:  # 最多显示前 3 个失败
                error_summary += f"\n- {entry_info['title']}: {entry_info['error']}"
            if len(failed_entries) > 3:
                error_summary += f"\n... 等 {len(failed_entries) - 3} 个失败"
            
            error_msg = error_summary
            
            # 全部失败则设置 Status 为 ERROR
            if written == 0 and failed > 0:
                subscription_status = StatusValues.ERROR
        
        # 更新订阅状态，若有失败信息则记录到 Notion
        update_subscription_status(
            client, subscription,
            status=subscription_status,
            feed_title=feed_result.feed_title,
            feed_icon_url=feed_result.feed_icon_url,
            error_msg=error_msg,
        )

    # 自动清理过期文章
    cleanup_expired_articles(client, config.entries_database_id, config.cleanup_days, config.timezone)

    log.info(
        f"\n全部完成 — 写入: {total_written}  跳过: {total_skipped}  失败: {total_failed}"
    )
