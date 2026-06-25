# 子階段：同步流程協調者解耦 (Coordinator Domain)

## 目標
將臃腫在 `__main__.py` 的寫入流程與過濾邏輯遷移至 `sync.py`，使 `sync.py` 成為真正的中控大腦，而 `__main__.py` 僅負責最上層的依賴注入與併發排程。

## 執行細節
1. **修改 `__main__.py`**：
   - 將 `_should_skip_entry` 移出（移至 `notion.article`，但若此時 `article.py` 尚未完成，你可以直接呼叫 `from .notion.article import should_skip_entry`）。
   - 將 `_handle_aggregated_mode`, `_handle_standard_mode`, `_write_page_with_blocks`, `process_subscription` 全部剪下，並移至 `sync.py`。
   - `__main__.py` 保留環境驗證、取得訂閱清單、ThreadPool 併發拉取 RSS，接著在迴圈中呼叫 `sync.process_subscription(client, sub, entries)`。
2. **修改 `sync.py`**：
   - 貼上從 `__main__.py` 剪下的函數。
   - 將原本的 `fetch_failed` 與 `fetch_success` 移除，並將所有呼叫改為 `from .notion.subscription import handle_subscription_failure, handle_subscription_success`。
   - 將 `_write_page_with_blocks` 中的 `client.create_page` 改為使用 `article.py` 的新介面（如 `from .notion.article import create_article_page`）。
3. **注意並行開發的依賴**：
   - 此階段的重構依賴於 `article.py` 和 `subscription.py` 的新介面。即便其他 SubAgent 尚未提交這些檔案，你仍應假定這些介面存在並完成你的重構。
   - 請在提交流程中妥善 `git pull --rebase`，解決衝突並確保代碼乾淨。

## 收尾
- 將此檔案移至 `.agents/plans/1_processing/`。
- 修改完成後，以乾淨的 commit 提交至 `decouple-sync` 分支（勿產生 Merge Commit）。
