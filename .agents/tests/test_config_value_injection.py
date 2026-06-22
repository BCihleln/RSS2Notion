import os
import pytest
import sys
from importlib import reload

# 確保 rss2notion 模組能被引入
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from rss2notion.utils.config import Config
from rss2notion.schema import StatusValues

def setup_env():
    os.environ["NOTION_API_KEY"] = "test"
    os.environ["NOTION_ARTICLES_DATABASE_ID"] = "test"
    os.environ["NOTION_FEEDS_DATABASE_ID"] = "test"

def test_config_value_injection_defaults():
    setup_env()
    # 測試沒有環境變數時的預設值
    if "SUBSCRIPTION_FETCH_STATUS" in os.environ:
        del os.environ["SUBSCRIPTION_FETCH_STATUS"]
    if "SUBSCRIPTION_UPDATE_STATUS" in os.environ:
        del os.environ["SUBSCRIPTION_UPDATE_STATUS"]
    
    config = Config.from_env()
    assert config.subscription_fetch_status == StatusValues.ACTIVE
    assert config.subscription_update_status == True

def test_config_value_injection_custom():
    setup_env()
    # 測試開發環境下自訂的環境變數
    os.environ["SUBSCRIPTION_FETCH_STATUS"] = ""
    os.environ["SUBSCRIPTION_UPDATE_STATUS"] = "false"
    
    config = Config.from_env()
    assert config.subscription_fetch_status == ""
    assert config.subscription_update_status == False
    
    # 清理
    del os.environ["SUBSCRIPTION_FETCH_STATUS"]
    del os.environ["SUBSCRIPTION_UPDATE_STATUS"]
