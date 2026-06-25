# 子階段：訂閱源領域邏輯遷移 (Subscription Domain)

## 目標
將與 `Subscription` 狀態、錯誤區塊、彙整區塊相關的特定業務邏輯從 `client.py` 和 `sync.py` 抽離，集中至 `notion/subscription.py`。

## 執行細節
1. **修改 `notion/client.py`**：
   - 將 `append_error_block`, `_build_error_block`, `append_aggregated_urls_block` 函數剪下。
2. **修改 `notion/subscription.py`**：
   - 將上述函數貼上，並修正相關的 `NotionClient` 調用（例如，將 `client.append_blocks` 改為外部傳入 `client` 實例進行調用）。
   - 將 `sync.py` 中的 `fetch_failed` 與 `fetch_success` 邏輯遷移過來，並重新命名為 `handle_subscription_failure` 與 `handle_subscription_success`。
3. **清理依賴**：
   - 確保 `notion/subscription.py` 引入必要的 `from datetime import datetime, timezone` 等套件。
   - 確保 `client.py` 移除不再使用的 imports。
   - **注意**：其他正在並行的 SubAgent 可能也會修改 `client.py`，提交流程中請務必 `git pull --rebase` 並解衝突。

## 收尾
- 將此檔案移至 `.agents/plans/1_processing/`。
- 修改完成後，以乾淨的 commit 提交至 `decouple-sync` 分支（勿產生 Merge Commit）。
