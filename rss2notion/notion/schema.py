"""
Notion 数据库字段名和值的常量定义
"""


class SubscriptionFields:
    """订阅数据库字段名"""
    NAME =              "Feed Name"         # Read/Write 
    URL =               "URL"               # Read only
    DISABLED =          "Disabled"          # Read only
    FULL_TEXT_ENABLED = "FullTextEnabled"   # Read only
    STATUS =            "Status"            # Read/Write 
    LAST_UPDATE =       "Updates"           # Read only, Notion database will update automatically


class EntryFields:
    """文章数据库字段名"""
    NAME =              "Name"      # Read/Write 
    URL =               "URL"       # Read/Write 
    PUBLISHED =         "Published" # Read/Write 
    STATE =             "State"     # Read/Write 
    SOURCE =            "Source"    # Read/Write 


class StatusValues:
    """订阅状态值"""
    ACTIVE =            "Active"    # Read only
    ERROR =             "Error"     # Read only


class StateValues:
    """文章状态值"""
    UNREAD =            "Unread"    # Read only
    READING =           "Reading"   # Read only
    STARRED =           "Starred"   # Read only
