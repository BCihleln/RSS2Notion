"""
主同步流程编排
"""

import logging
import time

from .utils.config import Config

from .notion.client import NotionClient
from .notion.subscription import update_subscription_status
from .schema import StatusValues
from .rss import parse_rss

from .models import Subscription, RSSEntry

log = logging.getLogger(__name__)
config = Config.from_env()

# ──────────────────────────────────────────────
# 内部輔助函數
# ──────────────────────────────────────────────

def fetch_subscription(subscription: Subscription):
    """
    單個訂閱源的 RSS 拉取，返回 (Subscription, FeedResult or Exception)
    便於并發拉取 RSS
    """
    try:
        return subscription, parse_rss(subscription)
    except Exception as e:
        return subscription, e

def fetch_failed(
    client: NotionClient,
    subscription: Subscription,
    error_msg: str,
) -> None:
    """处理 RSS 拉取/写入全部失败的情况。

    规则：
    - 统计页面上已有的错误 Callout 块数量
    - 累积（含本次）达到 config.mark_err_threshold 时，将状态升级为 Error
    - 未达阈值时，将状态清空（select → None），保持订阅仍可被下次轮询到
    - 无论如何都追加带时间戳的错误块
    """
    existing_error_count = len(subscription.accumulated_errors)

    # 含本次即将追加的一条
    total_after = existing_error_count + 1
    log.debug(f"   错误块计数: {existing_error_count} → {total_after}（阈值 {config.mark_err_threshold}）"
    )

    mark_as_err = ""
    new_status: str | None
    if total_after > config.mark_err_threshold:
        mark_as_err = "標記爲 Error"
        new_status = StatusValues.ERROR
    else:
        log.debug(f"   错误未达阈值，状态清空（将在下次轮询重试）")
        new_status = None  # 清空 select，保持可被下次轮询
    
    log.warning(f"订阅 [{subscription.name}] 累积错误达 {total_after} 次 {mark_as_err}")

    update_subscription_status(
        client, subscription,
        status=new_status,
        error_msg=error_msg,
    )


def fetch_success(client: NotionClient, subscription: Subscription) -> None:
    """拉取成功后：清空历史错误块，将状态置为 Active。"""
    """
    清除页面中所有错误 Callout 块。
    返回实际删除的块数量。
    """
    blocks = subscription.accumulated_errors
    deleted = 0
    for block in blocks:
        try:
            client.delete_block(block["id"])
            deleted += 1
            time.sleep(0.2)  # 避免触发速率限制
        except Exception as e:
            log.warning(f"   删除错误块 {block['id']} 失败（跳过）: {e}")

    if deleted:
        log.info(f"   ✓ 已清除 {deleted} 个历史错误块")

    update_subscription_status(
        client, subscription,
        status=None, # dev for testing the same feed without changing state
    )
