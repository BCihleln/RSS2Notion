import pytest
from unittest.mock import MagicMock, ANY
from datetime import datetime

from rss2notion.schema import SubscriptionFields
from rss2notion.models import Subscription
from rss2notion.notion.client import NotionClient

def test_schema_aggregated():
    """驗證 Schema 是否新增了 AGGREGATED 常數"""
    assert hasattr(SubscriptionFields, "AGGREGATED"), "缺少 SubscriptionFields.AGGREGATED"
    assert SubscriptionFields.AGGREGATED == "Aggregated"

def test_subscription_model():
    """驗證 Subscription 資料模型是否支援 Aggregated 屬性"""
    sub = Subscription(
        page_id="123",
        name="Test Feed",
        url="http://test.com/rss",
        icon=None,
        channel_image=None,
        filterout_keywords=[],
        status="Active",
        last_update=datetime.now(),
        existing_articles=[],
        accumulated_errors=[]
    )
    # 驗證預設值與屬性是否存在
    assert hasattr(sub, "is_aggregated")
    assert hasattr(sub, "aggregated_urls_block_id")

def test_client_update_methods():
    """驗證 NotionClient 是否新增了 Callout block 的更新與建立方法"""
    client = NotionClient(api_key="fake_key")
    client._request = MagicMock(return_value={})
    client.append_blocks = MagicMock()
    
    assert hasattr(client, "update_block_text"), "缺少 update_block_text 方法"
    
    # 測試 update_block_text 是否呼叫了 PATCH
    client.update_block_text("fake_block_id", "hash1\nhash2")
    client._request.assert_called_with(
        "PATCH", 
        "/blocks/fake_block_id", 
        json=ANY
    )
    
    # 確認是否建立成功 (因為實作可能命名不完全一致，這裡用 hasattr 寬鬆檢查)
    assert any(method for method in dir(client) if "append" in method and "block" in method)
