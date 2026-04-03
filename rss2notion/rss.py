"""
RSS 解析：获取订阅条目
"""

import logging
from datetime import datetime, timezone

import feedparser
from time import struct_time

from .models import RSSEntry, FeedResult, Subscription
from .utils.get_favicon import get_website_favicon

log = logging.getLogger(__name__)


def _parse_entry_content(entry:dict) -> str:
    # 提取正文内容：优先取 HTML，否则用 summary
    for c in entry.get("content", []):
        if c.get("type") == "text/html":
            return c.get("value", "")
    
    return entry.get("summary", "")

def _parse_entry_thumbnail(entry:dict)-> str:
    """
    提取条目级缩略图：优先 media_content（即 feedparser 规范化的媒体元素列表），再试 enclosures
    """
    entry_thumb = ""
    if hasattr(entry, "media_content"):
        for media in entry.get("media_content", []):
            if media.get("medium") == "image" or media.get("type", "").startswith("image/"):
                entry_thumb = media.get("url", "")
                break
    elif hasattr(entry, "media_thumbnail"): # 备用：media_thumbnail（更常见的 RSS 扩展）
        entry_thumb = entry.get("media_thumbnail", [{}])[0].get("url", "")
    else: # 最后备用：enclosures
        for enc in entry.get("enclosures", []):
            if enc.get("type", "").startswith("image/"):
                entry_thumb = enc.get("url", "")
                break
    return entry_thumb

def _parse_entry_published(entry:dict, feed_updated_tuple: struct_time) -> datetime:
    """
    提取发布日期：优先 published_parsed，再试 updated_parsed，
    都没有则 fallback 到 feed 更新时间，最后为空字符串（不用 datetime.now()）
    """
    tuple:struct_time = entry.get("published_parsed") or entry.get("updated_parsed") or feed_updated_tuple

    return datetime(tuple.tm_year, tuple.tm_mon, tuple.tm_mday, tuple.tm_hour, tuple.tm_min, tuple.tm_sec, tzinfo=timezone.utc)

def parse_rss(subscirption: Subscription) -> FeedResult:
    """解析 RSS feed，返回频道标题和条目列表"""
    log.info(f"   解析 RSS: {subscirption.url}")
    parse_result = feedparser.parse(subscirption.url)

    # 如果有 bozo 错误但没有 entries，无法继续
    if parse_result.bozo:
        if parse_result.entries:
            log.warning(f"RSS 解析異常，但成功提取 {len(parse_result.entries)} 条条目: {parse_result.bozo_exception}")
        else:
            log.warning(f"Parsed Fields : {parse_result.keys()}")
            raise ValueError(f"RSS 解析失敗，无条目可提取: {parse_result.bozo_exception}")

    channel_image = ""
    if not subscirption.channel_image:
        # 提取频道级封面图：依次尝试 image.url → logo → icon（Atom 格式）
        if hasattr(parse_result.feed, "image"):
            channel_image = parse_result.feed.image.get("href", "")
        elif hasattr(parse_result.feed, "logo"):
            channel_image = feed_icon_url = parse_result.feed.logo
        else: 
            channel_image = feed_icon_url = parse_result.feed.get("icon", "")
    
    # feedparser 的 feed.updated_parsed 用作日期缺失时的备用
    feed_updated_tuple:struct_time = parse_result.feed.get("updated_parsed")

    parsed_entries = []
    for entry in parse_result.entries:
        rss_entry = RSSEntry(
            title           = str(entry.get("title", "No Title")),
            url             = str(entry.get("link", "")),
            published       = _parse_entry_published(entry, feed_updated_tuple),
            author          = str(entry.get("author", "")),
            content_html    = _parse_entry_content(entry),
            cover_image     = _parse_entry_thumbnail(entry),
            channel_image   = channel_image,
        )
        parsed_entries.append(rss_entry)

    log.debug(f"   获取到 {len(parsed_entries)} 条条目，频道: {subscirption.name}")
    return FeedResult(
        entries=parsed_entries
        )
