import sys
import os
import logging
from rss2notion.utils.config import Config
from rss2notion.notion.client import NotionClient
from rss2notion.notion.subscription import get_avaliable_subscriptions

logging.basicConfig(level=logging.INFO)

def main():
    config = Config.from_env()
    client = NotionClient(config.notion_api_key)

    subscriptions = get_avaliable_subscriptions(
        client, 
        config.feeds_datasource_id, 
        config.entries_datasource_id
    )

    found_aggregated = False
    for sub in subscriptions:
        if getattr(sub, "is_aggregated", False):
            found_aggregated = True
            print("="*40)
            print(f"Subscription: {sub.name}")
            print(f"is_aggregated: {sub.is_aggregated}")
            print(f"Callout block ID: {sub.aggregated_urls_block_id}")
            
            blocks = client.get_block_children(sub.page_id)
            callout_count = 0
            for b in blocks:
                if b.get("type") == "callout":
                    icon = b.get("callout", {}).get("icon", {}).get("emoji", "")
                    if icon in ("🔗", "📦"):
                        callout_count += 1
                        rich_text = b["callout"].get("rich_text", [])
                        content = "".join(rt.get("plain_text", "") for rt in rich_text)
                        
                        if not content and b.get("has_children"):
                            callout_children = client.get_block_children(b["id"])
                            if callout_children and callout_children[0].get("type") == "toggle":
                                toggle_children = client.get_block_children(callout_children[0]["id"])
                                if toggle_children and toggle_children[0].get("type") == "paragraph":
                                    nested_rich_text = toggle_children[0]["paragraph"].get("rich_text", [])
                                    content = "".join(rt.get("plain_text", "") for rt in nested_rich_text)
                                    
                        url_list = [c for c in content.split("\n") if c]
                        print("Found URL Callout Block.")
                        print(f"Number of URLs in Callout: {len(url_list)}")
                        if len(url_list) > 0:
                            print("Sample URLs:")
                            for u in url_list[:3]:
                                print(f"  - {u}")
                        
            if callout_count == 0:
                print("No URL Callout block with 🔗 or 📦 found in this subscription!")
            print("="*40)

if __name__ == "__main__":
    main()
