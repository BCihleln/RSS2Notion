"""
HTML → Notion Blocks 直接轉換
架構參照 starver444/html-to-notion-blocks：
  Stage 1: parse_html()   — DOM 遞歸，輸出中間格式
  Stage 2: to_notion_blocks() — 中間格式 → Notion API blocks
"""

from __future__ import annotations
from typing import Optional
from bs4 import BeautifulSoup, NavigableString, Tag # type: ignore


# ─────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────

NOTION_CODE_LANGS = {
    "abap", "arduino", "bash", "basic", "c", "clojure", "coffeescript", "c++", "c#",
    "css", "dart", "diff", "docker", "elixir", "elm", "erlang", "flow", "fortran", "f#",
    "gherkin", "glsl", "go", "graphql", "groovy", "haskell", "html", "java", "javascript",
    "json", "julia", "kotlin", "latex", "less", "lisp", "livescript", "lua", "makefile",
    "markdown", "markup", "matlab", "mermaid", "nix", "objective-c", "ocaml", "pascal",
    "perl", "php", "plain text", "powershell", "prolog", "protobuf", "python", "r",
    "reason", "ruby", "rust", "sass", "scala", "scheme", "scss", "shell", "sql", "swift",
    "toml", "typescript", "vb.net", "verilog", "vhdl", "visual basic", "webassembly",
    "xml", "yaml", "java/c/c++/c#",
}

# Callout 偵測 class 關鍵字（參照原 JS 實現）
_CALLOUT_CLASSES = {"callout", "admonition", "alert", "notice", "warning", "note", "tip", "hint", "info-block"}

# 已知防盜鏈域名，Notion 無法嵌入
_HOTLINK_BLOCKED = ("sinaimg.cn", "qpic.cn", "gtimg.cn", "mmbiz.qpic.cn", "zhimg.com")


# ─────────────────────────────────────────────
# 中間格式型別定義（純 dict，方便 debug）
# ─────────────────────────────────────────────
# 每個中間 block 結構：
# {
#   "type": str,          # paragraph / heading / image / code / list_item / ...
#   "text": str,          # 純文字（給段落/標題用）
#   "rich_text": list,    # 已組裝的 rich_text（inline 解析後）
#   "level": int,         # heading 級別 1-3
#   "list_type": str,     # bulleted / numbered
#   "indent": int,        # 嵌套深度
#   "url": str,           # image / embed
#   "language": str,      # code block
#   "children": list,     # 子 block（嵌套列表）
# }


# ─────────────────────────────────────────────
# Stage 1：DOM Walker → 中間格式
# ─────────────────────────────────────────────

def parse_html(html: str) -> list[dict]:
    """將 HTML 字符串解析為中間 block 列表"""
    soup = BeautifulSoup(html, "html.parser")
    blocks: list[dict] = []
    for node in soup.children:
        blocks.extend(_walk(node, indent=0))
    return _merge_adjacent_paragraphs(blocks)


