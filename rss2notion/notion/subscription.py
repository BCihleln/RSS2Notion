"""
订阅数据库：读取活跃订阅、更新订阅状态
"""

import logging
import time
from datetime import datetime, timezone

from ..models import Subscription
from .client import NotionClient
from .article import query_existing_article_urls
from ..schema import SubscriptionFields, StatusValues
from ..utils.config import Config

log = logging.getLogger(__name__)
config = Config.from_env()

_ERROR_BLOCK_EMOJI = "⚠️"

def get_avaliable_subscriptions(
        client: NotionClient, 
        subscirption_datasource_id: str, 
        ) -> list[Subscription]:
    """从订阅数据库读取所有 Status 為 Active/Empty 的 Page """
    # 不論線上或開發環境，都會獲取 empty 狀態的 Subscription
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
    subscriptions:list[Subscription] = []
    pages = client._paginate("POST", f"/data_sources/{subscirption_datasource_id}/query", json=body)
    for page in pages:
        sub = _parse_subscription(page)
        if isinstance(sub, Subscription):
            subscriptions.append(sub)
            cleanup_str = f"，Cleanup Days 覆寫: {sub.fetch_days}" if sub.fetch_days is not None else ""
            log.debug(f"   訂閲源獲取 ✓ : {sub.name} (已延遲加載資料){cleanup_str}")
        else: 
            log.error(f"   訂閲源獲取 ✗ : {page['url']}")

    active = error =  empty = 0
    for sub in subscriptions:
        if sub.status == StatusValues.ACTIVE: active += 1
        elif sub.status == StatusValues.ERROR: error += 1
        else: empty += 1
    active_str = f"活躍 {active}" if active else None
    error_str = f"錯誤 {error}" if error else None
    empty_str = f"觀察 {empty}" if empty else None
    log.info(f"讀取到 {len(subscriptions)} 個訂閲：{" | ".join(filter(None,[active_str, error_str, empty_str]))}")
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
    # 如果啓用狀態更新，才向 Notion 送出 PATCH 修改 properties
    if config.subscription_update_status:
        # status 为 None / "" 时清空 select（用于"暂时出错但未达阈值"场景）
        status_value = {"name": status} if status else None 

        body: dict = {
            "properties": {
                SubscriptionFields.STATUS: {"select": status_value},
            }
        }

        client._request("PATCH", f"/pages/{subscription.page_id}", json=body)

    # 若有错误消息，追加带时间戳的错误块到订阅页面
    if error_msg:
        append_error_block(
            client,
            subscription.page_id, 
            error_msg, 
            mention_user=(status == StatusValues.ERROR)
            )

def lazy_load_subscription_data(
    client: NotionClient, 
    subscription: Subscription, 
    entries_datasource_id: str | None = None,
    fetch_blocks: bool = False,
    fetch_articles: bool = False
) -> None:
    """延遲加載訂閱源的 Callout 區塊與歷史文章記錄"""
    if fetch_blocks and not subscription.blocks_loaded:
        page_blocks = client.get_block_children(subscription.page_id)
        subscription.accumulated_errors = []
        for b in page_blocks:
            if b.get("type") != "callout":
                continue
                
            icon_emoji = b.get("callout", {}).get("icon", {}).get("emoji", "")
            if icon_emoji in ("🔗", "📦"):
                _extract_aggregated_urls(client, subscription, b)
            else:
                subscription.accumulated_errors.append(b)
        subscription.blocks_loaded = True

    if fetch_articles and entries_datasource_id and not subscription.articles_loaded:
        subscription.existing_articles.extend(query_existing_article_urls(client, entries_datasource_id, subscription.page_id))
        subscription.articles_loaded = True

# ─────────────────────────────────────────────
# 内部辅助函数
# ─────────────────────────────────────────────

