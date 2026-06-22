# 實作子計畫：Aggregated 模式 - Schema 與 API 更新

## 目標
為 RSS2Notion 擴充 Aggregated（彙整）模式所需的底層 Schema 與 Notion API 支援。

## 實作內容

### 1. 修改 `rss2notion/schema.py`
- `SubscriptionFields` 新增常數：`AGGREGATED = "Aggregated"`。

### 2. 修改 `rss2notion/models.py`
- `Subscription` 資料模型新增兩個屬性：
  - `is_aggregated: bool = False`
  - `aggregated_urls_block_id: str | None = None`

### 3. 修改 `rss2notion/notion/subscription.py`
- 在 `_parse_subscription` 中，讀取 `SubscriptionFields.AGGREGATED` (Checkbox 屬性)，並賦值給 `is_aggregated`。
- 在 `get_avaliable_subscriptions` 中，遍歷 `page_blocks` 時：
  - 除了原本抓取 ⚠️ Callout 作為 error 外，若發現含有 🔗 (Link) 或 📦 Emoji 的 Callout，將其文字內容 (可能被分拆在多個 `rich_text` item 中) 讀取、拼接，並以換行符號 `\n` 切割，存入 `sub.existing_articles` 陣列中。
  - 將該 🔗 Callout Block 的 ID 存入 `sub.aggregated_urls_block_id`。

### 4. 修改 `rss2notion/notion/client.py`
- 新增方法 `update_block_text(self, block_id: str, new_text: str)`：
  - 呼叫 `PATCH /v1/blocks/{block_id}`，傳入 `callout` 物件以更新其 `rich_text` 內容。
  - 注意：Notion 的單一 text object 上限為 2000 字元。若 `new_text` 超過此長度，需將其以 2000 字元為單位分割為多個 text object 放入 `rich_text` 陣列中。
- 新增或調整方法 `append_aggregated_urls_block(self, page_id: str, new_text: str)`：
  - 用於初次沒有 🔗 Callout 時，在頁面底部新增一個 Callout Block，Emoji 設為 🔗，內容同樣需支援超過 2000 字元的自動分割。

## 收尾要求
- 同步更新相關文檔 (如 README_*.md)。
- 完成後，請將變更使用 git commit 提交，Commit 訊息需清晰註明此子階段的實作。
