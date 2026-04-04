import os
from dotenv import load_dotenv
from rss2notion.utils.config import Config
from rss2notion.notion.client import NotionClient
from rss2notion.notion.subscription import _parse_subscription
from rss2notion.schema import SubscriptionFields, StatusValues

load_dotenv()
config = Config.from_env()
client = NotionClient(config.notion_api_key)

body = {
    "filter": {
        "property": SubscriptionFields.STATUS,
        "select": {"equals": StatusValues.ERROR},
    },
    "page_size": 100,
}

pages = client._paginate("POST", f"/data_sources/{config.feeds_datasource_id}/query", json=body)
for page in pages:
    sub = _parse_subscription(page)
    if sub:
        print(f"Name: {sub.name}")
        print(f"URL: {sub.url}")
        print("-" * 20)
