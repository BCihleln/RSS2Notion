"""
自动清理：删除超过指定天数的 Unread 文章
"""

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .client import NotionClient
from .schema import EntryFields, StateValues

log = logging.getLogger(__name__)


def cleanup_expired_articles(
    client: NotionClient,
    database_id: str,
    cleanup_days: int,
    tz: ZoneInfo,
) -> int:
    """
    清理 State!=STARRED 且 Published 超过 cleanup_days 天的文章。
    cleanup_days=-1 时跳过清理。
    删除操作实为移入 Notion 回收站（30 天内可恢复）。
    返回删除数量。
    """
    if cleanup_days < 0:
        log.info("自动清理已禁用（CLEANUP_DAYS=-1）")
        return 0

    cutoff = (datetime.now(tz) - timedelta(days=cleanup_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff_iso = cutoff.isoformat()
    log.info(f"清理 {cleanup_days} 天前的 未星號 文章（截止: {cutoff}）")

    body: dict = {
        "filter": {
            "and": [
                {
                    "property": EntryFields.STATE,
                    "select": {"does_not_equal": StateValues.STARRED},
                },
                {
                    "property": EntryFields.PUBLISHED,
                    "date": {"before": cutoff_iso},
                },
            ]
        },
        "page_size": 100,
    }

    deleted_count = 0
    pages_should_deleted = client._paginate("POST", f"/databases/{database_id}/query", json=body)
    for page in pages_should_deleted:
        try:
            client.delete_page(page["id"])
            deleted_count += 1
            time.sleep(0.3) # 控制速率
        except Exception as e:
            log.error(f"删除页面 {page['id']} 失败: {e}")

    log.info(f"清理完成：删除了 {deleted_count} 篇过期文章")
    return deleted_count
