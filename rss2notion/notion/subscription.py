"""
订阅数据库：读取活跃订阅、更新订阅状态
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from .client import NotionClient
from .article import query_existing_article_urls
from ..schema import SubscriptionFields, StatusValues
from ..utils.config import Config

log = logging.getLogger(__name__)
config = Config.from_env()

_ERROR_BLOCK_EMOJI = "⚠️"


@dataclass
class Subscription:
    """对应 Notion 订阅数据库中的一行，並封裝其業務邏輯"""
    page_id: str
    name: str
    url: str
    icon: dict | None
    channel_image: str | None
    filterout_keywords: list
    status: str                     # Active / Error /Disabled
    last_update: datetime           # ISO 日期
    existing_articles: list[str]    # 已存入 Notion 的文章清單 (混存 URL 與標題) ，便於去重
    accumulated_errors: list[dict]
    fetch_amount: int | None = None
    fetch_days: int | None = None
    is_aggregated: bool = False
    aggregated_urls_block_id: str | None = None
    aggregated_urls_paragraph_id: str | None = None
    blocks_loaded: bool = False
    articles_loaded: bool = False

    @classmethod
    def from_notion_page(cls, page: dict) -> 'Subscription | None':
        """将 Notion 页面对象解析为 Subscription"""
        try:
            props:dict = page.get("properties", {})

            url = props.get(SubscriptionFields.URL, {}).get("url", "")
            if not url:
                log.warning(f"订阅页面 {page.get('url', '')} 缺少 URL，跳过")
                return None

            # DEBUG
            # log.info(f" page.keys( : {page.keys(}"))
            # log.info(f"所有属性: {props.keys()}")  # 看看有哪些属性，便於處理 Database 類型不同的情況
            
            icon = page.get("icon", {})
            # log.info(f" icon : {icon}")
            image = page.get("cover", {})
            # log.info(f" image : {image}")

            name_items = props.get(SubscriptionFields.NAME, {}).get("title", [])
            name = "".join(item.get("plain_text", "") for item in name_items).strip()
            # log.info(f" name : {name}")

            status_obj = props.get(SubscriptionFields.STATUS, {}).get("select", {})
            status = ""
            if status_obj: status = status_obj.get("name")
            # log.info(f" status : {status}")

            last_update_str = props.get(SubscriptionFields.LAST_UPDATE, {}).get("last_edited_time", "")
            last_update = last_update_str 
            # log.info(f"subscription last update : {last_update}")

            filterout_keywords_tags:list[dict] = props.get(SubscriptionFields.FILTERLIST, {}).get("multi_select", [])
            filterout_keywords = [tag.get('name') for tag in filterout_keywords_tags]

            cleanup_days_raw = props.get(SubscriptionFields.CLEANUP_DAYS, {}).get("number", None)
            cleanup_days = int(cleanup_days_raw) if cleanup_days_raw is not None else None

            fetch_amount_raw = props.get(SubscriptionFields.FETCH_AMOUNT, {}).get("number", None)
            fetch_amount = int(fetch_amount_raw) if fetch_amount_raw is not None else None

            is_aggregated = props.get(SubscriptionFields.AGGREGATED, {}).get("checkbox", False)

            return cls(
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

    def lazy_load(
        self,
        client: NotionClient, 
        articles_datasource_id: str | None = None,
        fetch_blocks: bool = False,
        fetch_articles: bool = False
    ) -> None:
        """延遲加載訂閱源的 Callout 區塊與歷史文章記錄"""
        if fetch_blocks and not self.blocks_loaded:
            page_blocks = client.get_block_children(self.page_id)
            self.accumulated_errors = []
            for b in page_blocks:
                if b.get("type") != "callout":
                    continue
                    
                icon_emoji = b.get("callout", {}).get("icon", {}).get("emoji", "")
                if icon_emoji in ("🔗", "📦"):
                    self._extract_aggregated_urls(client, b)
                else:
                    self.accumulated_errors.append(b)
            self.blocks_loaded = True

        if fetch_articles and articles_datasource_id and not self.articles_loaded:
            self.existing_articles.extend(query_existing_article_urls(client, articles_datasource_id, self.page_id))
            self.articles_loaded = True

    def __update_status(
        self,
        client: NotionClient,
        status: str | None,
        error_msg: str | None = None,
    ) -> None:
        """更新订阅的 Status"""
        if config.subscription_update_status:
            status_value = {"name": status} if status else None 
            body: dict = {
                "properties": {
                    SubscriptionFields.STATUS: {"select": status_value},
                }
            }
            client._request("PATCH", f"/pages/{self.page_id}", json=body)

        if error_msg:
            self._append_error_block(
                client,
                error_msg, 
                mention_user=(status == StatusValues.ERROR)
            )

    def mark_error(
        self,
        client: NotionClient,
        error_msg: str,
    ) -> None:
        """处理 RSS 拉取/写入全部失败的情况"""
        self.lazy_load(client, fetch_blocks=True)
        existing_error_count = len(self.accumulated_errors)
        total_after = existing_error_count + 1
        log.debug(f"   错误块计数: {existing_error_count} → {total_after}（阈值 {config.mark_err_threshold}）")

        mark_as_err = ""
        new_status: str | None
        if total_after > config.mark_err_threshold:
            mark_as_err = "標記爲 Error"
            new_status = StatusValues.ERROR
        else:
            log.debug(f"   错误未达阈值，状态清空（将在下次轮询重试）")
            new_status = None
        
        log.warning(f"订阅 [{self.name}] 累积错误达 {total_after} 次 {mark_as_err}")

        self.__update_status(
            client,
            status=new_status,
            error_msg=error_msg,
        )

    def mark_active(self, client: NotionClient) -> None:
        """拉取成功后：清空历史错误块，将状态置为 Active。"""
        deleted = 0
        if self.status != StatusValues.ACTIVE:
            self.lazy_load(client, fetch_blocks=True)
            blocks = self.accumulated_errors
            for block in blocks:
                try:
                    client.delete_block(block["id"])
                    deleted += 1
                    time.sleep(0.2)  # 避免触发速率限制
                except Exception as e:
                    log.warning(f"   删除错误块 {block['id']} 失败（跳过）: {e}")

        if deleted:
            log.info(f"   ✓ 已清除 {deleted} 个历史错误块")

        self.__update_status(
            client,
            status=StatusValues.ACTIVE,
        )

    def append_aggregated_urls_block(self, client: NotionClient, new_text: str) -> str:
        """附加一個 Aggregated 模式用來儲存 URLs 的 Callout Block (Emoji 📦)。"""
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
        res = client._request("PATCH", f"/blocks/{self.page_id}/children", json={"children": [block]})
        results = res.get("results", [])
        if results:
            return results[0].get("id", "")
        return ""

    def _extract_aggregated_urls(self, client: NotionClient, block: dict) -> None:
        """從 Aggregated Subscirption 頁内 callout block 解析出已拉取的 Post Cache"""
        self.aggregated_urls_block_id = block["id"]
        rich_text = block["callout"].get("rich_text", [])
        text_content = "".join(rt.get("plain_text", "") for rt in rich_text)
        
        if not text_content and block.get("has_children"):
            callout_children = client.get_block_children(block["id"])
            if not callout_children or callout_children[0].get("type") != "toggle":
                return
                
            toggle_children = client.get_block_children(callout_children[0]["id"])
            if not toggle_children or toggle_children[0].get("type") != "paragraph":
                return
                
            self.aggregated_urls_paragraph_id = toggle_children[0]["id"]
            nested_rich_text = toggle_children[0]["paragraph"].get("rich_text", [])
            text_content = "".join(rt.get("plain_text", "") for rt in nested_rich_text)

        if text_content:
            self.existing_articles.extend(text_content.split("\n"))

    def _append_error_block(self, client: NotionClient, error_msg: str, mention_user: bool = False) -> None:
        try:
            user_id = client._get_notion_user_id() if mention_user else None
            
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            full_msg = f"[{timestamp}] {error_msg}"
            max_length = 2000
            if len(full_msg) > max_length:
                full_msg = full_msg[:max_length - 5] + "...[截断]"
            if user_id:
                full_msg += " "
            rich_text = [{"type": "text", "text": {"content": full_msg, "link": None}}]
            if user_id:
                rich_text.append({"type": "mention", "mention": {"type": "user", "user": {"id": user_id}}})

            block = {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": rich_text,
                    "icon": {"type": "emoji", "emoji": _ERROR_BLOCK_EMOJI},
                    "color": "red_background",
                },
            }
            client.append_blocks(self.page_id, [block])
            log.info(f"   ✓ 错误块已记录到页面 {self.page_id}")
        except Exception as e:
            log.warning(f"   ✗ 错误块写入失败（不影响主流程）: {e}")


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
        sub = Subscription.from_notion_page(page)
        if sub:
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
    log.info(f"讀取到 {len(subscriptions)} 個訂閲：{' | '.join(filter(None,[active_str, error_str, empty_str]))}")
    return subscriptions