def _walk(node, indent: int = 0) -> list[dict]:
    if isinstance(node, NavigableString):
        text = str(node).strip()
        if text:
            return [{"type": "paragraph", "rich_text": [_rt(text)], "indent": indent}]
        return []

    if not isinstance(node, Tag):
        return []

    tag = node.name
    # ── 標題 ──
    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = min(int(tag[1]), 3)
        return [{"type": "heading", "level": level,
                 "rich_text": _collect_inline(node), "indent": indent}]

    # ── 段落 ──
    if tag == "p":
        return _walk_p(node, indent)

    # ── 列表 ──
    if tag in ("ul", "ol"):
        list_type = "bulleted" if tag == "ul" else "numbered"
        return _walk_list(node, list_type, indent)

    # ── 圖片 ──
    if tag == "img":
        src = _extract_img_src(node)
        if src:
            return [{"type": "image", "url": src, "indent": indent}]
        return []

    # ── figure（通常包著 img）──
    if tag == "figure":
        blocks = []
        for child in node.children:
            blocks.extend(_walk(child, indent))
        return blocks

    # ── 引用 ──
    if tag == "blockquote":
        return [{"type": "quote", "rich_text": _collect_inline(node), "indent": indent}]

    # ── 程式碼 ──
    if tag == "pre":
        return [_walk_pre(node, indent)]

    if tag == "code" and (not node.parent or node.parent.name != "pre"):
        # 行內 code 包在段落裡，當作段落處理
        return [{"type": "paragraph", "rich_text": _collect_inline(node), "indent": indent}]

    # ── 分隔線 ──
    if tag == "hr":
        return [{"type": "divider", "indent": indent}]

    # ── 表格 ──
    if tag == "table":
        return [_walk_table(node, indent)]

    # ── Callout 偵測 ──
    classes = set(node.get("class", [])) # type: ignore
    if classes & _CALLOUT_CLASSES:
        return [{"type": "callout", "rich_text": _collect_inline(node), "indent": indent}]

    # ── 容器標籤，遞歸子節點 ──
    if tag in ("div", "section", "article", "main", "aside", "header", "footer",
               "nav", "body", "html", "span", "td", "th"):
        blocks = []
        for child in node.children:
            blocks.extend(_walk(child, indent))
        return blocks

    # ── br → 忽略（不產生空塊）──
    if tag == "br":
        return []

    # ── 其他 inline 標籤 (em, strong, a, s ...) 包成段落 ──
    rt = _collect_inline(node)
    if rt:
        return [{"type": "paragraph", "rich_text": rt, "indent": indent}]
    return []


def _walk_p(node: Tag, indent: int) -> list[dict]:
    """
    處理 <p>：若段落內含 <img>，拆開輸出圖片 block + 文字 block；
    否則直接輸出段落。
    """
    imgs = node.find_all("img")
    if not imgs:
        rt = _collect_inline(node)
        if rt:
            return [{"type": "paragraph", "rich_text": rt, "indent": indent}]
        return []

    blocks = []
    text_buf = []

    def flush_text():
        if text_buf:
            rt = _inline_nodes_to_rich_text(text_buf)
            if rt:
                blocks.append({"type": "paragraph", "rich_text": rt, "indent": indent})
            text_buf.clear()

    for child in node.children:
        if isinstance(child, Tag) and child.name == "img":
            flush_text()
            src = _extract_img_src(child)
            if src:
                blocks.append({"type": "image", "url": src, "indent": indent})
        else:
            text_buf.append(child)

    flush_text()
    return blocks


def _walk_list(node: Tag, list_type: str, indent: int) -> list[dict]:
    """遞歸處理 ul/ol，支援嵌套列表"""
    blocks = []
    for li in node.find_all("li", recursive=False):
        # 分離 li 直接文字 vs 嵌套列表
        inline_nodes = []
        nested_blocks = []

        for child in li.children:
            if isinstance(child, Tag) and child.name in ("ul", "ol"):
                nested_type = "bulleted" if child.name == "ul" else "numbered"
                nested_blocks.extend(_walk_list(child, nested_type, indent + 1))
            else:
                inline_nodes.append(child)

        rt = _inline_nodes_to_rich_text(inline_nodes)
        block: dict = {
            "type": "list_item",
            "list_type": list_type,
            "rich_text": rt,
            "indent": indent,
            "children": nested_blocks,
        }
        blocks.append(block)
    return blocks


def _walk_pre(node: Tag, indent: int) -> dict:
    code_node = node.find("code")
    if code_node:
        classes = code_node.get("class", []) # type: ignore
        lang = next(
            (c.replace("language-", "").lower() for c in classes if c.startswith("language-")), # type: ignore
            "plain text"
        )
        content = code_node.get_text()
    else:
        lang = "plain text"
        content = node.get_text()

    if lang not in NOTION_CODE_LANGS:
        lang = "plain text"

    return {"type": "code", "text": content, "language": lang, "indent": indent}


