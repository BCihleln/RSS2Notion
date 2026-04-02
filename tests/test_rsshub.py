import sys
import os

# Dynamically resolve project root (one level up from tests/ directory)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


if sys.platform.startswith('win'):
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except Exception:
        pass

import logging
# Configure standard logging to show HTTP requests
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

from rss2notion.utils.fetcher import fetch_and_parse_feed, sign_rsshub_url

def main():
    test_url = "http://100.100.167.125:1200/gcores/tags/1535/articles"
    
    # Check or prompt for RSSHUB_ACCESS_KEY
    access_key = os.environ.get("RSSHUB_ACCESS_KEY")
    if not access_key:
        print("[INFO] No RSSHUB_ACCESS_KEY found in environment.")
        try:
            access_key = input("Please enter your RSSHub ACCESS_KEY (Press Enter if none): ").strip()
        except Exception:
            access_key = ""
        if access_key:
            os.environ["RSSHUB_ACCESS_KEY"] = access_key

    # Ensure RSSHUB_BASE_URL is set so sign_rsshub_url knows to sign it
    if not os.environ.get("RSSHUB_BASE_URL"):
        os.environ["RSSHUB_BASE_URL"] = "http://100.100.167.125:1200"

    print("\n" + "="*50)
    print(" Test 1: Verify URL Signing (Sign) Logic")
    print("="*50)
    print(f"Configured BASE_URL  : {os.environ['RSSHUB_BASE_URL']}")
    print(f"Configured ACCESS_KEY: {'Set (Hidden)' if os.environ.get('RSSHUB_ACCESS_KEY') else 'Not Set'}")
    
    signed_url = sign_rsshub_url(test_url)
    print(f"Original URL        : {test_url}")
    print(f"Signed URL          : {signed_url}")
    
    print("\n" + "="*50)
    print(" Test 2: Execute RSS Fetch and Parse")
    print("="*50)
    
    try:
        # fetch_and_parse_feed includes multi-stage fetching and will call sign_rsshub_url internally
        feed = fetch_and_parse_feed(test_url)
        
        print("\n" + "="*50)
        print(" Test Result")
        print("="*50)
        if feed.entries:
            print("Success! Connected and parsed successfully.")
            print(f"Feed Title  : {feed.feed.get('title', 'Unknown')}")
            print(f"Feed Count  : {len(feed.entries)} entries")
            print(f"Latest Entry: {feed.entries[0].get('title', 'No Title')}")
        else:
            print("Warning: Parsed successfully but no entries found.")
            if feed.bozo:
                print(f"Parser error detail: {feed.bozo_exception}")
    except Exception as e:
        print("\n" + "="*50)
        print("Test Failed")
        print("="*50)
        print(f"Error fetching or parsing:\n{e}")

if __name__ == "__main__":
    main()
