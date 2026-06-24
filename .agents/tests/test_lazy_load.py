import unittest
from unittest.mock import MagicMock
from datetime import datetime

# Assuming the subagents have implemented lazy_load_subscription_data and updated models.py
# If they haven't yet, this test will fail when run. We'll run it after they finish.
from rss2notion.models import Subscription
from rss2notion.notion.subscription import lazy_load_subscription_data

class TestLazyLoad(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.sub = Subscription(
            page_id="test-page-id",
            name="test",
            url="http://test.com",
            icon=None,
            channel_image=None,
            filterout_keywords=[],
            status="Active",
            last_update=datetime.now(),
            existing_articles=[],
            accumulated_errors=[]
        )

    def test_lazy_load_blocks_only(self):
        self.client.get_block_children.return_value = [{"id": "b1", "type": "paragraph"}]
        lazy_load_subscription_data(self.client, self.sub, fetch_blocks=True, fetch_articles=False)
        self.client.get_block_children.assert_called_once_with("test-page-id")
        self.client.query_pages_by_source.assert_not_called()
        self.assertTrue(getattr(self.sub, '_blocks_loaded', False))
        self.assertFalse(getattr(self.sub, '_articles_loaded', False))

    def test_lazy_load_articles_only(self):
        self.client.query_pages_by_source.return_value = ["http://article.com"]
        lazy_load_subscription_data(self.client, self.sub, entries_datasource_id="db-id", fetch_blocks=False, fetch_articles=True)
        self.client.get_block_children.assert_not_called()
        self.client.query_pages_by_source.assert_called_once_with("db-id", "test-page-id")
        self.assertFalse(getattr(self.sub, '_blocks_loaded', False))
        self.assertTrue(getattr(self.sub, '_articles_loaded', False))

    def test_lazy_load_cache(self):
        self.sub._blocks_loaded = True
        self.sub._articles_loaded = True
        lazy_load_subscription_data(self.client, self.sub, entries_datasource_id="db-id", fetch_blocks=True, fetch_articles=True)
        self.client.get_block_children.assert_not_called()
        self.client.query_pages_by_source.assert_not_called()

if __name__ == '__main__':
    unittest.main()
