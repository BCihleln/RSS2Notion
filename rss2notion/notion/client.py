"""
Notion API 基础客户端
"""

import logging
import time

import requests

log = logging.getLogger(__name__)

_NOTION_API_VERSION = "2025-09-03"

class NotionClient:
    BASE = "https://api.notion.com/v1"

    def __init__(self, api_key: str, retry_times: int = 3, retry_delay: float = 2.0, notion_user_id: str | None = None):
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Notion-Version": _NOTION_API_VERSION,
        }
        self.retry_times = retry_times
        self.retry_delay = retry_delay
        self.notion_user_id = notion_user_id

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
                # DELETE 返回 200 且无 body，直接返回空 dict
                if resp.status_code == 200 and not resp.content:
                    return {}
                return resp.json()
            except requests.HTTPError as e:
                log.error(f"HTTP 错误 [{attempt}/{self.retry_times}]: {url} \n 錯誤訊息{e.response.text}")
                if attempt == self.retry_times:
                    raise
                time.sleep(self.retry_delay)
        return {}

    def _paginate(self, method: str, path: str, **kwargs) -> list[dict]:
        """通用批量查询 Database pages 或 page blocks，返回所有结果合并后的列表。"""
        results = []
        next_cursor = None
        while True:
            if next_cursor:
                if "json" in kwargs:
                    kwargs["json"] = {**kwargs["json"], "start_cursor": next_cursor}
                else:
                    kwargs["params"] = {**kwargs.get("params", {}), "start_cursor": next_cursor}
            result = self._request(method, path, **kwargs)
            results.extend(result.get("results", []))
            if not result.get("has_more"):
                break
            next_cursor = result.get("next_cursor")
        return results

    def retrieve_data_source(self, data_source_id: str) -> dict:
        """Retrieve a Notion data source schema, including its properties."""
        return self._request("GET", f"/data_sources/{data_source_id}")

    # ─────────────────────────────────────────────
    # 阅读数据库操作
    # ─────────────────────────────────────────────


    def create_page(
        self,
        parent: dict,
        properties: dict,
        children: list[dict] | None = None,
        cover: dict | None = None,
    ) -> dict:
        """创建页面
        
        Args:
            parent: parent object, e.g. {"type": "data_source_id", "data_source_id": datasource_id}
            properties: 頁面屬性字典
            children: 頁面的內容區塊 (可選)
            cover: 頁面的封面 (可選)
        """
        payload: dict = {
            "parent": parent,
            "properties": properties,
        }
        if children:
            payload["children"] = children
        if cover:
            payload["cover"] = cover
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

    # ─────────────────────────────────────────────
    # 错误块管理
    # ─────────────────────────────────────────────

    def get_block_children(self, block_id: str) -> list[dict]:
        """获取页面/块的直接子块列表（支持分页）"""
        blocks: list[dict] = self._paginate("GET", f"/blocks/{block_id}/children", params={"page_size": 100})

        return blocks

    def delete_block(self, block_id: str) -> None:
        """删除单个块（移入回收站）"""
        self._request("DELETE", f"/blocks/{block_id}")

    def update_block_text(self, block_id: str, new_text: str, block_type: str = "paragraph") -> None:
        """
        更新 block 的文本內容。
        Notion 單個 text 限制 2000 字元，超長會被拆分成多個 rich_text items。
        """
        rich_text = []
        for i in range(0, len(new_text), 2000):
            rich_text.append({
                "type": "text",
                "text": {"content": new_text[i:i+2000]}
            })

        body = {
            block_type: {
                "rich_text": rich_text
            }
        }
        self._request("PATCH", f"/blocks/{block_id}", json=body)


    def _get_notion_user_id(self) -> str | None:
        """延迟解析并缓存 Notion 用户 ID"""
        if getattr(self, '_notion_user_id_resolved', False):
            return self.notion_user_id

        self._notion_user_id_resolved = True
        if not self.notion_user_id:
            try:
                for u in self._paginate("GET", "/users"):
                    if u.get("type") == "person":
                        self.notion_user_id = u["id"]
                        break
            except Exception as e:
                log.warning(f"   ✗ 无法获取 Notion 使用者 ID: {e}")

        return self.notion_user_id

# ─────────────────────────────────────────────
# 内部辅助函数
# ─────────────────────────────────────────────


