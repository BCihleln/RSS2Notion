"""
文章領域邏輯遷移 (Article Domain)
"""
from ..models import RSSEntry, Subscription
from ..schema import EntryFields, StateValues
from .client import NotionClient


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


def _build_entry_properties(entry: RSSEntry, source_page_id: str | None) -> dict:
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


def create_article_page(
    client: NotionClient,
    datasource_id: str,
    source_page_id: str | None,
    entry: RSSEntry,
    blocks: list[dict] | None = None,
) -> dict:
    """创建阅读数据库页面
    
    Args:
        client: NotionClient 实例
        datasource_id: 数据库 ID
        source_page_id: 订阅源页面 ID（可选）
        entry: RSS 条目对象
        blocks: Notion blocks 列表。若提供，则包含全文内容；否则仅保存元数据
    """
    properties = _build_entry_properties(entry, source_page_id)
    cover = None
    if entry.cover_image:
        cover = {
            "type": "external",
            "external": {"url": entry.cover_image},
        }
    
    return client.create_page(
        parent={"type": "data_source_id", "data_source_id": datasource_id},
        properties=properties,
        children=blocks,
        cover=cover,
    )


def should_skip_entry(subscription: Subscription, entry: RSSEntry) -> str:
    """檢查單篇文章是否需要跳過，返回跳過原因，若不跳過返回空字串"""
    for keyword in subscription.filterout_keywords:
        if keyword in (entry.title + entry.url): 
            return f"匹配到關鍵字: [{keyword}]"
    
    if (entry.url and entry.url in subscription.existing_articles) or (entry.title in subscription.existing_articles):
        return "Notion 已存在相同文章"
            
    return ""
