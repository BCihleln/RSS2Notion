"""
OPML 導入與導出

import_opml(opml_path, config)  — 從 OPML 文件批量導入訂閱源到 Notion
export_opml(output_path, config) — 將 Notion 訂閱數據庫導出為 OPML 文件
"""

import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from xml.dom import minidom

from rss2notion.utils.config import Config
from rss2notion.utils.get_favicon import get_website_favicon
from rss2notion.notion.client import NotionClient
from rss2notion.schema import SubscriptionFields, StatusValues

# 訂閱數據庫 Tags 屬性名（multi_select）
TAGS_FIELD = "Group Tag"


# ──────────────────────────────────────────────
# 內部資料結構
# ──────────────────────────────────────────────

@dataclass
class _OPMLEntry:
    """從 OPML 解析出的單條訂閱源"""
    title: str          # 訂閱源名稱（可能為空）
    xml_url: str        # RSS feed URL
    html_url: str       # 對應網站 URL（用於抓取 favicon）
    group: str          # 所屬分組名稱（用作 Tag，可能為空）


# ──────────────────────────────────────────────
# OPML 導入
# ──────────────────────────────────────────────

def import_opml(opml_path: str | Path, config: Config) -> dict:
    """
    從 OPML 文件批量導入訂閱源到 Notion 訂閱數據庫。

    處理邏輯：
    - xmlUrl 已存在於 Notion 中 → 跳過（不重複新增）
    - 分組名稱（外層 outline 的 title）→ 寫入 Tags
    - 訂閱源 ICON → 從 htmlUrl 抓取網站 favicon
    - title/text 均為空 → 以 xmlUrl 作為名稱

    Args:
        opml_path: OPML 文件路徑
        config:    Config 實例（提供 API Key 與 Database ID）

    Returns:
        {"added": int, "skipped": int, "failed": int}
    """
    opml_path = Path(opml_path)
    log.info(f"開始導入 OPML：{opml_path}")

    entries = _parse_opml(opml_path)
    log.info(f"解析到 {len(entries)} 條訂閱源")

    client = NotionClient(
        api_key=config.notion_api_key,
        retry_times=config.retry_times,
        retry_delay=config.retry_delay,
    )

    # 批量查詢已存在的 URL，避免逐條查詢
    existing_urls = _fetch_all_feed_urls(client, config.feeds_database_id)
    log.info(f"Notion 中已有 {len(existing_urls)} 條訂閱源（用於去重）")

    added = skipped = failed = 0

    for idx, entry in enumerate(entries, 1):
        log.info(f"[{idx}/{len(entries)}] {entry.title or entry.xml_url}")

        # URL 去重
        if entry.xml_url in existing_urls:
            log.info("    → 已存在，跳過")
            skipped += 1
            continue

        try:
            # 嘗試抓取 favicon
            icon_url = ""
            if entry.html_url:
                try:
                    icon_url = get_website_favicon(entry.html_url)
                    log.info(f"    favicon: {icon_url}")
                except Exception as e:
                    log.warning(f"    favicon 獲取失敗：{e}")

            _create_feed_page(
                client=client,
                database_id=config.feeds_database_id,
                title=entry.title or entry.xml_url,
                xml_url=entry.xml_url,
                icon_url=icon_url,
                tags=[entry.group] if entry.group else [],
            )

            existing_urls.add(entry.xml_url)
            added += 1
            log.info(f"    ✓ 已新增")

        except Exception as e:
            log.error(f"    ✗ 新增失敗：{e}")
            failed += 1

        time.sleep(0.4)  # 控制 Notion API 速率

    log.info(f"導入完成 — 新增: {added}  跳過: {skipped}  失敗: {failed}")
    return {"added": added, "skipped": skipped, "failed": failed}


# ──────────────────────────────────────────────
# OPML 導出
# ──────────────────────────────────────────────

def export_opml(output_path: str | Path, config: Config) -> None:
    """
    將 Notion 訂閱數據庫（含 Disabled）全量導出為 OPML 文件。

    Tags 中的第一個值將作為 OPML 分組名稱；
    無 Tags 的訂閱源統一歸入「Uncategorized」分組。

    Args:
        output_path: 輸出 .opml 文件路徑
        config:      Config 實例
    """
    output_path = Path(output_path)
    log.info("開始導出 OPML …")

    client = NotionClient(
        api_key=config.notion_api_key,
        retry_times=config.retry_times,
        retry_delay=config.retry_delay,
    )

    subscriptions = _fetch_all_subscriptions(client, config.feeds_database_id)
    log.info(f"共讀取到 {len(subscriptions)} 條訂閱源")

    # 按第一個 Tag 分組；無 Tag 歸入 "Uncategorized"
    groups: dict[str, list[dict]] = {}
    for sub in subscriptions:
        group_name = sub["tags"][0] if sub["tags"] else "Uncategorized"
        groups.setdefault(group_name, []).append(sub)

    # 構建 OPML XML
    root = ET.Element("opml", version="1.0")

    head = ET.SubElement(root, "head")
    title_el = ET.SubElement(head, "title")
    title_el.text = f"RSS2Notion Export — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"

    body = ET.SubElement(root, "body")

    for group_name, feeds in sorted(groups.items()):
        group_outline = ET.SubElement(body, "outline", text=group_name, title=group_name)
        for feed in feeds:
            ET.SubElement(
                group_outline,
                "outline",
                text=feed["name"],
                title=feed["name"],
                type="rss",
                xmlUrl=feed["url"],
                htmlUrl=feed.get("html_url", ""),
            )

    # 格式化輸出（帶縮排）
    xml_str = minidom.parseString(
        ET.tostring(root, encoding="unicode")
    ).toprettyxml(indent="  ", encoding="UTF-8").decode("UTF-8")

    # minidom 會多加一行 <?xml?> 宣告，替換成標準版本
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + "\n".join(xml_str.splitlines()[1:])

    output_path.write_text(xml_str, encoding="utf-8")
    log.info(f"導出完成：{output_path}（{len(subscriptions)} 條）")


