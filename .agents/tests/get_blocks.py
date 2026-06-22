import os
import json
from rss2notion.utils.config import Config
from rss2notion.notion.client import NotionClient

config = Config.from_env()
client = NotionClient(config.notion_api_key)

# The test subscription ID should be known or I can fetch all active subscriptions
from rss2notion.notion.subscription import get_avaliable_subscriptions
subscriptions = get_avaliable_subscriptions(
    client, 
    config.feeds_datasource_id, 
    config.entries_datasource_id
)

for sub in subscriptions:
    if getattr(sub, "is_aggregated", False):
        print(f"Subscription: {sub.name}")
        blocks = client.get_block_children(sub.page_id)
        for b in blocks:
            if b.get("type") == "callout":
                print(json.dumps(b, indent=2, ensure_ascii=False))
