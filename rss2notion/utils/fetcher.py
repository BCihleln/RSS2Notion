import logging
import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

log = logging.getLogger(__name__)

# Suppress insecure request warnings when verify=False is used
urllib3.disable_warnings(InsecureRequestWarning)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def fetch_feed_content(url: str, timeout: int = 15) -> bytes:
    """
    Fetch the content of an RSS feed from the given URL.
    
    This function uses a modern browser User-Agent to avoid being blocked by
    anti-bot systems (like Cloudflare/RSSHub). It also implements an SSL
    fallback mechanism: if the strict SSL verification fails, it will log a
    warning and retry without SSL verification.
    
    Args:
        url: The URL of the RSS feed.
        timeout: Request timeout in seconds.
        
    Returns:
        The raw bytes content of the feed.
        
    Raises:
        requests.RequestException: If the network request fails (e.g. 403, 404).
    """
    try:
        # First attempt: standard request with SSL verification
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout, verify=True)
        # response.raise_for_status()
        # return response.content
    except requests.exceptions.SSLError as e:
        log.warning(f"   SSL verification failed for {url}. Retrying with verify=False... ({str(e)})")
        # Fallback attempt: bypass SSL verification
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout, verify=False)
    response.raise_for_status()
    return response.content
