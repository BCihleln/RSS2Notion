import inspect
import sys
import os

# 將工作目錄加入 sys.path 以便正確 import
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

def run_tests():
    print("Running tests for decouple-sync...")
    
    # 測試 1: 檢查 NotionClient 是否已經純化（移除特定業務方法）
    from rss2notion.notion.client import NotionClient
    client_methods = [func for func in dir(NotionClient) if callable(getattr(NotionClient, func)) and not func.startswith("__")]
    
    assert "query_pages_by_source" not in client_methods, "client.py 應移除 query_pages_by_source"
    assert "append_aggregated_urls_block" not in client_methods, "client.py 應移除 append_aggregated_urls_block"
    assert "append_error_block" not in client_methods, "client.py 應移除 append_error_block"
    
    # 測試 2: 檢查 article.py 是否成功建立並包含目標函數
    from rss2notion.notion import article
    assert hasattr(article, "query_existing_article_urls"), "article.py 缺少 query_existing_article_urls"
    assert hasattr(article, "create_article_page"), "article.py 缺少 create_article_page"
    assert hasattr(article, "should_skip_entry"), "article.py 缺少 should_skip_entry"
    
    # 測試 3: 檢查 subscription.py 是否包含新增的狀態處理函數
    from rss2notion.notion import subscription
    assert hasattr(subscription, "handle_subscription_failure"), "subscription.py 缺少 handle_subscription_failure"
    assert hasattr(subscription, "handle_subscription_success"), "subscription.py 缺少 handle_subscription_success"
    
    # 測試 4: 檢查 sync.py 是否成為真正的 Coordinator
    import rss2notion.sync as sync
    assert hasattr(sync, "process_subscription"), "sync.py 缺少 process_subscription"
    assert hasattr(sync, "_handle_aggregated_mode"), "sync.py 缺少 _handle_aggregated_mode"
    assert hasattr(sync, "_handle_standard_mode"), "sync.py 缺少 _handle_standard_mode"
    assert not hasattr(sync, "fetch_failed"), "sync.py 應移除 fetch_failed"
    assert not hasattr(sync, "fetch_success"), "sync.py 應移除 fetch_success"
    
    print("All decouple tests passed successfully!")

if __name__ == "__main__":
    try:
        run_tests()
    except AssertionError as e:
        print(f"Test Failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error during import or execution: {e}")
        sys.exit(1)
