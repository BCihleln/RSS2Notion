"""
命令行入口：python -m rss2notion
"""

import logging
import time
from datetime import datetime, timedelta

from .utils.config import Config
from .utils.html2notion_block import html_to_notion_blocks
from .utils.clustering import cluster_items

from .models import Subscription, RSSEntry

from .sync import fetch_subscription, fetch_failed, fetch_success

from .notion.client import NotionClient
from .notion.cleanup import cleanup_filtered_articles
from .notion.subscription import get_avaliable_subscriptions
from .notion.validation import SchemaValidationError, validate_notion_setup
from .schema import EntryFields, StateValues

from concurrent.futures import ThreadPoolExecutor, as_completed

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)
config = Config.from_env()


def _should_skip_entry(subscription: Subscription, entry: RSSEntry) -> str:
    """檢查單篇文章是否需要跳過，返回跳過原因，若不跳過返回空字串"""
    for keyword in subscription.filterout_keywords:
        if keyword in (entry.title + entry.url): 
            return f"匹配到關鍵字: [{keyword}]"
    
    if (entry.url and entry.url in subscription.existing_articles) or (entry.title in subscription.existing_articles):
        return "Notion 已存在相同文章"
            
    return ""


def _write_page_with_blocks(client: NotionClient, entry: RSSEntry, source_page_id: str, all_blocks: list[dict]) -> dict:
    """建立 Notion 頁面並寫入所有區塊，處理分批與鎖定，回傳 page API response"""
    first_batch = all_blocks[:config.notion_block_limit]
    rest_blocks = all_blocks[config.notion_block_limit:]

    page = client.create_page(
        datasource_id=config.entries_datasource_id,
        entry=entry,
        source_page_id=source_page_id,
        blocks=first_batch,
    )
    page_id = page["id"]

    if rest_blocks:
        client.append_blocks(page_id, rest_blocks)
    
    client.lock_page(page_id)
    time.sleep(0.334)
    return page


def _handle_aggregated_mode(client: NotionClient, subscription: Subscription, entries: list[RSSEntry]) -> tuple[int, int, int, list[dict]]:
    """處理彙整模式的寫入邏輯，回傳 (written, skipped, failed, failed_entries)"""
    written = skipped = failed = 0
    failed_entries: list[dict] = []
    all_urls = []
    new_entries = []

    for entry in entries:
        if entry.url:
            all_urls.append(entry.url)
        
        skip_msg = _should_skip_entry(subscription, entry)
        if skip_msg:
            log.debug(f"   跳過: {skip_msg}")
            skipped += 1
            continue
        
        new_entries.append(entry)

    if new_entries:
        published_times = [e.published for e in new_entries if e.published]
        if published_times:
            min_time = min(published_times).strftime("%m-%d %H:%M")
            max_time = max(published_times).strftime("%m-%d %H:%M")
            title = f"{min_time} 彙整" if min_time == max_time else f"{min_time} - {max_time} 彙整"
        else:
            title = f"{datetime.now(config.timezone).strftime('%m-%d %H:%M')} 彙整"

        # 依照標題相似度分群
        clusters = cluster_items(new_entries, key=lambda e: e.title, percentile=config.aggregation_similarity_percentile)
        
        all_blocks = []
        for i, cluster in enumerate(clusters):
            # 在不同群組之間插入橫線區隔
            if i > 0:
                all_blocks.append({
                    "object": "block",
                    "type": "divider",
                    "divider": {}
                })
                
            for entry in cluster:
                published_str = entry.published.strftime("%m-%d %H:%M") if entry.published else ""
                text_content = [
                    {
                        "type": "text",
                        "text": {
                            "content": entry.title,
                            "link": {"url": entry.url} if entry.url else None
                        }
                    }
                ]
                if published_str:
                    text_content.append({
                        "type": "text",
                        "text": {"content": f" ({published_str})"},
                        "annotations": {"color": "gray"}
                    })

                all_blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": text_content}
                })

        dummy_entry = RSSEntry(
            title=title,
            url=subscription.url,
            published=max(published_times) if published_times else datetime.now(config.timezone),
            author="",
            content_html=""
        )

        try:
            page = _write_page_with_blocks(client, dummy_entry, subscription.page_id, all_blocks)
            written += len(new_entries)
            log.info(f"    ✓ 写入彙整頁面: {title} (包含 {len(new_entries)} 篇文章)")
            log.info(f"    ------- {page['url']}")
        except Exception as e:
            log.error(f"    ✗ 写入彙整頁面失败: {e}")
            failed_entries.append({"title": title, "error": str(e)[:100]})
            failed += len(new_entries)
    
    if failed == 0 and all_urls:
        urls_str = "\n".join(all_urls)
        try:
            if getattr(subscription, "aggregated_urls_paragraph_id", None):
                client.update_block_text(subscription.aggregated_urls_paragraph_id, urls_str, block_type="paragraph")
            elif getattr(subscription, "aggregated_urls_block_id", None):
                # Fallback to updating the old callout directly if paragraph ID wasn't found
                client.update_block_text(subscription.aggregated_urls_block_id, urls_str, block_type="callout")
            else:
                new_id = client.append_aggregated_urls_block(subscription.page_id, urls_str)
                subscription.aggregated_urls_block_id = new_id
        except Exception as e:
            log.error(f"    ✗ 更新 Callout 失败: {e}")

    return written, skipped, failed, failed_entries


