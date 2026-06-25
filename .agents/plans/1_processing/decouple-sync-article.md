# 子階段：文章領域邏輯遷移 (Article Domain)

## 目標
將與 RSS 文章 (Article/Entry) 寫入、屬性構建相關的領域邏輯從 `client.py` 中抽離，建立全新的 `notion/article.py` 模塊。

## 執行細節
1. **建立 `notion/article.py`**。
2. **修改 `notion/client.py`**：
   - 將 `create_page` 降級為純 HTTP Wrapper：移除 `entry` 與 `source_page_id` 參數，改為直接接收 `parent`、`properties`、`children`、`cover` 等字典參數，並移除內部對 `_build_entry_properties` 的呼叫。
   - 將 `query_pages_by_source` 與 `_build_entry_properties` 函數剪下。
3. **編寫 `notion/article.py`**：
   - 將 `query_pages_by_source` 貼上，並改名為 `query_existing_article_urls(client: NotionClient, datasource_id: str, source_page_id: str) -> list[str]`。
   - 將 `_build_entry_properties` 貼上，負責處理 `RSSEntry` 與 `EntryFields`。
   - 新增 `create_article_page(client: NotionClient, datasource_id: str, source_page_id: str | None, entry: RSSEntry, blocks: list[dict] | None = None) -> dict` 函數，內部呼叫 `_build_entry_properties` 後，再呼叫降級後的 `client.create_page`。
4. **清理依賴**：
   - 確保 `article.py` 引入 `RSSEntry`, `EntryFields`, `StateValues` 等。
   - `client.py` 應不再依賴 `RSSEntry`, `EntryFields`, `StateValues`。
   - **注意**：其他正在並行的 SubAgent 也會修改 `client.py`，請在提交時妥善 `git pull --rebase` 並解衝突。

## 收尾
- 將此檔案移至 `.agents/plans/1_processing/`。
- 修改完成後，以乾淨的 commit 提交至 `decouple-sync` 分支（勿產生 Merge Commit）。