# ──────────────────────────────────────────────
# 內部輔助函數
# ──────────────────────────────────────────────

def _parse_opml(path: Path) -> list[_OPMLEntry]:
    """解析 OPML 文件，支援單層與雙層 outline 結構"""
    tree = ET.parse(path)
    body = tree.getroot().find("body")
    if body is None:
        raise ValueError("OPML 文件缺少 <body> 元素")

    entries: list[_OPMLEntry] = []

    for child in body:
        # 判斷是否為分組容器（沒有 xmlUrl 屬性）
        if child.get("xmlUrl"):
            # 頂層直接是 feed（無分組）
            entries.append(_outline_to_entry(child, group=""))
        else:
            # 外層是分組，內層才是 feed
            group_name = (child.get("title") or child.get("text") or "").strip()
            for feed_outline in child:
                if feed_outline.get("xmlUrl"):
                    entries.append(_outline_to_entry(feed_outline, group=group_name))

    return entries


def _outline_to_entry(outline: ET.Element, group: str) -> _OPMLEntry:
    """將單個 <outline> 元素轉為 _OPMLEntry"""
    title = (outline.get("title") or outline.get("text") or "").strip()
    return _OPMLEntry(
        title=title,
        xml_url=outline.get("xmlUrl", "").strip(),
        html_url=outline.get("htmlUrl", "").strip(),
        group=group,
    )


def _fetch_all_feed_urls(client: NotionClient, database_id: str) -> set[str]:
    """批量取得訂閱數據庫中所有已存在的 xmlUrl，回傳 URL 集合（用於去重）"""
    urls: set[str] = set()
    body: dict = {"page_size": 100}
    pages = client._paginate("POST", f"/databases/{database_id}/query", json=body)
    for page in pages:
        if (url := 
            page.get("properties", {})
            .get(SubscriptionFields.URL, {})
            .get("url", "")):
            urls.add(url)
    return urls


def _fetch_all_subscriptions(client: NotionClient, database_id: str) -> list[dict]:
    """取得訂閱數據庫的全部訂閱（含 Disabled），回傳簡易 dict 列表"""
    subs = []
    body: dict = {"page_size": 100}
    pages = client._paginate("POST", f"/databases/{database_id}/query", json=body)
    for page in pages:
        props = page.get("properties", {})
        url = props.get(SubscriptionFields.URL, {}).get("url", "")
        if not url:  # 略過沒有 URL 的頁面
            continue

        # 名稱
        name_items = props.get(SubscriptionFields.NAME, {}).get("title", [])
        name = "".join(item.get("plain_text", "") for item in name_items).strip()

        # Tags（multi_select）
        tags = [t["name"] for t in props.get(TAGS_FIELD, {}).get("multi_select", [])]

        subs.append({"name": name or url, "url": url, "tags": tags})

    return subs


def _create_feed_page(
    client: NotionClient,
    database_id: str,
    title: str,
    xml_url: str,
    icon_url: str,
    tags: list[str],
) -> dict:
    """在訂閱數據庫中建立一個新的訂閱源頁面"""

    payload: dict = {
        "parent": {"database_id": database_id},
        "properties": {
            SubscriptionFields.NAME: {
                "title": [{"text": {"content": title[:2000]}}]
            },
            SubscriptionFields.URL: {"url": xml_url},
        }
    }

    # 從 OPML 導入 Tag
    if tags:
        payload["properties"][TAGS_FIELD] = {
            "multi_select": [{"name": t} for t in tags]
        }

    # 有正常獲取 icon_url
    if icon_url:
        payload["icon"] = {"type": "external", "external": {"url": icon_url}}

    return client._request("POST", "/pages", json=payload)

# ──────────────────────────────────────────────
# 測試運行
# ──────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# 加载 .env 文件
from dotenv import load_dotenv
load_dotenv()
config = Config.from_env()

opml_file_path = r"feed.opml"

# 導入
result = import_opml(opml_file_path, config)

# 導出
# export_opml("backup.opml", config)