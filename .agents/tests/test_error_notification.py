import os
import unittest
from rss2notion.utils.config import Config
from rss2notion.notion.client import _build_error_block

class TestErrorNotification(unittest.TestCase):
    def setUp(self):
        # Setup required env vars for Config
        os.environ["NOTION_API_KEY"] = "dummy_key"
        os.environ["NOTION_ARTICLES_DATABASE_ID"] = "dummy_db"
        os.environ["NOTION_FEEDS_DATABASE_ID"] = "dummy_feed_db"

    def test_config_loads_user_id(self):
        os.environ["NOTION_USER_ID"] = "user-123"
        config = Config.from_env()
        self.assertEqual(config.notion_user_id, "user-123")

    def test_config_no_user_id(self):
        if "NOTION_USER_ID" in os.environ:
            del os.environ["NOTION_USER_ID"]
        config = Config.from_env()
        self.assertIsNone(config.notion_user_id)

    def test_build_error_block_with_mention(self):
        block = _build_error_block("Test error", timestamp="2026", user_id="user-123")
        rich_text = block["callout"]["rich_text"]
        self.assertEqual(len(rich_text), 2)
        self.assertEqual(rich_text[0]["text"]["content"], "[2026] Test error ")
        self.assertEqual(rich_text[1]["type"], "mention")
        self.assertEqual(rich_text[1]["mention"]["user"]["id"], "user-123")

    def test_build_error_block_without_mention(self):
        block = _build_error_block("Test error", timestamp="2026")
        rich_text = block["callout"]["rich_text"]
        self.assertEqual(len(rich_text), 1)
        self.assertEqual(rich_text[0]["text"]["content"], "[2026] Test error")

if __name__ == '__main__':
    unittest.main()
