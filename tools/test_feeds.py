import feedparser
import logging
from curl_cffi import requests as cffi_requests
from rss2notion.utils.fetcher import fetch_and_parse_feed

logging.basicConfig(level=logging.INFO)

urls = [
    "https://rsshub.app/anthropic/research",
    "https://rsshub.app/gcores/news",
    "https://rsshub.app/gcores/tags/1535/articles",
    "https://rsshub.app/gcores/categories/28/articles",
    # "https://www.gcores.com/rss",
    # "https://news.pts.org.tw/xml/newsfeed.xml"
]

for url in urls:
    print(f"\n{'='*50}\nTesting: {url}")
    
    # 1. 現有方法 (feedparser -> requests)
    print("\n--- Method 1: Current Fetcher (requests) ---")
    try:
        d = fetch_and_parse_feed(url)
        if getattr(d, 'bozo', False):
            print(f"Result: Bozo Exception: {d.bozo_exception}")
        else:
            print(f"Result: SUCCESS! Entries: {len(d.entries)}")
    except Exception as e:
        print(f"Result: ERROR: {e}")
        
    # 2. curl_cffi 方法
    print("\n--- Method 2: curl_cffi ---")
    try:
        # impersonate="chrome110" makes it mimic Chrome's TLS/JA3 fingerprints
        response = cffi_requests.get(url, impersonate="chrome110", timeout=15)
        print(f"HTTP Status: {response.status_code}")
        if response.status_code == 200:
            d2 = feedparser.parse(response.content)
            if getattr(d2, 'bozo', False) and getattr(d2, 'entries', []) == []:
                print(f"Result: SUCCESS but Bozo: {d2.bozo_exception}")
            else:
                print(f"Result: SUCCESS! Entries: {len(d2.entries)}")
        else:
            print(f"Result: FAILED with status {response.status_code}")
    except Exception as e:
        print(f"Result: ERROR: {e}")
