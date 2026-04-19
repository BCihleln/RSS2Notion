"""
自动清理：删除超过指定天数的 Unread 文章
"""

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .client import NotionClient
from ..schema import EntryFields, StateValues

log = logging.getLogger(__name__)


def cleanup_expired_articles(
    client: NotionClient,
    datasource_id: str,
    cleanup_days: int,
    tz: ZoneInfo,
    source_page_id: str | None = None,
) -> int:
    """
    清理 State!=STARRED 且 Published 超过 cleanup_days 天的文章。

    Args:
        client:         NotionClient 实例
        datasource_id:    文章数据库 ID
        cleanup_days:   保留天数；-1 时跳过清理
        tz:             时区（用于计算截止日期）
        source_page_id: 若提供，只清理该订阅源的文章；None 则清理全库（不建议单独使用）

    删除操作实为移入 Notion 回收站（30 天内可恢复）。
    返回删除数量。
    """
    if cleanup_days <= 0:
        log.debug(f"自动清理已禁用（清理天數 : {cleanup_days}），跳过")
        return 0

    cutoff = (datetime.now(tz) - timedelta(days=cleanup_days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    cutoff_iso = cutoff.isoformat()
    filters: list[dict] = [
        {
            "property": EntryFields.STATE,
            "select": {"does_not_equal": StateValues.STARRED},
        },
        {
            "property": EntryFields.PUBLISHED,
            "date": {"before": cutoff_iso},
        },
    ]

    if source_page_id:
        filters.append({
            "property": EntryFields.SOURCE,
            "relation": {"contains": source_page_id},
        })

    body: dict = {
        "filter": {"and": filters},
        "page_size": 100,
    }

    deleted_count = 0
    pages_should_deleted = client._paginate("POST", f"/data_sources/{datasource_id}/query", json=body)
    for page in pages_should_deleted:
        try:
            log.info(f"   刪除：{page['url']}")
            client.delete_page(page["id"])
            deleted_count += 1
            time.sleep(0.3) # 控制速率
        except Exception as e:
            log.error(f"   删除页面 {page['id']} 失败: {e}")

    return deleted_count
