"""
配置管理：从环境变量读取所有配置项
"""

import os
from ..schema import StatusValues
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass
class Config:
    notion_api_key: str
    entries_datasource_id: str           # 文章数据库 ID
    feeds_datasource_id: str             # 订阅数据库 ID
    timezone: ZoneInfo                 # 时区对象
    cleanup_days: int                  # 清理天数，-1 表示不清理
    notion_user_id: str | None = None  # Notion 使用者 ID
    max_import_count: int = 1          # 單訂閱源文章導入時，未限定時間範圍的數量上限
    notion_block_limit: int = 100      # 首批写入 block 上限
    retry_times: int = 3
    retry_delay: float = 2.0
    mark_err_threshold: int = 10       # 累积错误块数量达到该阈值时，才将订阅状态升级为 Error
    subscription_fetch_status: str = StatusValues.ACTIVE
    subscription_update_status: bool = True

    @classmethod
    def from_env(cls) -> "Config":
        """从环境变量构建配置，缺失必填项时抛出明确错误"""
        missing = []

        api_key = os.environ.get("NOTION_API_KEY", "")
        if not api_key:
            missing.append("NOTION_API_KEY")

        datasource_id = os.environ.get("NOTION_ARTICLES_DATABASE_ID", "")
        if not datasource_id:
            missing.append("NOTION_ARTICLES_DATABASE_ID")

        sub_datasource_id = os.environ.get("NOTION_FEEDS_DATABASE_ID", "")
        if not sub_datasource_id:
            missing.append("NOTION_FEEDS_DATABASE_ID")

        if missing:
            raise ValueError(f"缺少必填环境变量: {', '.join(missing)}")

        tz_name = os.environ.get("TIMEZONE", "Asia/Shanghai")
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            raise ValueError(f"无效的时区名称: {tz_name}，请使用 IANA 时区格式，如 Asia/Shanghai")

        cleanup_days_str = os.environ.get("CLEANUP_DAYS", "30")
        try:
            cleanup_days = int(cleanup_days_str)
        except ValueError:
            raise ValueError(f"CLEANUP_DAYS 必须为整数，当前值: {cleanup_days_str}")

        subscription_fetch_status = os.environ.get("SUBSCRIPTION_FETCH_STATUS", StatusValues.ACTIVE)
        
        # 預設為 True，允許更新狀態
        update_status_str = os.environ.get("SUBSCRIPTION_UPDATE_STATUS", "true").lower()
        subscription_update_status = update_status_str == "true"
        notion_user_id = os.environ.get("NOTION_USER_ID")

        return cls(
            notion_api_key=api_key,
            entries_datasource_id=datasource_id,
            feeds_datasource_id=sub_datasource_id,
            timezone=tz,
            cleanup_days=cleanup_days,
            subscription_fetch_status=subscription_fetch_status,
            subscription_update_status=subscription_update_status,
            notion_user_id=notion_user_id,
        )
