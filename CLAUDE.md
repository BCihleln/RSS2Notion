# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 項目簡介

RSS2Notion 是一個將 RSS 訂閱內容同步到 Notion 數據庫的 Python 工具，通過 GitHub Actions 每 8 小時自動運行。RSS 訂閱源從 Notion 訂閱數據庫讀取，將 Feed 中已包含的 HTML 內容（`content` 或 `summary` 字段）渲染為 Notion 塊，並支持關鍵詞過濾、訂閱源級別覆寫，以及自動清理過期文章。

## 設計邊界

本項目是一個**同步橋接工具**，預設用戶已有可用的 RSS/Atom 訂閱源。以下問題明確超出範圍，不應在此倉庫中實現：

- 從靜態網頁（CSS 選擇器抓取）產生 RSS 訂閱源
- 從 JavaScript 渲染的動態頁面抓取內容
- 從原始網頁抓取全文（Full-text import）

渲染的內容來源僅限於 RSS Feed 條目中 `content` 或 `summary` 字段已包含的 HTML 字符串。

## 開發環境

```bash
# 安裝依賴（需 Python >= 3.14 和 uv）
uv sync

# 運行（需設置環境變量）
export NOTION_API_KEY=...
export NOTION_ARTICLES_DATABASE_ID=...
export NOTION_FEEDS_DATABASE_ID=...
uv run python -m rss2notion

# 驗證模塊導入
uv run python -c "from rss2notion.notion.subscription import get_avaliable_subscriptions; print('OK')"
```

## 項目結構

```
rss2notion/
├── __main__.py           # 入口：並發拉取 RSS → 串行寫入 Notion → 清理過期文章
├── __init__.py
├── schema.py             # Notion 字段名和狀態值常量（SubscriptionFields / EntryFields / StatusValues / StateValues）
├── models.py             # 數據模型：RSSEntry, Subscription
├── rss.py                # RSS 解析（parse_rss, 日期/縮略圖/內容提取）
├── sync.py               # 輔助流程：fetch_success / fetch_failed（錯誤計數、狀態更新）
└── notion/
│   ├── client.py         # NotionClient：_request / _paginate / create_page / append_blocks / delete_page 等
│   ├── subscription.py   # 訂閱數據庫：get_avaliable_subscriptions / update_subscription_status / _parse_subscription
│   └── cleanup.py        # 自動清理過期文章：cleanup_expired_articles
└── utils/
    ├── config.py         # 環境變量 → Config dataclass
    ├── get_favicon.py    # 網站 favicon 抓取工具
    └── html2notion_block.py  # HTML → Notion Blocks 完整轉換管線

tools/
└── opml.py               # OPML 導入/導出（獨立腳本，直接運行）
```

## 環境變量

| 變量 | 必填 | 默認值 | 說明 |
|------|:----:|--------|------|
| `NOTION_API_KEY` | 是 | — | Notion Integration Token |
| `NOTION_ARTICLES_DATABASE_ID` | 是 | — | 文章數據庫 ID |
| `NOTION_FEEDS_DATABASE_ID` | 是 | — | 訂閱數據庫 ID |
| `TIMEZONE` | 否 | `Asia/Shanghai` | IANA 時區名 |
| `CLEANUP_DAYS` | 否 | `30` | 清理天數；-1 不清理且導入全部歷史 |

## Notion 數據庫屬性

### 訂閱數據庫（`NOTION_FEEDS_DATABASE_ID`）

| 字段名（Notion） | 常量 | 類型 | 說明 |
|----------------|------|------|------|
| `Feed Name` | `SubscriptionFields.NAME` | title | 訂閱源名稱 |
| `URL` | `SubscriptionFields.URL` | url | RSS 訂閱鏈接 |
| `Status` | `SubscriptionFields.STATUS` | select | Active / Error / Disabled |
| `Updates` | `SubscriptionFields.LAST_UPDATE` | last_edited_time | Notion 自動維護 |
| `Filterout` | `SubscriptionFields.FILTERLIST` | multi_select | 標題/URL 命中則跳過該文章 |
| `Articles` | `SubscriptionFields.ARTICLES` | relation | 關聯文章數（Notion 自動） |
| `Cleanup Days` | `SubscriptionFields.CLEANUP_DAYS` | number | 訂閱源級清理天數覆寫 |
| `Fetch Amount` | `SubscriptionFields.FETCH_AMOUNT` | number | 每次最多拉取篇數 |

### 文章數據庫（`NOTION_ARTICLES_DATABASE_ID`）

