import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

def get_website_favicon(site_url):
    try:
        response = requests.get(site_url, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for <link rel="icon"> or <link rel="shortcut icon">
        icon_link = soup.find("link", rel=lambda x: x and 'icon' in x.lower())
        if icon_link and icon_link.get('href'):
            return urljoin(site_url, icon_link['href'])
            
        # Common fallback: domain/favicon.ico
        return urljoin(site_url, "/favicon.ico")
    except Exception as e:
        raise ValueError(f"網站 icon 解析異常 : {e}")

# ──────────────────────────────────────────────
# 測試運行
# ──────────────────────────────────────────────

# import feedparser
# result = feedparser.parse("https://rss.csdn.net/datawhale/rss/map")
# print(result.keys())
# print(result.feed.keys())

# # Usage with feedparser
# site_link = result.feed.get('link')
# if site_link:
#     print(f"Website Icon: {get_website_favicon(site_link)}")