def _walk_table(node: Tag, indent: int) -> dict:
    """表格轉為 Notion table block"""
    rows_data = []
    has_header = False

    thead = node.find("thead")
    if thead:
        has_header = True
        for tr in thead.find_all("tr"):
            cells = [_collect_inline(cell) for cell in tr.find_all(["th", "td"])]
            rows_data.append(cells)

    tbody = node.find("tbody") or node
    for tr in tbody.find_all("tr", recursive=(tbody == node)):
        cells = [_collect_inline(cell) for cell in tr.find_all(["th", "td"])]
        if cells:
            rows_data.append(cells)

    col_count = max((len(r) for r in rows_data), default=1)

    # 補齊每行的 cell 數量
    for row in rows_data:
        while len(row) < col_count:
            row.append([_rt("")])

    return {
        "type": "table",
        "col_count": col_count,
        "has_header": has_header,
        "rows": rows_data,
        "indent": indent,
    }


def _merge_adjacent_paragraphs(blocks: list[dict]) -> list[dict]:
    """
    相鄰的純文字 NavigableString 段落合並，
    避免一句話被切成多個 paragraph block。
    """
    # 目前 walk 已按 block 輸出，此處保留為擴展點
    return blocks


# ─────────────────────────────────────────────
# Inline 解析：收集 rich_text 陣列
# ─────────────────────────────────────────────

def _collect_inline(node: Tag) -> list[dict]:
    """收集一個節點內所有 inline 內容，返回 rich_text list"""
    return _inline_nodes_to_rich_text(list(node.children))


def _inline_nodes_to_rich_text(
    nodes,
    bold=False,
    italic=False,
    code=False,
    strikethrough=False,
    underline=False,
    href: Optional[str] = None,
) -> list[dict]:
    result = []
    for node in nodes:
        if isinstance(node, NavigableString):
            text = str(node)
            # 過濾純空白（但保留單個空格，它在 inline 中有意義）
            if not text.strip() and text != " ":
                # 只有純換行/Tab 才跳過
                if set(text) <= {"\n", "\r", "\t"}:
                    continue
            if text:
                result.append(_rt(
                    text, bold=bold, italic=italic, code=code,
                    strikethrough=strikethrough, underline=underline, href=href
                ))
            continue

        if not isinstance(node, Tag):
            continue

        tag = node.name

        if tag in ("strong", "b"):
            result.extend(_inline_nodes_to_rich_text(
                node.children, bold=True, italic=italic, code=code,
                strikethrough=strikethrough, underline=underline, href=href
            ))
        elif tag in ("em", "i"):
            result.extend(_inline_nodes_to_rich_text(
                node.children, bold=bold, italic=True, code=code,
                strikethrough=strikethrough, underline=underline, href=href
            ))
        elif tag == "code":
            result.extend(_inline_nodes_to_rich_text(
                node.children, bold=bold, italic=italic, code=True,
                strikethrough=strikethrough, underline=underline, href=href
            ))
        elif tag in ("s", "del", "strike"):
            result.extend(_inline_nodes_to_rich_text(
                node.children, bold=bold, italic=italic, code=code,
                strikethrough=True, underline=underline, href=href
            ))
        elif tag == "u":
            result.extend(_inline_nodes_to_rich_text(
                node.children, bold=bold, italic=italic, code=code,
                strikethrough=strikethrough, underline=True, href=href
            ))
        elif tag == "a":
            link = node.get("href", "").strip() or href # type: ignore
            result.extend(_inline_nodes_to_rich_text(
                node.children, bold=bold, italic=italic, code=code,
                strikethrough=strikethrough, underline=underline, href=link
            ))
        elif tag == "br":
            result.append(_rt("\n", bold=bold, italic=italic, code=code,
                               strikethrough=strikethrough, underline=underline, href=href))
        elif tag == "img":
            # inline img，alt 文字作為佔位
            alt = node.get("alt", "").strip() # type: ignore
            if alt:
                result.append(_rt(f"[圖片: {alt}]"))
        else:
            # span / mark / 其他 inline 容器，透傳格式繼續遞歸
            result.extend(_inline_nodes_to_rich_text(
                node.children, bold=bold, italic=italic, code=code,
                strikethrough=strikethrough, underline=underline, href=href
            ))

    return result


