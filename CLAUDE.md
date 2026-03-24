# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介

RSS2Notion 是一个将 RSS 订阅内容同步到 Notion 数据库的 Python 工具，通过 GitHub Actions 每小时自动运行。RSS 订阅源从 Notion 订阅数据库读取，支持全文/仅元数据两种保存模式，并自动清理过期未读文章。

## 开发环境

```bash
# 安装依赖（需 Python >= 3.14 和 uv）
uv sync

# 运行（需设置环境变量）
export NOTION_API_KEY=...
export NOTION_ARTICLES_DATABASE_ID=...
export NOTION_FEEDS_DATABASE_ID=...
uv run python -m rss2notion

# 验证模块导入
uv run python -c "from rss2notion.sync import run; print('OK')"
```

## 项目结构

```
rss2notion/
├── __main__.py           # 入口，配置日志并调用 Config.from_env() + run()
├── config.py             # 环境变量 → Config dataclass
├── models.py             # RSSEntry, FeedResult, Subscription
├── rss.py                # RSS 解析（parse_rss, parse_date）
├── converter.py          # HTML/Markdown → Notion Blocks 转换管线
├── sync.py               # 主同步流程编排
└── notion/
    ├── client.py          # NotionClient 基础 API 客户端
    ├── subscription.py    # 订阅数据库读取/更新
    └── cleanup.py         # 自动清理过期文章
```

## 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `NOTION_API_KEY` | 是 | — | Notion Integration Token |
| `NOTION_ARTICLES_DATABASE_ID` | 是 | — | 文章数据库 ID |
| `NOTION_FEEDS_DATABASE_ID` | 是 | — | 订阅数据库 ID |
| `TIMEZONE` | 否 | `Asia/Shanghai` | IANA 时区名 |
| `CLEANUP_DAYS` | 否 | `30` | 清理天数，-1 不清理 |

## 架构说明

**主同步流程（`sync.py:run`）：**
1. 从订阅数据库读取活跃订阅（`notion/subscription.py:fetch_active_subscriptions`）
2. 对每个订阅：解析 RSS → 用 LastUpdate 时间过滤新文章 → 批量查询已存在 URL 去重 → 写入文章数据库 → 更新订阅状态
3. 执行自动清理（`notion/cleanup.py:cleanup_expired_articles`）

**HTML → Notion Blocks 转换（`converter.py`）：**
- `split_html_to_blocks` 用 BeautifulSoup 将 HTML 拆为 `("text", md)` 和 `("image", url)` 交替块
- `markdown_to_notion_blocks` 用 mistletoe 解析 Markdown AST，递归转为 Notion block 格式
- `entry_to_notion_blocks` 组合以上两步

**去重策略：**
- 优先用订阅的 `LastUpdate` 过滤时间范围，减少待检查条目数
- 对过滤后的条目，一次性查询该订阅源在文章数据库中的所有 URL（`notion/client.py:query_pages_by_source`），构建 set 做 O(1) 去重

## Notion 数据库属性

### 订阅数据库（对应 `NOTION_FEEDS_DATABASE_ID`）
`Name`(title) · `URL`(url) · `Disabled`(checkbox) · `FullTextEnabled`(checkbox) · `Status`(select: Active/Error) · `LastUpdate`(date) · `Tags`(multi_select)

### 文章数据库（对应 `NOTION_ARTICLES_DATABASE_ID`）
`Name`(title) · `URL`(url) · `Published`(date) · `Author`(rich_text) · `Tags`(multi_select) · `State`(select: Unread/Reading/Starred) · `Source`(relation → 订阅数据库)

**注意**：Notion Integration 需要同时连接两个数据库才能正常运行。
