"""
Notion API 基础客户端
"""

from ..models import RSSEntry 
import logging
import time

import requests

from .schema import EntryFields, StateValues

log = logging.getLogger(__name__)


class NotionClient:
    BASE = "https://api.notion.com/v1"

    def __init__(self, api_key: str, retry_times: int = 3, retry_delay: float = 2.0):
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        self.retry_times = retry_times
        self.retry_delay = retry_delay

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.BASE}{path}"
        for attempt in range(1, self.retry_times + 1):
            try:
                resp = requests.request(method, url, headers=self.headers, **kwargs)
                if resp.status_code == 429:
                    wait = float(resp.headers.get("Retry-After", self.retry_delay))
                    log.warning(f"触发速率限制，等待 {wait}s …")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.HTTPError as e:
                log.error(f"HTTP 错误 [{attempt}/{self.retry_times}]: {url} \n 錯誤訊息{e.response.text}")
                if attempt == self.retry_times:
                    raise
                time.sleep(self.retry_delay)
        return {}

    # ─────────────────────────────────────────────
    # 阅读数据库操作
    # ─────────────────────────────────────────────

    def query_pages_by_source(self, database_id: str, source_page_id: str) -> set[str]:
        """
        批量查询阅读数据库中指定订阅源的所有已存在 URL，返回 URL 集合。
        用于高效去重：避免逐条 API 查询。
        """
        existing_urls: set[str] = set()
        body = {
            "filter": {
                "property": EntryFields.SOURCE,
                "relation": {"contains": source_page_id},
            },
            "page_size": 100,
        }
        has_more = True
        next_cursor = None

        while has_more:
            if next_cursor:
                body["start_cursor"] = next_cursor
            result = self._request("POST", f"/databases/{database_id}/query", json=body)
            for page in result.get("results", []):
                url_prop = page.get("properties", {}).get(EntryFields.URL, {})
                url = url_prop.get("url") or ""
                if url:
                    existing_urls.add(url)
            has_more = result.get("has_more", False)
            next_cursor = result.get("next_cursor")

        return existing_urls

    def create_page(
        self,
        database_id: str,
        entry,
        source_page_id: str | None = None,
        blocks: list[dict] | None = None,
    ) -> dict:
        """创建阅读数据库页面
        
        Args:
            database_id: 数据库 ID
            entry: RSS 条目对象
            source_page_id: 订阅源页面 ID（可选）
            blocks: Notion blocks 列表。若提供，则包含全文内容；否则仅保存元数据
        """
        properties = _build_entry_properties(entry, source_page_id)
        payload: dict = {
            "parent": {"database_id": database_id},
            "properties": properties,
        }
        if blocks:
            payload["children"] = blocks
        if entry.cover_image:
            payload["cover"] = {
                "type": "external",
                "external": {"url": entry.cover_image},
            }
        return self._request("POST", "/pages", json=payload)

    def lock_page(self, page_id: str) -> None:
        self._request("PATCH", f"/pages/{page_id}", json={"is_locked": True})


    def append_blocks(self, page_id: str, blocks: list[dict]) -> None:
        """分批追加 blocks（每批最多 100 个）"""
        for i in range(0, len(blocks), 100):
            self._request(
                "PATCH",
                f"/blocks/{page_id}/children",
                json={"children": blocks[i: i + 100]},
            )

    def delete_page(self, page_id: str) -> dict:
        """将页面移入回收站（30 天内可在 Notion 回收站恢复）"""
        return self._request("PATCH", f"/pages/{page_id}", json={"in_trash": True})

    def append_error_block(self, page_id: str, error_msg: str) -> None:
        """追加错误 Callout 块到页面（用于记录订阅失败或文章写入失败）
        
        Args:
            page_id: 目标页面 ID
            error_msg: 错误信息（直接使用异常消息字符串）
        """
        try:
            block = _build_error_block(error_msg)
            self.append_blocks(page_id, [block])
            log.info(f"   ✓ 错误块已记录到页面 {page_id}")
        except Exception as e:
            log.warning(f"   ✗ 错误块写入失败（不影响主流程）: {e}")


# ─────────────────────────────────────────────
# 内部辅助函数
# ─────────────────────────────────────────────

def _build_error_block(error_msg: str) -> dict:
    """生成 Notion Callout block（⚠️ 红色背景）
    
    Args:
        error_msg: 错误消息字符串
        
    Returns:
        符合 Notion Block 规范的字典
    """
    # 截断超长消息（Notion paragraph content 限制 2000 字符）
    max_length = 2000
    if len(error_msg) > max_length:
        error_msg = error_msg[:max_length - 5] + "...[截断]"
    
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {
                        "content": error_msg,
                        "link": None,
                    },
                }
            ],
            "icon": {
                "type": "emoji",
                "emoji": "⚠️",
            },
            "color": "red_background",
        },
    }


def _build_entry_properties(
        entry: RSSEntry, 
        source_page_id: str | None) -> dict:
    """构建阅读数据库页面的 properties"""
    # 构建标题，如果有 URL 則添加超鏈接
    title_rich_text = {
        "type": "text",
        "text": {
            "content": entry.title[:2000],
        },
    }
    if entry.url:
        title_rich_text["text"]["link"] = {"url": entry.url}
    
    properties: dict = {
        EntryFields.NAME:      {"title": [title_rich_text]},
        EntryFields.URL:       {"url": entry.url or None},
        EntryFields.PUBLISHED: {"date": {"start": entry.published.isoformat()}},
        EntryFields.STATE:     {"select": {"name": StateValues.UNREAD}},
    }
    if source_page_id:
        properties[EntryFields.SOURCE] = {
            "relation": [{"id": source_page_id}]
        }
    return properties
