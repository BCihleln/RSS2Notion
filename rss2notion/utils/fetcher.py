import logging
import requests
import urllib3
import feedparser
import urllib.error
import hashlib
import os
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from urllib3.exceptions import InsecureRequestWarning

log = logging.getLogger(__name__)

# Suppress insecure request warnings when verify=False is used
urllib3.disable_warnings(InsecureRequestWarning)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def sign_rsshub_url(url: str) -> str:
    """
    If url matches RSSHUB_BASE_URL and RSSHUB_ACCESS_KEY is set,
    automatically append the MD5 access code query parameter as required by RSSHub's ACCESS_KEY feature.
    """
    access_key = os.environ.get("RSSHUB_ACCESS_KEY")
    base_url = os.environ.get("RSSHUB_BASE_URL")
    if not access_key or not base_url:
        return url

    try:
        url_parsed = urlparse(url)
        base_parsed = urlparse(base_url)

        # Check if the network location (domain + port) matches
        if url_parsed.netloc and url_parsed.netloc == base_parsed.netloc:
            route_path = url_parsed.path
            if not route_path.startswith('/'):
                route_path = '/' + route_path

            # RSSHub MD5 format: md5(route_path + access_key)
            text_to_hash = route_path + access_key
            code = hashlib.md5(text_to_hash.encode('utf-8')).hexdigest()

            query_params = dict(parse_qsl(url_parsed.query))
            query_params['code'] = code

            new_query = urlencode(query_params)
            signed_url = urlunparse((
                url_parsed.scheme,
                url_parsed.netloc,
                url_parsed.path,
                url_parsed.params,
                new_query,
                url_parsed.fragment
            ))
            log.debug(f"   自動對 RSSHub URL 進行簽名安全訪問")
            return signed_url
    except Exception as e:
        log.warning(f"   簽名 RSSHub URL 失敗: {e}")

    return url

def fetch_and_parse_feed(url: str, timeout: int = 15) -> feedparser.FeedParserDict:
    """
    Multi-stage fetch and parse strategy for RSS feeds:
    1. Try default feedparser (often bypasses some bot protections that target modern browsers)
    2. Fallback to requests + Chrome User-Agent (verify=True)
    3. Fallback to requests + Chrome User-Agent (verify=False)
    
    Raises Exceptions for HTTP 301, 410, or if all fallbacks fail.
    """
    url = sign_rsshub_url(url)
    log.debug(f"   Fetch [Stage 1] 使用 feedparser 預設方式獲取: {url}")
    d = feedparser.parse(url)
    
    status = getattr(d, 'status', None)
    
    # 處理特殊需要中斷的狀態碼
    if status == 301:
        new_url = getattr(d, 'href', '未知')
        raise Exception(f"HTTP 301 永久重定向: 該訂閱源已轉移，請更新 URL。新 URL: {new_url}")
    elif status == 410:
        raise Exception("HTTP 410 已刪除: 該訂閱源已永久停止服務。")

    # 判斷是否發生網路錯誤 (觸發進入下一階段)
    is_network_error = False
    if status in (403, 404, 429, 500, 502, 503, 521, 400):
        is_network_error = True
    elif d.bozo == 1:
        # Check if the exception is network-related (e.g. URLError, ConnectionError)
        if isinstance(d.bozo_exception, (urllib.error.URLError, ConnectionError, TimeoutError)):
            is_network_error = True
            
    # 如果無網路錯誤，且成功解析出 entries 或原本就無錯誤，則視為成功
    if not is_network_error and (d.entries or not d.bozo):
        return d
        
    log.debug(f"         [Stage 1] 失敗 (Status: {status}{", Bozo: "+str(d.bozo_exception) if d.bozo else ''})")

    # Stage 2: Requests + UserAgent + verify=True
    log.debug(f"         [Stage 2] 嘗試使用 requests + User-Agent (verify=True)")
    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout, verify=True)
        response.raise_for_status()
        return feedparser.parse(response.content)
    except requests.exceptions.SSLError as ssl_err:
        log.info(f"         [Stage 2] SSL 驗證失敗 : {str(ssl_err)}")
        pass # Proceed to Stage 3
    except requests.exceptions.RequestException as e:
        # 其他 HTTP 錯誤則直接拋出，不再嘗試關閉 SSL
        raise Exception(f"         [Stage 2] 獲取失敗 : {str(e)}")

    # Stage 3: Requests + UserAgent + verify=False
    log.debug(f"   Fetch [Stage 3] 嘗試使用 requests + User-Agent (verify=False)")
    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout, verify=False)
        response.raise_for_status()
        return feedparser.parse(response.content)
    except requests.exceptions.RequestException as e:
        raise Exception(f"         [Stage 3] 獲取失敗 : {str(e)}")
