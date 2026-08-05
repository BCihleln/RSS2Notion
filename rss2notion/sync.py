"""
主同步流程编排
"""

import logging
import time
from datetime import datetime, timedelta

from .utils.config import Config
from .utils.html2notion_block import html_to_notion_blocks

from .notion.client import NotionClient
from .notion.subscription import Subscription
from .notion.cleanup import cleanup_filtered_articles
from .schema import EntryFields, StateValues
from .rss import parse_rss
from .notion.article import Article

log = logging.getLogger(__name__)
config = Config.from_env()

# ──────────────────────────────────────────────
# 内部輔助函數
# ──────────────────────────────────────────────

def fetch_subscription(subscription: Subscription):
    """
    單個訂閱源的 RSS 拉取，返回 (Subscription, FeedResult or Exception)
    便於并發拉取 RSS
    """
    try:
        return subscription, parse_rss(subscription)
    except Exception as e:
        return subscription, e

def _write_page_with_blocks(client: NotionClient, article: Article, source_page_id: str, all_blocks: list[dict]) -> dict:
    """建立 Notion 頁面並寫入所有區塊，處理分批與鎖定，回傳 page API response"""
    first_batch = all_blocks[:config.notion_block_limit]
    rest_blocks = all_blocks[config.notion_block_limit:]

    article.blocks = first_batch
    page = article.save_to_notion(
        client=client,
        datasource_id=config.articles_datasource_id,
        source_page_id=source_page_id,
        save_blocks=True,
    )
    page_id = page["id"]

    if rest_blocks:
        client.append_blocks(page_id, rest_blocks)
    
    client.lock_page(page_id)
    time.sleep(0.334)
    return page

def _write_page_with_blocks_with_parent(
    client: NotionClient, article: Article, source_page_id: str,
    parent_item_id: str, all_blocks: list[dict]
) -> dict:
    """建立 Notion 子文章頁面（含 Parent-item Relation），處理分批與鎖定"""
    first_batch = all_blocks[:config.notion_block_limit]
    rest_blocks = all_blocks[config.notion_block_limit:]

    article.blocks = first_batch
    page = article.save_to_notion(
        client=client,
        datasource_id=config.articles_datasource_id,
        source_page_id=source_page_id,
        parent_item_id=parent_item_id,
        save_blocks=True,
    )
    page_id = page["id"]

    if rest_blocks:
        client.append_blocks(page_id, rest_blocks)

    client.lock_page(page_id)
    time.sleep(0.334)
    return page


def _handle_aggregated_mode(client: NotionClient, subscription: Subscription, articles: list[Article]) -> tuple[int, int, int, list[dict]]:
    """處理彙整模式：Sub-item 子文章架構"""
    written = skipped = failed = 0
    failed_entries: list[dict] = []
    new_articles: list[Article] = []

    for article in articles:
        skip_msg = article.should_skip(subscription)
        if skip_msg:
            log.debug(f"   跳過: {skip_msg}")
            skipped += 1
            continue
        new_articles.append(article)

    if not new_articles:
        return written, skipped, failed, failed_entries

    # ── 僅 1 篇：直接以標準模式寫入（不建立 Parent 頁面）──
    if len(new_articles) == 1:
        article = new_articles[0]
        try:
            all_blocks = html_to_notion_blocks(article.content_html) if article.content_html else []
            page = _write_page_with_blocks(client, article, subscription.page_id, all_blocks)
            log.info(f"    ✓ 聚合單篇直寫: {article.title}")
            log.info(f"    ------- {page['url']}")
            subscription.existing_articles.append(article.url)
            written += 1
        except Exception as e:
            log.error(f"    ✗ 写入失败: {e}")
            failed_entries.append({"title": article.title[:60], "error": str(e)[:100]})
            failed += 1
        return written, skipped, failed, failed_entries

    # ── ≥2 篇：建立 Parent 聚合頁面 + 子文章 ──
    published_times = [a.published for a in new_articles if a.published]
    if published_times:
        min_time = min(published_times).strftime("%m-%d %H:%M")
        max_time = max(published_times).strftime("%m-%d %H:%M")
        title = f"{min_time} 彙整" if min_time == max_time else f"{min_time} - {max_time} 彙整"
    else:
        title = f"{datetime.now(config.timezone).strftime('%m-%d %H:%M')} 彙整"

    # 建立 Parent 聚合頁面（無 content blocks，標題為時間範圍）
    parent_article = Article(
        title=title,
        url="",
        published=max(published_times) if published_times else datetime.now(config.timezone),
        author="",
        content_html=""
    )

    try:
        parent_page = parent_article.save_to_notion(
            client=client,
            datasource_id=config.articles_datasource_id,
            source_page_id=subscription.page_id,
            save_blocks=False,
        )
        parent_page_id = parent_page["id"]
        client.lock_page(parent_page_id)
        time.sleep(0.334)
        log.info(f"    ✓ 建立 Parent 聚合頁面: {title}")
        log.info(f"    ------- {parent_page['url']}")
    except Exception as e:
        log.error(f"    ✗ 建立 Parent 聚合頁面失敗: {e}")
        failed_entries.append({"title": title, "error": str(e)[:100]})
        failed += len(new_articles)
        return written, skipped, failed, failed_entries

    # 逐篇寫入子文章（設定 Parent-item Relation）
    for idx, article in enumerate(new_articles, 1):
        try:
            all_blocks = html_to_notion_blocks(article.content_html) if article.content_html else []
            page = _write_page_with_blocks_with_parent(
                client, article, subscription.page_id, parent_page_id, all_blocks
            )
            log.info(f"    ✓ [{idx}/{len(new_articles)}] 子文章: {article.title[:50]}")
            subscription.existing_articles.append(article.url)
            written += 1
        except Exception as e:
            log.error(f"    ✗ [{idx}/{len(new_articles)}] 子文章寫入失敗: {e}")
            failed_entries.append({"title": article.title[:60], "error": str(e)[:100]})
            failed += 1

    return written, skipped, failed, failed_entries

