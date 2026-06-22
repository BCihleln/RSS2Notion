# 實作子計畫：Aggregated 模式 - 主流程與去重邏輯更新

## 目標
修改 RSS2Notion 的主流程 (`__main__.py`)，讓其支援 Aggregated 模式，包含 MD5 去重比對、單一頁面寫入，以及 Callout 狀態更新。

## 實作內容

### 1. MD5 去重判斷
- 讀取到 `entries` 後，若 `subscription.is_aggregated` 為 `True`：
  - 由於 `subscription.existing_articles` 現在儲存的是歷史抓取文章的 MD5 字串列表，我們需計算本次每篇 `entry` 的 MD5 值（例如使用 `hashlib.md5(entry.url.encode()).hexdigest()`）。
  - 過濾掉 MD5 值已存在於 `existing_articles` 的舊文章，僅保留真正的新文章。

### 2. 動態標題與單一頁面建立
- 取得這些新文章的最早 (`min(published)`) 與最晚 (`max(published)`) 發布時間。
- 呼叫 `client.create_page` 建立一個 Entry Page，標題格式為 `{最早時間} - {最晚時間} 彙整`（時間格式建議為 `MM-DD HH:MM` 或依系統習慣）。如果只有一篇文章，標題也可以只放一個時間。
- 跳過原有的 `for entry in entries:` 逐一建立 Page 的迴圈。

### 3. 轉換為 Bulleted List 寫入
- 將篩選出的新文章集合，轉換為 Bulleted List Item Blocks。
- 每個 Block 的格式為：`[文章標題](文章連結) (發布時間)`。
- 透過 `client.append_blocks` 分批（每批上限 100 個 block）寫入到該新建立的彙整頁面中。

### 4. 更新狀態 Callout (In-place Update)
- 寫入成功後，將本次 RSS 來源抓取到的 **所有** entries (包含已去重過濾掉的舊文章) 的 MD5 值，用換行符號 `\n` 拼接為單一字串。
- 若 `subscription.aggregated_urls_block_id` 存在：呼叫 `client.update_block_text` 直接更新該 Callout 的內容。
- 若不存在：呼叫 `client.append_aggregated_urls_block` 在頁面建立一個新的 🔗 Callout。

## 依賴提醒
- 此任務依賴 `aggregated-schema-api` 子計畫中對 `client` 以及 `models` 所擴充的屬性與方法，請假設那些屬性 (`is_aggregated`, `update_block_text` 等) 均已存在進行開發。

## 收尾要求
- 同步更新相關文檔 (如 README_*.md)。
- 完成後，請將變更使用 git commit 提交，Commit 訊息需清晰註明此子階段的實作。
