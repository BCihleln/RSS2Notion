"""
文章領域邏輯遷移 (Article Domain)
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .subscription import Subscription

from ..schema import EntryFields, StateValues
from .client import NotionClient
from ..utils.html2notion_block import html_to_notion_blocks


@dataclass
class Article:
    title: str
    url: str
    published: datetime
    author: str
    content_html: str
    cover_image: str = "" # 最终封面：优先取文章第一张图，没有则用频道图
    channel_image: str = "" # 频道级封面图（RSS <image> 标签），条目无图时兜底使用
    blocks: list[dict] = field(default_factory=list, init=False) # 暫存解析后的「块列表」

    def __post_init__(self):
        if self.content_html:
            self.blocks = html_to_notion_blocks(self.content_html)
            # 從已解析的 blocks 中找第一張圖作封面
            for b in self.blocks:
                if b.get("type") == "image":
                    self.cover_image = b["image"]["external"]["url"]
                    break
        if not self.cover_image:
            self.cover_image = self.channel_image

    def should_skip(self, subscription: 'Subscription') -> str:
        """檢查單篇文章是否需要跳過，返回跳過原因，若不跳過返回空字串"""
        for keyword in subscription.filterout_keywords:
            if keyword in (self.title + self.url): 
                return f"匹配到關鍵字: [{keyword}]"
        
        if (self.url and self.url in subscription.existing_articles) or (self.title in subscription.existing_articles):
            return "Notion 已存在相同文章"
                
        return ""

    def to_notion_properties(self, source_page_id: str | None) -> dict:
        """构建阅读数据库页面的 properties"""
        # 构建标题，如果有 URL 則添加超鏈接
        title_rich_text = {
            "type": "text",
            "text": {
                "content": self.title[:2000],
            },
        }
        if self.url:
            title_rich_text["text"]["link"] = {"url": self.url}
        
        properties: dict = {
            EntryFields.NAME:      {"title": [title_rich_text]},
            EntryFields.URL:       {"url": self.url or None},
            EntryFields.PUBLISHED: {"date": {"start": self.published.isoformat()}},
            EntryFields.STATE:     {"select": {"name": StateValues.UNREAD}},
        }
        if source_page_id:
            properties[EntryFields.SOURCE] = {
                "relation": [{"id": source_page_id}]
            }
        return properties

    def save_to_notion(
        self,
        client: NotionClient,
        datasource_id: str,
        source_page_id: str | None,
        save_blocks: bool = True
    ) -> dict:
        """创建阅读数据库页面并保存内容"""
        properties = self.to_notion_properties(source_page_id)
        cover = None
        if self.cover_image:
            cover = {
                "type": "external",
                "external": {"url": self.cover_image},
            }
        
        children = self.blocks if save_blocks else None

        return client.create_page(
            parent={"type": "data_source_id", "data_source_id": datasource_id},
            properties=properties,
            children=children,
            cover=cover,
        )


def query_existing_article_urls(client: NotionClient, datasource_id: str, source_page_id: str) -> list[str]:
    """
    批量查询阅读数据库中指定订阅源的所有已存在文章，返回 URL 與標題 集合。
    用于高效去重：避免逐条 API 查询。
    """
    body = {
        "filter": {
            "property": EntryFields.SOURCE,
            "relation": {"contains": source_page_id},
        },
        "page_size": 100,
    }
    existing_urls_titles: set[str] = set()
    for page in client._paginate("POST", f"/data_sources/{datasource_id}/query", json=body):
        if (url := page.get("properties", {}).get(EntryFields.URL, {}).get("url","")):
            existing_urls_titles.add(url)
        title_list = page.get("properties", {}).get(EntryFields.NAME, {}).get("title", [])
        if title_list:
            title = "".join(item.get("plain_text", "") for item in title_list).strip()
            if title: existing_urls_titles.add(title)
    return [*existing_urls_titles]
