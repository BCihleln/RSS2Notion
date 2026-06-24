import os
import sys
import json
import difflib
from pathlib import Path

# 將專案根目錄加入 PYTHONPATH 以便讀取 rss2notion 模組
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from rss2notion.utils.config import Config
from rss2notion.notion.client import NotionClient
from rss2notion.notion.subscription import get_avaliable_subscriptions
from rss2notion.sync import fetch_subscription

def main():
    config = Config.from_env()
    client = NotionClient(
        api_key=config.notion_api_key,
        retry_times=config.retry_times,
        retry_delay=config.retry_delay,
        notion_user_id=config.notion_user_id,
    )
    
    subscriptions = get_avaliable_subscriptions(
        client, 
        config.entries_datasource_id
    )
    
    agg_sub = next((s for s in subscriptions if getattr(s, 'is_aggregated', False)), None)
    if not agg_sub:
        print("No aggregated subscription found.")
        return
        
    print(f"Fetching RSS for: {agg_sub.name}")
    sub, result = fetch_subscription(agg_sub)
    if isinstance(result, Exception):
        print(f"Error fetching: {result}")
        return
        
    entries = result
    entries = entries[:100]  # 取前 100 筆作為視覺化範例
    n = len(entries)
    titles = [e.title for e in entries]
    
    nodes = []
    edges = []
    
    for i, title in enumerate(titles):
        label = title[:15] + "..." if len(title) > 15 else title
        nodes.append({
            "id": i,
            "label": label,
            "title": title,
            "size": 20,
            "color": "#8fd9b6",
            "font": {"color": "white"}
        })
        
    similarities_list = []
    
    for i in range(n):
        for j in range(i + 1, n):
            s1 = titles[i]
            s2 = titles[j]
            matcher = difflib.SequenceMatcher(None, s1, s2)
            sim = matcher.ratio()
            
            # LCS weighting
            min_len = min(len(s1), len(s2))
            if min_len > 0:
                match = matcher.find_longest_match(0, len(s1), 0, len(s2))
                lcs_weight = match.size / min_len
                sim = sim * lcs_weight
            else:
                sim = 0.0
                
            similarities_list.append(sim)
            edges.append({
                "from": i,
                "to": j,
                "value": sim,
                "title": f"Similarity: {sim*100:.1f}%",
                "label": f"{sim*100:.1f}%"
            })
            
    similarities_list.sort(reverse=True)
            
    graph_data = {
        "nodes": nodes,
        "edges": edges,
        "similarities": similarities_list,
        "percentile": config.aggregation_similarity_percentile
    }
    
    out_path = Path(__file__).parent / "clustering_data.js"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"const graphData = {json.dumps(graph_data, ensure_ascii=False, indent=2)};\n")
        
    print(f"Data saved to {out_path}")
    
    html_path = Path(__file__).parent / "clustering_viewer.html"
    print(f"Opening viewer at {html_path} ...")
    try:
        os.startfile(str(html_path))
    except Exception:
        print("Please open the HTML file manually in your browser.")

if __name__ == "__main__":
    main()
