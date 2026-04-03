"""
订阅数据库：读取活跃订阅、更新订阅状态
"""

import logging

from ..models import Subscription
from .client import NotionClient
from .schema import SubscriptionFields, StatusValues

log = logging.getLogger(__name__)

def fetch_active_subscriptions(client: NotionClient, database_id: str) -> list[Subscription]:
    """从订阅数据库读取所有 Status 為 Active/Empty 的 Page """
    body: dict = {
        "filter": {
            "or":[
                {
                    "property": SubscriptionFields.STATUS,
                    "select": {"is_empty": True},
                },
                {
                    "property": SubscriptionFields.STATUS,
                    "select": {"equals": StatusValues.ACTIVE},
                }
            ]
        },
        "page_size": 100,
    }
    subscriptions = []
    has_more = True
    next_cursor = None

    while has_more:
        if next_cursor:
            body["start_cursor"] = next_cursor
        result = client._request("POST", f"/databases/{database_id}/query", json=body)

        for page in result.get("results", []):
            sub = _parse_subscription(page)
            if sub:
                subscriptions.append(sub)

        has_more = result.get("has_more", False)
        next_cursor = result.get("next_cursor")

    log.info(f"读取到 {len(subscriptions)} 个活跃订阅")
    return subscriptions


def update_subscription_status(
    client: NotionClient,
    subscription: Subscription,
    status: str,
    error_msg: str | None = None,
) -> None:
    """
    更新订阅的 Status。
    LastUpdate 則由 Notion 自動更新（始终更新为当前运行时间）
    如果订阅的 Name 为空且 feed_title 不为空，自动回填站点名。
    如果 error_msg 不为空，将错误信息追加为 Notion Callout block 到订阅页面。
    """
    body: dict = {
        "properties": {
            SubscriptionFields.STATUS:      {"select": {"name": status}},
        }
    }


    client._request(
        "PATCH",
        f"/pages/{subscription.page_id}",
        json=body,
    )
    
    # 若有错误消息，追加错误块到订阅页面
    if error_msg:
        client.append_error_block(subscription.page_id, error_msg)


# ─────────────────────────────────────────────
# 内部辅助函数
# ─────────────────────────────────────────────

def _parse_subscription(page: dict) -> Subscription | None:
    """将 Notion 页面对象解析为 Subscription"""
    try:
        props:dict = page.get("properties", {})

        # URL（url 类型）
        url = props.get(SubscriptionFields.URL, {}).get("url", "")
        if not url:
            log.warning(f"订阅页面 {page['url']} 缺少 URL，跳过")
            return None
        
        # Page Icon
        icon = page.get("icon", {})

        # Page Image
        image = page.get("cover", {})

        # Name（title 类型）
        name_items = props.get(SubscriptionFields.NAME, {}).get("title", [])
        name = "".join(item.get("plain_text", "") for item in name_items).strip()

        # FullTextEnabled（checkbox 类型）
        full_text_enabled = props.get(SubscriptionFields.FULL_TEXT_ENABLED, {}).get("checkbox", False)

        # Status（select 类型）
        status_obj = props.get(SubscriptionFields.STATUS, {}).get("select", {})
        status = ""
        if status_obj: status = status_obj.get("name")

        # LastUpdate（last_edited_time 类型，返回 ISO 8601 格式的字符串）
        last_update = props.get(SubscriptionFields.LAST_UPDATE, {}).get("last_edited_time", "")

        return Subscription(
            page_id=page["id"],
            name=name,
            url=url,
            icon=icon,
            channel_image=image, 
            full_text_enabled=full_text_enabled,
            status=status,
            last_update=last_update,
        )
    except Exception as e:
        log.error(f"解析订阅页面失败 {page.get('id', '?')}: {e}")
        return None
