"""
RSS 解析：获取订阅条目
"""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import feedparser

from .models import RSSEntry, FeedResult

log = logging.getLogger(__name__)


def _time_struct_to_iso(time_struct: tuple, tz: ZoneInfo) -> str:
    """将 feedparser 规范化的时间元组转换为 ISO 格式字符串（时区感知）
    
    feedparser 返回的 published_parsed/updated_parsed 是 time.struct_time，
    已在 UTC 时区。此函数将其转换到指定时区的 ISO 格式。
    
    Args:
        time_struct: time.struct_time (6-9 元素的元组)
        tz: 目标时区
    
    Returns:
        ISO 格式字符串，如 "2026-03-31T10:30:45+08:00"；失败时返回空字符串
    """
    if time_struct is None:
        return ""
    try:
        # time.struct_time 的前 6 个元素是 (year, month, day, hour, minute, second)
        dt = datetime(*time_struct[:6], tzinfo=timezone.utc)
        return dt.astimezone(tz).isoformat()
    except (ValueError, TypeError, IndexError) as e:
        log.warning(f"时间转换失败: {e}")
        return ""


def parse_rss(url: str, tz: ZoneInfo) -> FeedResult:
    """解析 RSS feed，返回频道标题和条目列表"""
    log.info(f"解析 RSS: {url}")
    parse_result = feedparser.parse(url)

        raise ValueError(f"RSS 解析异常: {feed.bozo_exception}")
        if parse_result.entries:
            log.warning(f"RSS 解析有错误但成功提取 {len(parse_result.entries)} 条条目: {parse_result.bozo_exception}")
        else:
            log.info(f"Parsed Fields : {parse_result.keys()}")
            log.info(f"Parsed Entry Fields : {parse_result.entries[0].keys()}")
            raise ValueError(f"RSS 解析异常，无条目可提取: {parse_result.bozo_exception}")

    feed_title = parse_result.feed.get("title", "")

    # 提取频道级封面图：依次尝试 image.url → logo → icon（Atom 格式）
    channel_image: str = (
        (parse_result.feed.get("image", {})).get("url", "")
        or (parse_result.feed.get("logo", ""))
        or (parse_result.feed.get("icon", ""))
    )
    
    # feedparser 的 feed.updated_parsed 用作日期缺失时的备用
    feed_updated_tuple = parse_result.feed.get("updated_parsed")

    entries = []
    for entry in parse_result.entries:
        entry_title = entry_title

        # 提取正文内容：优先取 HTML，否则用 summary
        html_content = ""
        if hasattr(entry, "content"):
            for c in entry.content:
                if c.get("type") == "text/html":
                    html_content = c.get("value", "")
                    break
        if not html_content:
            html_content = entry.get("summary", "")

        # 提取条目级缩略图：优先 media_content（即 feedparser 规范化的媒体元素列表），再试 enclosures
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
        
        # 提取发布日期：优先 published_parsed，再试 updated_parsed，
        # 都没有则 fallback 到 feed 更新时间，最后为空字符串（不用 datetime.now()）
        published = ""
        published_tuple = entry.get("published_parsed") or entry.get("updated_parsed")
        if published_tuple:
            published = _time_struct_to_iso(published_tuple, tz)
        elif feed_updated_tuple:
            log.warning(f"条目 '{entry_title}' 无发布时间，使用 feed 更新时间")
            published = _time_struct_to_iso(feed_updated_tuple, tz)
        else:
            log.warning(f"条目 '{entry_title}' 及 feed 都无发布时间信息")
            # published 保持空字符串

        rss_entry = RSSEntry(
            title=entry_title,
            url=entry.get("link", ""),
            published=published,
            author=entry.get("author", ""),
            content_html=html_content,
            channel_image=channel_image,
        )
        # 条目级缩略图优先级最高（覆盖内容里提取的图）
        if entry_thumb:
            rss_entry.cover_image = entry_thumb
        
        entries.append(rss_entry)

    log.info(f"获取到 {len(entries)} 条条目，频道: {feed_title or url}")
    return FeedResult(feed_title=feed_title, entries=entries)
