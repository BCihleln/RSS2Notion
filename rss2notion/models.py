"""
数据模型定义
"""

from dataclasses import dataclass, field
from datetime import datetime

# from .utils.converter import split_html_to_blocks
from .utils.html2notion_block import html_to_notion_blocks


@dataclass
class RSSEntry:
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
            # self.blocks = split_html_to_blocks(self.content_html)
            self.blocks = html_to_notion_blocks(self.content_html)
        # 從已解析的 blocks 中找第一張圖作封面
            for b in self.blocks:
                if b.get("type") == "image":
                    self.cover_image = b["image"]["external"]["url"]
                    break
        if not self.cover_image:
            self.cover_image = self.channel_image

@dataclass
class Subscription:
    """对应 Notion 订阅数据库中的一行"""
    page_id: str
    name: str
    url: str
    icon: dict | None
    channel_image: str | None
    filterout_keywords: list
    status: str                     # Active / Error /Disabled
    last_update: datetime           # ISO 日期
    existing_articles: list[str]    # 已存入 Notion 的文章鏈接清單，便於去重
    accumulated_errors: list[dict]