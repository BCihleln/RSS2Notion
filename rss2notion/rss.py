"""
RSS 解析：获取订阅条目
"""

import logging
from datetime import datetime, timezone

import feedparser
import re
from time import struct_time

from .models import RSSEntry, Subscription
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
    entry_thumb_dict = {}
    if media_thumbnails := entry.get("media_thumbnail", [{}]):
        entry_thumb_dict = media_thumbnails[0]
    elif media_contents := entry.get("media_content", []):
        for media in media_contents:
            if media.get("medium") == "image" or media.get("type", "").startswith("image/"):
                entry_thumb_dict = media
                break
    else: # 最后备用：enclosures
        for enc in entry.get("enclosures", []):
            if enc.get("type", "").startswith("image/"):
                entry_thumb_dict = enc
                break
    return entry_thumb_dict.get("url", "")

def _parse_entry_published(entry:dict, feed_updated_tuple: struct_time) -> datetime:
    """
    提取发布日期：优先 published_parsed，再试 updated_parsed，再试 feed_updated_time
    都没有则 fallback 到 datetime.now()
    """
    tuple:struct_time = entry.get("published_parsed") or entry.get("updated_parsed") or feed_updated_tuple
    if tuple:
        return datetime(tuple.tm_year, tuple.tm_mon, tuple.tm_mday, tuple.tm_hour, tuple.tm_min, tuple.tm_sec, tzinfo=timezone.utc)
    else: # 嘗試從文章內容提取日期
        text = entry.get("summary", "") + _parse_entry_content(entry)
        if extracted := _extract_date_from_text(text):
            log.debug(f"   從內文提取到日期：{extracted.date()}")
            return extracted
        return datetime.now(tz=timezone.utc)

def _extract_date_from_text(text: str) -> datetime | None:
    """從文字中嘗試 regex 提取日期（用於缺失 published 字段時的備援）"""
    date_pattern = [
        r'(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日', # CJK 格式：2025年4月19日
        r'\b(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})\b', # ISO-like 格式：2025.04.19 / 2025/04/19 / 2025-04-19
    ]
    for pattern_try in date_pattern:
        if m := re.search(pattern_try, text):
            try: return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc) 
            except ValueError: continue  # 命中但值不合法，試下一個 pattern
    return None

def parse_rss(subscirption: Subscription) -> list[RSSEntry]:
    """解析 RSS feed，返回条目列表"""
    log.debug(f"   解析 RSS: {subscirption.url}")
    parse_result = feedparser.parse(subscirption.url)

    # 如果有 bozo 错误但没有 entries，无法继续
    if parse_result.bozo:
        if parse_result.entries:
            log.warning(f"   {subscirption.name} 解析異常，但成功提取 {len(parse_result.entries)} 条条目: {parse_result.bozo_exception}")
        else:
            log.debug(f"Parsed Fields : {parse_result.keys()}")
            raise ValueError(f"   {subscirption.name} 解析失敗，无条目可提取: {parse_result.bozo_exception}")

    channel_image = ""
    if not subscirption.channel_image:
        # 提取频道级封面图：依次尝试 image.url → logo → icon（Atom 格式）
        if hasattr(parse_result.feed, "image"):
            channel_image = parse_result.feed.image.get("href", "")  # type: ignore
        elif hasattr(parse_result.feed, "logo"):
            channel_image = feed_icon_url = parse_result.feed.logo  # type: ignore
        else: 
            channel_image = feed_icon_url = parse_result.feed.get("icon", "")  # type: ignore
    
    # feedparser 的 feed.updated_parsed 用作日期缺失时的备用
    feed_updated_tuple:struct_time = parse_result.feed.get("updated_parsed")  # type: ignore

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
    return parsed_entries
