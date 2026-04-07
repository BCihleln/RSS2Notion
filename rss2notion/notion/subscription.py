"""
订阅数据库：读取活跃订阅、更新订阅状态
"""

import logging

from ..models import Subscription
from .client import NotionClient
from .schema import SubscriptionFields, StatusValues

log = logging.getLogger(__name__)

def get_avaliable_subscriptions(
        client: NotionClient, 
        subscirption_database_id: str, 
        entries_database_id: str,
        ) -> list[Subscription]:
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
    log.debug("開始獲取訂閲源")
    subscriptions = []
    pages = client._paginate("POST", f"/databases/{subscirption_database_id}/query", json=body)
    for page in pages:
        sub = _parse_subscription(page)
        if isinstance(sub, Subscription):
            page_blocks = client.get_block_children(page["id"])
            sub.accumulated_errors = [b for b in page_blocks if (b.get("type") == "callout")] # 篩選出 callout 塊作爲已累積的錯誤快
            sub.existing_articles = client.query_pages_by_source(entries_database_id, page["id"])
            subscriptions.append(sub)
            log.debug(f"   訂閲源獲取 ✓ : {sub.name} 已有 {len(sub.existing_articles)} 條文章记录")
        else: 
            log.error(f"   訂閲源獲取 ✗ : {page["url"]}")

    log.info(f"读取到 {len(subscriptions)} 个活跃订阅")
    return subscriptions


def update_subscription_status(
    client: NotionClient,
    subscription: Subscription,
    status: str | None,
    error_msg: str | None = None,
) -> None:
    """
    更新订阅的 Status。
    Args:
        client:       NotionClient 实例
        subscription: 目标订阅对象
        status:       新状态值（StatusValues 常量）；传入 None 或空字符串则清空 select
        error_msg:    若不为 None，将错误信息以带时间戳的 Callout 块追加到订阅页面
    """
    # status 为 None / "" 时清空 select（用于"暂时出错但未达阈值"场景）
    if status:
        status_value: dict | None = {"name": status}
    else:
        status_value = None

    body: dict = {
        "properties": {
            SubscriptionFields.STATUS: {"select": status_value},
        }
    }

    client._request("PATCH", f"/pages/{subscription.page_id}", json=body)

    # 若有错误消息，追加带时间戳的错误块到订阅页面
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
        # log.info(f" name : {name}")

        # Status（select 类型）
        status_obj = props.get(SubscriptionFields.STATUS, {}).get("select", {})
        status = ""
        if status_obj: status = status_obj.get("name")

        # LastUpdate（last_edited_time 类型，返回 ISO 8601 格式的字符串）
        last_update = props.get(SubscriptionFields.LAST_UPDATE, {}).get("last_edited_time", "")

        # Filterout Keywords (multi_select 類型)
        filterout_keywords_tags:list[dict] = props.get(SubscriptionFields.FILTERLIST, {}).get("multi_select", [])
        filterout_keywords = [tag.get('name') for tag in filterout_keywords_tags]

        return Subscription(
            page_id=page["id"],
            name=name,
            url=url,
            icon=icon,
            channel_image=image, 
            status=status,
            last_update=last_update,
            existing_articles=[],
            accumulated_errors=[],
            filterout_keywords=filterout_keywords
        )
    except Exception as e:
        log.error(f"解析订阅页面失败 {page.get('id', '?')}: {e}")
        return None