def _extract_aggregated_urls(client: NotionClient, subscription: Subscription, block: dict) -> None:
    """從 Aggregated Subscirption 頁内 callout block 解析出已拉取的 Post Cache"""
    subscription.aggregated_urls_block_id = block["id"]
    rich_text = block["callout"].get("rich_text", [])
    text_content = "".join(rt.get("plain_text", "") for rt in rich_text)
    
    if not text_content and block.get("has_children"):
        callout_children = client.get_block_children(block["id"])
        if not callout_children or callout_children[0].get("type") != "toggle":
            return
            
        toggle_children = client.get_block_children(callout_children[0]["id"])
        if not toggle_children or toggle_children[0].get("type") != "paragraph":
            return
            
        subscription.aggregated_urls_paragraph_id = toggle_children[0]["id"]
        nested_rich_text = toggle_children[0]["paragraph"].get("rich_text", [])
        text_content = "".join(rt.get("plain_text", "") for rt in nested_rich_text)

    if text_content:
        subscription.existing_articles.extend(text_content.split("\n"))

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

def append_aggregated_urls_block(client: NotionClient, page_id: str, new_text: str) -> str:
    """
    附加一個 Aggregated 模式用來儲存 URLs 的 Callout Block (Emoji 📦)。
    包含 Toggle -> Paragraph 的嵌套結構。
    回傳新建 block 的 ID。
    """
    rich_text = []
    for i in range(0, len(new_text), 2000):
        rich_text.append({
            "type": "text",
            "text": {"content": new_text[i:i+2000]}
        })

    block = {
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
                                    "rich_text": rich_text
                                }
                            }
                        ]
                    }
                }
            ]
        }
    }
    res = client._request("PATCH", f"/blocks/{page_id}/children", json={"children": [block]})
    results = res.get("results", [])
    if results:
        return results[0].get("id", "")
    return ""

def _build_error_block(error_msg: str, user_id: str | None = None) -> dict:
    """生成带时间戳的 Notion Callout block（⚠️ 红色背景）

    Args:
        error_msg: 错误消息字符串
        user_id: 需 mention 的使用者 ID (可选)

    Returns:
        符合 Notion Block 规范的字典
    """
    # 截断超长消息（Notion paragraph content 限制 2000 字符）
    # 拼接时间戳前缀
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    full_msg = f"[{timestamp}] {error_msg}"

    max_length = 2000
    if len(full_msg) > max_length:
        full_msg = full_msg[:max_length - 5] + "...[截断]"

    if user_id:
        full_msg += " "

    rich_text = [
        {
            "type": "text",
            "text": {
                "content": full_msg,
                "link": None,
            },
        }
    ]

    if user_id:
        rich_text.append({
            "type": "mention",
            "mention": {
                "type": "user",
                "user": {"id": user_id}
            }
        })

    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": rich_text,
            "icon": {
                "type": "emoji",
                "emoji": _ERROR_BLOCK_EMOJI,
            },
            "color": "red_background",
        },
    }

def append_error_block(client: NotionClient, page_id: str, error_msg: str, mention_user: bool = False) -> None:
    """追加带时间戳的错误 Callout 块到页面。

    Args:
        client: NotionClient 实例
        page_id: 目标页面 ID
        error_msg: 错误信息字符串
        mention_user: 是否提及使用者
    """
    try:
        user_id = client._get_notion_user_id() if mention_user else None
        block = _build_error_block(error_msg, user_id=user_id)
        client.append_blocks(page_id, [block])
        log.info(f"   ✓ 错误块已记录到页面 {page_id}")
    except Exception as e:
        log.warning(f"   ✗ 错误块写入失败（不影响主流程）: {e}")

def handle_subscription_failure(
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
    lazy_load_subscription_data(client, subscription, fetch_blocks=True)
    existing_error_count = len(subscription.accumulated_errors)

    # 含本次即将追加的一条
    total_after = existing_error_count + 1
    log.debug(f"   错误块计数: {existing_error_count} → {total_after}（阈值 {config.mark_err_threshold}）")

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

def handle_subscription_success(client: NotionClient, subscription: Subscription) -> None:
    """拉取成功后：清空历史错误块，将状态置为 Active。"""
    deleted = 0
    if subscription.status != StatusValues.ACTIVE:
        lazy_load_subscription_data(client, subscription, fetch_blocks=True)
        blocks = subscription.accumulated_errors
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
        status=StatusValues.ACTIVE,
    )
