"""
数据模型定义
"""

from dataclasses import dataclass, field
from datetime import datetime

from .converter import split_html_to_blocks


@dataclass
class RSSEntry:
    title: str
    url: str
    published: datetime
    author: str
    content_html: str
    cover_image: str = "" # 最终封面：优先取文章第一张图，没有则用频道图
    channel_image: str = "" # 频道级封面图（RSS <image> 标签），条目无图时兜底使用
    blocks: list[tuple] = field(default_factory=list, init=False) # 解析后的「块列表」，每个块是 ("text", markdown字符串) 或 ("image", url)

    def __post_init__(self):
        if self.content_html:
            self.blocks = split_html_to_blocks(self.content_html)
        # 优先用文章内第一张图，无图则降级到频道封面
        for kind, val in self.blocks:
            if kind == "image":
                self.cover_image = val
                break
        if not self.cover_image:
            self.cover_image = self.channel_image


@dataclass
class FeedResult:
    """parse_rss 的返回值"""
    feed_title: str
    feed_icon_url: str
    entries: list[RSSEntry]


@dataclass
class Subscription:
    """对应 Notion 订阅数据库中的一行"""
    page_id: str
    name: str
    url: str
    icon: dict | None
    channel_image: str | None
    full_text_enabled: bool
    status: str                     # Active / Error /Disabled
    last_update: datetime           # ISO 日期，可为 None