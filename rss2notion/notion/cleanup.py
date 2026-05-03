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


def cleanup_filtered_articles(
    client: NotionClient,
    datasource_id: str,
    filters: list[dict], 
    source_page_id: str | None = None,
) -> int:
    """
    清理 filters 範圍指定的文章。

    Args:
        client:         NotionClient 实例
        datasource_id:  文章数据库 ID
        source_page_id: 若提供，只清理该订阅源的文章；None 则清理全库（不建议单独使用）

    删除操作实为移入 Notion 回收站（30 天内可恢复）。
    返回删除数量。
    """
    if not filters: # filter 為空跳過，自動保護避免刪除全部文章
        log.error(f"自动清理未設定範圍，跳过")
        return 0

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
