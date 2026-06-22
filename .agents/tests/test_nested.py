import json
from rss2notion.utils.config import Config
from rss2notion.notion.client import NotionClient

config = Config.from_env()
client = NotionClient(config.notion_api_key)

page_id = '3337836f-ac92-8062-ba71-d4605bb50991'

nested_block = {
    "object": "block",
    "type": "callout",
    "callout": {
        "rich_text": [],
        "icon": {
            "type": "emoji",
            "emoji": "📦"
        },
        "children": [
            {
                "object": "block",
                "type": "toggle",
                "toggle": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {"content": "Aggregate Mode de-dup Info"},
                            "annotations": {"bold": True}
                        }
                    ],
                    "children": [
                        {
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [
                                    {
                                        "type": "text",
                                        "text": {"content": "hash1\nhash2\nhash3"}
                                    }
                                ]
                            }
                        }
                    ]
                }
            }
        ]
    }
}

res = client._request("PATCH", f"/blocks/{page_id}/children", json={"children": [nested_block]})
print("Success! Created block:", res.get("results", [{}])[0].get("id"))