# ─────────────────────────────────────────────
# Stage 2：中間格式 → Notion API Blocks
# ─────────────────────────────────────────────

def to_notion_blocks(intermediate: list[dict]) -> list[dict]:
    """將中間 block 列表轉為 Notion API block 格式"""
    blocks = []
    for b in intermediate:
        notion_block = _to_notion(b)
        if notion_block:
            blocks.append(notion_block)
    return blocks


def _to_notion(b: dict) -> Optional[dict]:
    t = b["type"]
    rt = b.get("rich_text") or []

    # 過濾空 rich_text 的段落
    if t == "paragraph":
        rt = _chunk_rich_text(rt)
        if not rt:
            return None
        return {"object": "block", "type": "paragraph",
                "paragraph": {"rich_text": rt}}

    if t == "heading":
        level = b.get("level", 1)
        ht = f"heading_{level}"
        return {"object": "block", "type": ht,
                ht: {"rich_text": _chunk_rich_text(rt)}}

    if t == "image":
        return {"object": "block", "type": "image",
                "image": {"type": "external", "external": {"url": b["url"]}}}

    if t == "list_item":
        list_type = "bulleted_list_item" if b["list_type"] == "bulleted" else "numbered_list_item"
        block: dict = {
            "object": "block",
            "type": list_type,
            list_type: {"rich_text": _chunk_rich_text(rt)},
        }
        children = [_to_notion(c) for c in b.get("children", [])]
        children = [c for c in children if c]
        if children:
            block[list_type]["children"] = children[:100]
        return block

    if t == "quote":
        return {"object": "block", "type": "quote",
                "quote": {"rich_text": _chunk_rich_text(rt)}}

    if t == "callout":
        return {"object": "block", "type": "callout",
                "callout": {
                    "rich_text": _chunk_rich_text(rt),
                    "icon": {"type": "emoji", "emoji": "💡"},
                    "color": "blue_background",
                }}

    if t == "code":
        content = b.get("text", "")[:2000]
        return {"object": "block", "type": "code",
                "code": {"rich_text": [_rt(content)],
                         "language": b.get("language", "plain text")}}

    if t == "divider":
        return {"object": "block", "type": "divider", "divider": {}}

    if t == "table":
        return _build_table_block(b)

    return None


def _build_table_block(b: dict) -> dict:
    rows = b.get("rows", [])
    col_count = b.get("col_count", 1)

    table_rows = []
    for row in rows:
        cells = [_chunk_rich_text(cell) for cell in row]
        table_rows.append({
            "object": "block",
            "type": "table_row",
            "table_row": {"cells": cells},
        })

    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": col_count,
            "has_column_header": b.get("has_header", False),
            "has_row_header": False,
            "children": table_rows,
        },
    }


# ─────────────────────────────────────────────
# rich_text 工具函數
# ─────────────────────────────────────────────

def _rt(
    content: str,
    bold: bool = False,
    italic: bool = False,
    code: bool = False,
    strikethrough: bool = False,
    underline: bool = False,
    href: Optional[str] = None,
) -> dict:
    obj: dict = {
        "type": "text",
        "text": {"content": content[:2000]},
        "annotations": {
            "bold": bold,
            "italic": italic,
            "code": code,
            "strikethrough": strikethrough,
            "underline": underline,
            "color": "default",
        },
    }
    if href:
        obj["text"]["link"] = {"url": href}
    return obj


def _chunk_rich_text(rt: list[dict]) -> list[dict]:
    """
    將 rich_text 列表中超過 2000 字的條目切分，
    確保每個 text.content 都在 Notion 的限制內。
    """
    result = []
    for item in rt:
        content = item["text"]["content"]
        if len(content) <= 2000:
            result.append(item)
        else:
            # 切分，保留相同 annotations
            for i in range(0, len(content), 2000):
                chunk = dict(item)
                chunk["text"] = dict(item["text"])
                chunk["text"]["content"] = content[i:i + 2000]
                result.append(chunk)
    return result