def _handle_standard_mode(client: NotionClient, subscription: Subscription, entries: list[RSSEntry]) -> tuple[int, int, int, list[dict]]:
    """處理標準模式的寫入邏輯，回傳 (written, skipped, failed, failed_entries)"""
    written = skipped = failed = 0
    failed_entries: list[dict] = []

    for idx, entry in enumerate(entries, 1):
        log.debug(f"   [{idx}/{len(entries)}] {entry.title[:60]}")

        skip_msg = _should_skip_entry(subscription, entry)
        if skip_msg: 
            log.debug(f"   跳過: {skip_msg}")
            skipped += 1
            continue

        try:
            all_blocks = []
            if entry.content_html:
                all_blocks = html_to_notion_blocks(entry.content_html)
                img_count = sum(1 for b in all_blocks if b.get("type") == "image")
                log.debug(f"    blocks: {len(all_blocks)} 个（含 {img_count} 张图片）")

            page = _write_page_with_blocks(client, entry, subscription.page_id, all_blocks)

            log.info(f"    ✓ 写入: {entry.title}")
            log.info(f"    ------- {page['url']}")
            subscription.existing_articles.append(entry.url)
            written += 1
        except Exception as e:
            log.error(f"    ✗ 写入失败: {e}")
            failed_entries.append({
                "title": entry.title[:60],
                "error": str(e)[:100],  # 截断错误消息
            })
            failed += 1

    return written, skipped, failed, failed_entries


def process_subscription(client: NotionClient, subscription: Subscription, entries: list[RSSEntry]) -> tuple[int, int, int, int]:
    """處理單一訂閱源的所有邏輯，包含時間篩選、寫入 Notion 及清理往期文章"""
    log.info(f"── 处理订阅: {subscription.name or subscription.url}")
    before_filter = len(entries)

    # ── 1. 時間/數量粗篩 ──
    import_days = 1
    is_overwrite_str = ""
    if (subscription.fetch_days is not None) and len(subscription.existing_articles) > 0:
        import_days = subscription.fetch_days
        is_overwrite_str = " (覆寫默認) "
    else:
        import_days = config.cleanup_days

    import_msg = ""
    cutoff = (datetime.now(config.timezone) - timedelta(days=import_days)).replace(hour=0,minute=0,second=0, microsecond=0)
    if import_days > 0:
        entries = [e for e in entries if e.published >= cutoff]
        import_msg = f"{is_overwrite_str}最近 {import_days} 天 (自 {cutoff})"
    else: # 無時限時，限定導入的最大數量 (避免全量導入)
        import_msg = f"歷史 {config.max_import_count} 篇"
        entries = entries[:config.max_import_count]

    if subscription.fetch_amount: # 根據訂閱源配置再篩最新的指定篇數
        entries = entries[:subscription.fetch_amount]
        import_msg += f" 最近 {subscription.fetch_amount} 篇"

    if not entries:
        log.info("   没有新文章，跳过")
        fetch_success(client, subscription)
        return 0, 0, 0, 0
    else:
        log.info(f"   導入文章：{import_msg} ({before_filter} → {len(entries)})")

    # ── 2. 執行寫入 (區分模式) ──
    if getattr(subscription, "is_aggregated", False):
        written, skipped, failed, failed_entries = _handle_aggregated_mode(client, subscription, entries)
    else:
        written, skipped, failed, failed_entries = _handle_standard_mode(client, subscription, entries)

    # ── 3. 寫入後狀態處理 ──
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

    # ── 4. 清理往期文章 ──
    log.debug(f"   清理配置：{import_days} 天{is_overwrite_str}")
    deleted = 0
    filters: list[dict] = []
    keep_latest_count = None
    if import_days > 0: # 自動刪除指定期限以前的往期文章
        log.debug(f"   清理 {import_days} 天前的未星號文章")
        filters = [
            {
                "property": EntryFields.STATE,
                "select": {"does_not_equal": StateValues.STARRED},
            },
            {
                "property": EntryFields.PUBLISHED,
                "date": {"before": cutoff.isoformat()},
            },
        ]
    else: # 自動刪除已讀文章
        log.debug(f"   僅清理已讀文章")
        filters = [
            {
                "property": EntryFields.STATE,
                "select": {"is_empty": True},
            }
        ]
        
        keep_latest_count = subscription.fetch_amount or config.max_import_count

    deleted = cleanup_filtered_articles(
            client,
            datasource_id=config.entries_datasource_id,
            source_page_id=subscription.page_id,
            filters=filters,
            keep_latest_count=keep_latest_count)
    if deleted: 
        log.info(f"   ✓ 已刪除 {deleted} 篇過期文章")

    write_str = f" 寫入: {written} " if written > 0 else ""
    skip_str = f" 跳過: {skipped} " if skipped > 0 else ""
    failed_str = f" 失敗: {failed} " if failed > 0 else ""
    deleted_str = f" 刪除: {deleted} " if deleted > 0 else ""
    log.info(f"   處理完成 —{write_str}{skip_str}{failed_str}{deleted_str}")

    return written, skipped, failed, deleted

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

    # 获取所有活跃订阅
    try:
        subscriptions = get_avaliable_subscriptions(client, 
            config.feeds_datasource_id, 
            config.entries_datasource_id)
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

    # ── 階段二 & 三：串行寫入 Notion 及清理（受速率限制）──
    total_written = total_skipped = total_failed = total_deleted = 0

    for subscription, entries in successed_subscriptions:
        written, skipped, failed, deleted = process_subscription(client, subscription, entries)
        total_written += written
        total_skipped += skipped
        total_failed += failed
        total_deleted += deleted

    log.info(
        f"\n全部完成 — 写入: {total_written}  跳过: {total_skipped}  失败: {total_failed}  刪除: {total_deleted}"
    )