def _handle_standard_mode(client: NotionClient, subscription: Subscription, articles: list[Article]) -> tuple[int, int, int, list[dict]]:
    """處理標準模式的寫入邏輯，回傳 (written, skipped, failed, failed_entries)"""
    written = skipped = failed = 0
    failed_entries: list[dict] = []

    for idx, article in enumerate(articles, 1):
        log.debug(f"   [{idx}/{len(articles)}] {article.title[:60]}")

        skip_msg = article.should_skip(subscription)
        if skip_msg: 
            log.debug(f"   跳過: {skip_msg}")
            skipped += 1
            continue

        try:
            all_blocks = []
            if article.content_html:
                all_blocks = html_to_notion_blocks(article.content_html)
                img_count = sum(1 for b in all_blocks if b.get("type") == "image")
                log.debug(f"    blocks: {len(all_blocks)} 个（含 {img_count} 张图片）")

            page = _write_page_with_blocks(client, article, subscription.page_id, all_blocks)

            log.info(f"    ✓ 写入: {article.title}")
            log.info(f"    ------- {page['url']}")
            subscription.existing_articles.append(article.url)
            written += 1
        except Exception as e:
            log.error(f"    ✗ 写入失败: {e}")
            failed_entries.append({
                "title": article.title[:60],
                "error": str(e)[:100],  # 截断错误消息
            })
            failed += 1

    return written, skipped, failed, failed_entries

def process_subscription(client: NotionClient, subscription: Subscription, articles: list[Article]) -> tuple[int, int, int, int]:
    """處理單一訂閱源的所有邏輯，包含時間篩選、寫入 Notion 及清理往期文章"""
    log.info(f"── 处理订阅: {subscription.name or subscription.url}")
    before_filter = len(articles)

    # ── 1. 時間/數量粗篩 ──
    import_days = 1
    is_overwrite_str = ""
    if subscription.fetch_days is not None:
        import_days = subscription.fetch_days
        is_overwrite_str = " (覆寫默認) "
    else:
        import_days = config.cleanup_days

    import_msg = ""
    cutoff = (datetime.now(config.timezone) - timedelta(days=import_days)).replace(hour=0,minute=0,second=0, microsecond=0)
    if import_days > 0:
        articles = [a for a in articles if a.published >= cutoff]
        import_msg = f"{is_overwrite_str}最近 {import_days} 天 (自 {cutoff})"
    else: # 無時限時，限定導入的最大數量 (避免全量導入)
        import_msg = f"歷史 {config.max_import_count} 篇"
        articles = articles[:config.max_import_count]

    if subscription.fetch_amount: # 根據訂閱源配置再篩最新的指定篇數
        articles = articles[:subscription.fetch_amount]
        import_msg += f" 最近 {subscription.fetch_amount} 篇"

    if not articles:
        log.info("   没有新文章，跳过")
        subscription.mark_active(client)
        return 0, 0, 0, 0
    else:
        log.info(f"   導入文章：{import_msg} ({before_filter} → {len(articles)})")
        
        subscription.lazy_load(
            client, 
            articles_datasource_id=config.articles_datasource_id, 
            fetch_blocks=True, 
            fetch_articles=True
        )

    # ── 2. 執行寫入 (區分模式) ──
    if subscription.is_aggregated:
        written, skipped, failed, failed_articles = _handle_aggregated_mode(client, subscription, articles)
    else:
        written, skipped, failed, failed_articles = _handle_standard_mode(client, subscription, articles)

    # ── 3. 寫入後狀態處理 ──
    if failed > 0: # 汇总失败的文章信息
        error_summary = f"文章写入失败 ({failed}/{len(articles)})"
        for article_info in failed_articles[:3]:  # 最多显示前 3 个失败
            error_summary += f"\n- {article_info['title']}: {article_info['error']}"
        if len(failed_articles) > 3:
            error_summary += f"\n... 等 {len(failed_articles) - 3} 个失败"
        subscription.mark_error(client, error_msg=error_summary)
    else: # 完全成功：清空历史错误块并置 Active
        subscription.mark_active(client)

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
            datasource_id=config.articles_datasource_id,
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
