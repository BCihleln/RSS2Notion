"""
Notion 数据库字段名和值的常量定义
"""


class SubscriptionFields:
    """订阅数据库字段名"""
    NAME = "Name"
    URL = "URL"
    DISABLED = "Disabled"
    FULL_TEXT_ENABLED = "FullTextEnabled"
    STATUS = "Status"
    LAST_UPDATE = "LastUpdate"
    TAGS = "Tags"


class EntryFields:
    """文章数据库字段名"""
    NAME = "Name"
    URL = "URL"
    PUBLISHED = "Published"
    AUTHOR = "Author" # Not in use
    STATE = "State"
    TAGS = "Tags"
    SOURCE = "Source"


class StatusValues:
    """订阅状态值"""
    ACTIVE = "Active"
    ERROR = "Error"


class StateValues:
    """文章状态值"""
    UNREAD = "Unread"
    READING = "Reading"
    STARRED = "Starred"
