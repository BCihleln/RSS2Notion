# 評估與實施計劃：Tailscale + GitHub Actions 內網直連方案

基於我們的討論，我們決定採用 **單一 Workflow + Tailscale 內網直連** 的方案。這樣可以最簡化架構，且無需修改 `RSS2Notion` 的核心 Python 邏輯。

同時，我們實現了 **自建 RSSHub 安全訪問的自動簽名**：Notion 數據庫中的訂閱網址無需附帶密碼參數，RSS2Notion 會在拉取時自動根據密鑰動態生成 MD5 簽名並附加到請求中。

## 💡 Tailscale 接入 GitHub Actions 原理說明

1. **認證金鑰 (Auth Key / OAuth)**：您不需要提供個人的 Tailscale 帳號密碼。相反，您會在 Tailscale 後台生成一組機器用的 **Auth Key** 或 **OAuth Client Credentials**。
2. **GitHub Secrets**：將這組金鑰存入 GitHub 倉庫的 `Settings -> Secrets and variables -> Actions` 中（絕對安全，不會公開）。
3. **動態加入網路**：在 GitHub Actions 運行我們的主程式 (Python) 之前，會先執行一個官方的 `tailscale/github-action` 步驟。這個步驟會使用上述 Secret 進行靜默登入。
4. **臨時節點 (Ephemeral Node)**：登入後，GitHub 的伺服器會**暫時**變成您 Tailscale 網路中的一台虛擬機（擁有 `100.x.x.x` 的 IP）。
5. **內網直連**：接下來運行的 Python 程式，就可以像在您家裡一樣，直接透過 `http://<NAS的Tailscale IP>:1200` 訪問您的 RSSHub。
6. **自動銷毀**：Action 結束後，這個臨時連線會自動中斷並從您的 Tailscale 設備列表中移除，不留痕跡。

---

## 🛠️ 具體修改計劃 (Proposed Changes)

### 1. 修改 Workflow 檔案

#### [MODIFY] [sync.yml](../.github/workflows/sync.yml)

在 Checkout 代碼與 Setup Python 之間插入 Tailscale 連線步驟，並在主執行步驟中注入 `RSSHUB_BASE_URL` 與 `RSSHUB_ACCESS_KEY` 環境變量：

```yaml
      - name: Checkout
        uses: actions/checkout@v4

      # Connect to Tailscale network to access the self-hosted RSSHub on NAS
      # Details can be found in: docs/tailscale-github-actions-implementation-plan.md
      - name: Connect to Tailscale
        uses: tailscale/github-action@v2
        with:
          oauth-client-id: ${{ secrets.TS_OAUTH_CLIENT_ID }}
          oauth-secret: ${{ secrets.TS_OAUTH_SECRET }}
          tags: tag:ci

      # ... 中間安裝 uv 與 python 的步驟 ...

      - name: Run RSS sync
        env:
          NOTION_API_KEY: ${{ secrets.NOTION_API_KEY }}
          NOTION_ARTICLES_DATABASE_ID: ${{ secrets.NOTION_ARTICLES_DATABASE_ID }}
          NOTION_FEEDS_DATABASE_ID: ${{ secrets.NOTION_FEEDS_DATABASE_ID }}
          TIMEZONE: ${{ vars.TIMEZONE || 'Asia/Shanghai' }}
          CLEANUP_DAYS: ${{ vars.CLEANUP_DAYS || '30' }}
          RSSHUB_BASE_URL: ${{ vars.RSSHUB_BASE_URL }}
          RSSHUB_ACCESS_KEY: ${{ secrets.RSSHUB_ACCESS_KEY }}
        run: uv run python -m rss2notion
```

### 2. 修改 RSS 獲取模塊

#### [MODIFY] [fetcher.py](../rss2notion/utils/fetcher.py)

實現 `sign_rsshub_url` 函數。在獲取 RSS Feed 前，檢查 URL 是否匹配 `RSSHUB_BASE_URL`，若匹配且設置了 `RSSHUB_ACCESS_KEY`，則會自動提取 path 並使用 MD5 計算出 `code` 查詢參數附加到 URL 上，以此符合 RSSHub 的訪問限制機制：

```python
def sign_rsshub_url(url: str) -> str:
    access_key = os.environ.get("RSSHUB_ACCESS_KEY")
    base_url = os.environ.get("RSSHUB_BASE_URL")
    if not access_key or not base_url:
        return url

    try:
        url_parsed = urlparse(url)
        base_parsed = urlparse(base_url)

        if url_parsed.netloc and url_parsed.netloc == base_parsed.netloc:
            route_path = url_parsed.path
            if not route_path.startswith('/'):
                route_path = '/' + route_path

            text_to_hash = route_path + access_key
            code = hashlib.md5(text_to_hash.encode('utf-8')).hexdigest()

            query_params = dict(parse_qsl(url_parsed.query))
            query_params['code'] = code

            new_query = urlencode(query_params)
            return urlunparse((
                url_parsed.scheme,
                url_parsed.netloc,
                url_parsed.path,
                url_parsed.params,
                new_query,
                url_parsed.fragment
            ))
    except Exception as e:
        log.warning(f"   簽名 RSSHub URL 失敗: {e}")

    return url
```

---

### 3. 用戶準備工作 (需由您手動完成)

1. **設定 Tailscale ACL**：前往 Tailscale Admin Console 的 Access Control 頁面，在策略中定義 `tag:ci` 的擁有者（通常是管理員群組），例如：
   ```json
   "tagOwners": {
       "tag:ci": ["autogroup:admin"],
   }
   ```
2. **生成 OAuth Client**：前往 Tailscale Settings -> OAuth，點擊生成新的 OAuth Client。在 Scope 權限中務必勾選：
   - **Devices**: `Write` (或 `Read/Write`)
   - **Auth keys**: `Write` (❗️必須勾選此 Write 權限，否則 GitHub Actions 無法為臨時機器生成註冊金鑰)
   並且在 **Allowed tags** 中勾選您定義的 `tag:ci`。

2. **設定 GitHub Secrets**：
   * `TS_OAUTH_CLIENT_ID`：Tailscale Client ID。
   * `TS_OAUTH_SECRET`：Tailscale Client Secret。
   * `RSSHUB_ACCESS_KEY`：您的自建 RSSHub `ACCESS_KEY` 密鑰。
3. **設定 GitHub Variables**：
   * `RSSHUB_BASE_URL`：您 NAS 在 Tailscale 中的 IP + 端口（例如 `http://100.x.x.x:1200`）。
4. **Notion 配置**：
   * 您的 Notion 訂閱網址**只需**填寫常規的自建內網 URL，例如：`http://100.x.x.x:1200/bilibili/user/dynamic/2262511`。
   * **無需**在 URL 手動拼接 `?code=...`，RSS2Notion 會自動動態計算並注入。
