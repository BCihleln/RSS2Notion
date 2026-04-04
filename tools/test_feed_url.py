
import requests
import feedparser


def _fetch_feed_content(url: str, timeout: int = 15) -> str:
    """
    抓取 Feed 原始內容。
    先以正常 SSL 驗證請求；若遇到 SSL 錯誤，警告後以 verify=False 重試。
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.SSLError as e:
        print(f"SSL 驗證失敗，跳過驗證重試: {url}")
        resp = requests.get(url, headers=headers, timeout=timeout, verify=False)
        resp.raise_for_status()
        return resp.text

# raw_url = "https://news.pts.org.tw/xml/newsfeed.xml"
raw_url = "https://www.youtube.com/feeds/videos.xml?channel_id=UC0vR0lxRAjvQOSAm_bA1P3A"

raw_content = _fetch_feed_content(raw_url)
result:dict = feedparser.parse(raw_content)
feed:dict = result.feed # type: ignore 

if feed: 
    print(result.keys())
    print(feed.keys()) # type: ignore 
    print(result.entries[0].keys()) # type: ignore 
    print(len(result.entries))
else:
    print(f"bozo : {result.bozo} | exception : {result.bozo_exception}")