# ─────────────────────────────────────────────
# 圖片工具
# ─────────────────────────────────────────────

def _extract_img_src(node: Tag) -> str:
    src = (
        node.get("src") or node.get("data-src") or
        node.get("data-original") or node.get("data-lazy-src") or ""
    ).strip() # type: ignore

    if src.startswith("http://"):
        src = "https://" + src[7:]

    if not src.startswith("https://"):
        return ""

    if any(pattern in src for pattern in _HOTLINK_BLOCKED):
        return ""

    return src


# ─────────────────────────────────────────────
# 公開 API（向下兼容現有 entry_to_notion_blocks 調用）
# ─────────────────────────────────────────────

def html_to_notion_blocks(html: str) -> list[dict]:
    """完整管線：HTML → Notion Blocks"""
    parsed_result = parse_html(html)
    blocks = to_notion_blocks(parsed_result)
    return blocks


def entry_to_notion_blocks(entry) -> list[dict]:
    """RSSEntry → Notion block 列表（供 __main__.py 調用）"""
    if not entry.content_html:
        return []
    return html_to_notion_blocks(entry.content_html)

# ─────────────────────────────────────────────
# 測試
# ─────────────────────────────────────────────
# import json
# htmls_for_test: list[tuple] = [
#     ("段落", "<p>Hello <strong>World</strong></p>"),
#     ("標題", "<h1>標題一</h1><h2>標題二</h2>"),
#     ("無序列表", "<ul><li>A</li><li>B</li></ul>"),
#     ("有序列表", "<ol><li>第一</li><li>第二</li></ol>"),
#     ("嵌套列表", "<ul><li>A<ul><li>A1</li><li>A2</li></ul></li><li>B</li></ul>"), 
#     ("圖片", '<img src="https://example.com/img.jpg" alt="test">'),
#     ("段落內圖片", '<p>文字前<img src="https://example.com/img.jpg">文字後</p>'),
#     ("代碼塊", '<pre><code class="language-python">print("hello")</code></pre>'), 
#     ("引用", "<blockquote>這是引用</blockquote>"), 
#     ("分隔線", "<hr>"), 
#     ("表格", """
# <table>
#   <thead><tr><th>名稱</th><th>值</th></tr></thead>
#   <tbody>
#     <tr><td>A</td><td>1</td></tr>
#     <tr><td>B</td><td>2</td></tr>
#   </tbody>
# </table>
# """), 
#     ("inline 格式", "<p><strong>粗體</strong> <em>斜體</em> <code>code</code> <a href='https://example.com'>鏈接</a></p>"),
#     ("br 標籤", "<p>第一行<br>第二行</p>"), 
#     ("防盜鏈圖片（應無輸出）", '<img src="https://mmbiz.qpic.cn/xxx.jpg">'), 

# ]

# # 暫時在舊版 converter 裡保留 split_html_to_blocks + markdown_to_notion_blocks


# # 然後這樣對比：
# from rss2notion.utils.converter import split_html_to_blocks, markdown_to_notion_blocks

# def compare(label: str, html: str):
#     old_blocks_raw = split_html_to_blocks(html)
#     old_blocks = []
#     for kind, val in old_blocks_raw:
#         if kind == "text":
#             old_blocks.extend(markdown_to_notion_blocks(val))
#         else:
#             old_blocks.append({"type": "image", "image": {"external": {"url": val}}})
    
#     new_blocks = html_to_notion_blocks(html)
    
#     print(f"\n【{label}】舊版 {len(old_blocks)} 塊 / 新版 {len(new_blocks)} 塊")
#     if old_blocks != new_blocks:
#         print("  ⚠️  輸出不同")
#         print("  舊:", json.dumps(old_blocks, ensure_ascii=False))
#         print("  新:", json.dumps(new_blocks, ensure_ascii=False))
#     else:
#         print("  ✓ 輸出相同")

# for tag, html in htmls_for_test:
#     compare(tag, html)