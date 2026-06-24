"""
订阅数据库：读取活跃订阅、更新订阅状态
"""

import logging

from ..models import Subscription
from .client import NotionClient
from ..schema import SubscriptionFields, StatusValues
from ..utils.config import Config

log = logging.getLogger(__name__)

def get_avaliable_subscriptions(
        client: NotionClient, 
        subscirption_datasource_id: str, 
        entries_datasource_id: str,
        ) -> list[Subscription]:
    """从订阅数据库读取所有 Status 為 Active/Empty 的 Page """
    config = Config.from_env()
    
    or_conditions = [
        {
            "property": SubscriptionFields.STATUS,
            "select": {"is_empty": True},
        }
    ]
    
    if config.subscription_fetch_status:
        or_conditions.append({
            "property": SubscriptionFields.STATUS,
            "select": {"equals": config.subscription_fetch_status},
        })

    body: dict = {
        "filter": {
            "or": or_conditions
        },
        "page_size": 100,
    }
    log.debug("開始獲取訂閲源")
    subscriptions = []
    pages = client._paginate("POST", f"/data_sources/{subscirption_datasource_id}/query", json=body)
    for page in pages:
        sub = _parse_subscription(page)
        if isinstance(sub, Subscription):
            subscriptions.append(sub)
            cleanup_str = f"，Cleanup Days 覆寫: {sub.fetch_days}" if sub.fetch_days is not None else ""
            log.debug(f"   訂閲源獲取 ✓ : {sub.name} (已延遲加載資料){cleanup_str}")
        else: 
            log.error(f"   訂閲源獲取 ✗ : {page['url']}")

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
    config = Config.from_env()
    
    # 如果啓用狀態更新，才向 Notion 送出 PATCH 修改 properties
    if config.subscription_update_status:
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
        client.append_error_block(
            subscription.page_id, 
            error_msg, 
            mention_user=(status == StatusValues.ERROR)
            )


# ─────────────────────────────────────────────
# 内部辅助函数
# ─────────────────────────────────────────────

def lazy_load_subscription_data(
    client: NotionClient, 
    subscription: Subscription, 
    entries_datasource_id: str | None = None,
    fetch_blocks: bool = False,
    fetch_articles: bool = False
) -> None:
    """延遲加載訂閱源的 Callout 區塊與歷史文章記錄"""
    if fetch_blocks and not getattr(subscription, "_blocks_loaded", False):
        page_blocks = client.get_block_children(subscription.page_id)
        subscription.accumulated_errors = []
        for b in page_blocks:
            if b.get("type") == "callout":
                icon_emoji = b.get("callout", {}).get("icon", {}).get("emoji", "")
                if icon_emoji in ("🔗", "📦"):
                    subscription.aggregated_urls_block_id = b["id"]
                    rich_text = b["callout"].get("rich_text", [])
                    text_content = "".join(rt.get("plain_text", "") for rt in rich_text)
                    
                    if not text_content and b.get("has_children"):
                        callout_children = client.get_block_children(b["id"])
                        if callout_children and callout_children[0].get("type") == "toggle":
                            toggle_children = client.get_block_children(callout_children[0]["id"])
                            if toggle_children and toggle_children[0].get("type") == "paragraph":
                                subscription.aggregated_urls_paragraph_id = toggle_children[0]["id"]
                                nested_rich_text = toggle_children[0]["paragraph"].get("rich_text", [])
                                text_content = "".join(rt.get("plain_text", "") for rt in nested_rich_text)

                    if text_content:
                        subscription.existing_articles.extend(text_content.split("\n"))
                else:
                    subscription.accumulated_errors.append(b)
        subscription._blocks_loaded = True

    if fetch_articles and entries_datasource_id and not getattr(subscription, "_articles_loaded", False):
        subscription.existing_articles.extend(client.query_pages_by_source(entries_datasource_id, subscription.page_id))
        subscription._articles_loaded = True

def _parse_subscription(page: dict) -> Subscription | None:
    """将 Notion 页面对象解析为 Subscription"""
    try:
        props:dict = page.get("properties", {})

        # DEBUG
        # log.info(f" page.keys( : {page.keys(}"))
        # log.info(f"所有属性: {props.keys()}")  # 看看有哪些属性，便於處理 Database 類型不同的情況

        # URL（url 类型）
        url = props.get(SubscriptionFields.URL, {}).get("url", "")
        if not url:
            log.warning(f"订阅页面 {page['url']} 缺少 URL，跳过")
            return None
        # log.info(f"url: {url}")
        
        # Page Icon
        icon = page.get("icon", {})
        # log.info(f" icon : {icon}")

        # Page Image
        image = page.get("cover", {})
        # log.info(f" image : {image}")

        # Name（title 类型）
        name_items = props.get(SubscriptionFields.NAME, {}).get("title", [])
        name = "".join(item.get("plain_text", "") for item in name_items).strip()
        # log.info(f" name : {name}")

        # Status（select 类型）
        status_obj = props.get(SubscriptionFields.STATUS, {}).get("select", {})
        status = ""
        if status_obj: status = status_obj.get("name")
        # log.info(f" status : {status}")

        # LastUpdate（last_edited_time 类型，返回 ISO 8601 格式的字符串）
        last_update = props.get(SubscriptionFields.LAST_UPDATE, {}).get("last_edited_time", "")

        # Filterout Keywords (multi_select 類型)
        filterout_keywords_tags:list[dict] = props.get(SubscriptionFields.FILTERLIST, {}).get("multi_select", [])
        filterout_keywords = [tag.get('name') for tag in filterout_keywords_tags]

        #DEBUG
        # log.info(f"subscription last update : {last_update}")
        #DEBUG

        # Cleanup Days（number 類型）；空值保留 None，表示沿用全局值
        cleanup_days_raw = props.get(SubscriptionFields.CLEANUP_DAYS, {}).get("number", None)
        cleanup_days: int | None = int(cleanup_days_raw) if cleanup_days_raw is not None else None

        # Fetch Amount（number 類型）；空值保留 None，表示沿用全局值
        fetch_amount: int | None = props.get(SubscriptionFields.FETCH_AMOUNT, {}).get("number", None)

        is_aggregated: bool = props.get(SubscriptionFields.AGGREGATED, {}).get("checkbox", False)

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
            filterout_keywords=filterout_keywords,
            fetch_days=cleanup_days,
            fetch_amount=fetch_amount,
            is_aggregated=is_aggregated,
        )
    except Exception as e:
        log.error(f"解析订阅页面失败 {page.get('id', '?')}: {e}")
        return None
