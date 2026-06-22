# 需求二：出錯通知 (Error 狀態 Mention) 實作計畫

本計畫預計在新 Session 中進行實作。

## 需求背景
當 RSS 來源狀態轉換為 Error 時（通常是連續抓取失敗達到閾值），在 Notion 的 RSS Source 頁面中追加的錯誤 Callout Block 內，同時 Mention 使用者 (`@Bill Chen`)，以利觸發 Notion 提醒，及早發現失效的訂閱源。

## 實作方案
採用「直接在 RSS Source 頁面的錯誤記錄 Block 中追加 Mention」的輕量化方案。

### 1. 配置與 Schema 更新
- **新增使用者 ID 環境變數**：在 `.env` 與 `Config` 類別中新增 `NOTION_USER_ID`，用於 Mention 指定使用者。

**需修改的檔案：**
- `rss2notion/utils/config.py`: `Config` 類別新增 `notion_user_id: str | None = None`，並從 `os.environ.get("NOTION_USER_ID")` 讀取。

### 2. Notion Client 及核心 API 更新
- **支援 Mention 寫入**：修改 `client.py` 內的錯誤區塊生成邏輯，加入 User Mention 物件。

**需修改的檔案：**
- `rss2notion/notion/client.py`:
  - `NotionClient.__init__` 增加 `notion_user_id` 參數，並保存為實例變數。
  - `_build_error_block` 函數增加 `user_id` 參數。若提供 `user_id`，則在 Callout block 的 `rich_text` 陣列末端追加 Mention 物件：
    ```json
    {
      "type": "mention", 
      "mention": {
        "type": "user", 
        "user": {"id": user_id}
      }
    }
    ```
  - `append_error_block` 呼叫 `_build_error_block` 時，傳入 `self.notion_user_id`。

### 3. 主流程邏輯更新
- **參數傳遞**：確保主流程在初始化 `NotionClient` 時，將 `config.notion_user_id` 正確傳入。

**需修改的檔案：**
- `rss2notion/__main__.py`: 
  - 初始化 `NotionClient` 時傳入 `notion_user_id=config.notion_user_id`。

## 驗證步驟
1. 確保 `.env` 已設定 `NOTION_USER_ID` (可透過 Notion API 取得使用者的 ID)。
2. 將某個 `Subscription` 的 URL 改為無效網址。
3. 執行程式直到該來源觸發 `Error` 狀態。
4. 檢查 Notion 中該來源的頁面，新追加的錯誤 Callout 中應出現藍色的 `@使用者` 標籤，並觸發 Notion 的通知推播。