| 字段名（Notion） | 常量 | 類型 | 說明 |
|----------------|------|------|------|
| `Name` | `EntryFields.NAME` | title | 文章標題（含超鏈接） |
| `URL` | `EntryFields.URL` | url | 文章鏈接 |
| `Published` | `EntryFields.PUBLISHED` | date | 發布時間 |
| `State` | `EntryFields.STATE` | select | Unread / Reading / Star |
| `Source` | `EntryFields.SOURCE` | relation | 關聯到訂閱數據庫 |

> **注意**：新增 Notion property 需要在三處同步更新：`schema.py`（字段常量）→ `models.py`（Subscription dataclass 字段）→ `subscription.py:_parse_subscription`（解析邏輯）。其中解析步驟最容易遺漏。

## 架構說明

### 主同步流程（`__main__.py`）

**階段一：並發拉取 RSS**（純網絡 I/O，ThreadPoolExecutor）
- 從訂閱數據庫讀取所有 Status 為 Active 或空值的訂閱
- 所有訂閱源並發調用 `fetch_subscription`（內部調用 `parse_rss`）
- 失敗的訂閱調用 `fetch_failed`：追加帶時間戳的 Callout 錯誤塊；累積錯誤數超過 `mark_err_threshold` 時將 Status 升級為 Error

**階段二：串行寫入 Notion**（受速率限制，約 3 req/s）
1. 時間窗口粗篩：根據 `import_days`（優先取訂閱源的 `fetch_days`，否則用全局 `cleanup_days`）過濾舊文章
2. 數量限制：若設置了 `fetch_amount`，只取最新的 N 篇
3. URL 去重：與 `subscription.existing_articles`（已在讀取訂閱時批量預取）做 `in` 查找
4. 關鍵詞過濾：標題或 URL 命中 `filterout_keywords` 中任意詞則跳過
5. 渲染內容：從 `entry.content_html`（即 Feed 中的 `content` 或 `summary` 字段）調用 `html_to_notion_blocks` 轉換
6. 創建頁面：首批最多 `notion_block_limit`（100）個 block，剩餘通過 `append_blocks` 追加
7. 鎖定頁面：`lock_page` 防止數據庫視圖中誤操作
8. 成功後調用 `fetch_success`：清除歷史錯誤塊，將 Status 置為 Active

**階段三：清理過期文章**
- 對每個訂閱源調用 `cleanup_expired_articles`，只刪除該訂閱源且 State ≠ Star 的文章

### HTML → Notion Blocks 轉換（`utils/html2notion_block.py`）

兩階段管線，轉換的輸入為 RSS Feed 條目中已提供的 HTML 字符串：
- `parse_html(html)` — BeautifulSoup DOM 遞歸 → 中間格式（`list[dict]`），支持 paragraph / heading / image / list / table / code / quote / callout / divider
- `to_notion_blocks(intermediate)` — 中間格式 → Notion API block 格式

對外公開 API：
- `html_to_notion_blocks(html)` — 完整管線入口
- `entry_to_notion_blocks(entry)` — 從 RSSEntry 調用（兼容舊接口）

### 錯誤追蹤機制（`sync.py` + `notion/client.py`）

- 每次 RSS 拉取或寫入失敗，調用 `client.append_error_block(page_id, msg)` 追加 `⚠️` Callout 塊
- `fetch_failed` 統計頁面上現有錯誤塊數量（`subscription.accumulated_errors`，在讀取訂閱時預取）
- 累積數 > `mark_err_threshold`：Status 設為 Error
- 未達閾值：Status 清空為 None（保持下次仍可被輪詢到）
- 成功時：`fetch_success` 刪除所有歷史錯誤塊，Status 置為 Active

### 去重策略

- 讀取訂閱時，`get_avaliable_subscriptions` 預先批量查詢每個訂閱源在文章數據庫中的所有 URL，存入 `subscription.existing_articles`（`list[str]`）
- 寫入前做 `in` 查找去重
- 同時對發布時間做時間窗口粗篩，減少需要去重的條目數

### `_paginate` 通用分頁

`NotionClient._paginate(method, path, **kwargs)` 封裝了 Notion API 的分頁邏輯，返回 `list[dict]`。所有需要翻頁的查詢（訂閱列表、文章列表、塊列表）都通過它實現。

## 代碼修改原則

- **字段常量在 `schema.py`，不要硬編碼字段名**：所有 Notion property 名稱只在 `schema.py` 中定義，業務代碼通過常量引用
- **新增 Notion 字段的三步清單**：`schema.py` → `models.py` → `subscription.py:_parse_subscription`
- **改動現有文件只給片段**：除非是全新文件，否則只提供修改的代碼片段和精確的插入位置
- **批量操作優先**：需要多次查詢的場景，優先考慮批量 API 調用（參考 `query_pages_by_source` 的設計）
- **速率限制**：寫入 Notion 時，每次 `create_page` 後 `time.sleep(0.334)`（~3 req/s）；刪除操作後 `time.sleep(0.3)`
