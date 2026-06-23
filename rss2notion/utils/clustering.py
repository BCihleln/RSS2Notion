import difflib
from typing import TypeVar, Callable

T = TypeVar('T')

def cluster_items(items: list[T], key: Callable[[T], str], percentile: float = 0.05) -> list[list[T]]:
    """
    將項目列表依照指定字串的相似度進行分群 (Connected Components / Single-Linkage Clustering)。
    對所有項目進行 N*N 次的兩兩比對，計算所有相似度並由高至低排序。
    取前 `percentile` (如 0.05 代表前 5%) 的最後一個相似度作為動態閾值，
    只要任兩個項目的相似度 >= 該閾值，它們就會被歸類到同一個連通分量中。
    
    Args:
        items: 要分群的項目列表。
        key: 從項目中提取字串（用於計算相似度）的函式。
        percentile: 取前 X% 作為閾值參考 (0.0 ~ 1.0)。預設為 0.05。
        
    Returns:
        分群後的列表，每個元素是一個包含相似項目的子列表。
    """
    import math
    
    n = len(items)
    if n == 0:
        return []
    if n == 1:
        return [items]
        
    # 建立無向圖的鄰接串列
    adj: dict[int, list[int]] = {i: [] for i in range(n)}
    
    # 預先提取所有字串以提升效能
    item_strs = [key(item) for item in items]
    
    # 計算 N*(N-1)/2 次比對
    similarities = []
    pairs = []
    
    for i in range(n):
        for j in range(i + 1, n):
            s1 = item_strs[i]
            s2 = item_strs[j]
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
                
            similarities.append(sim)
            pairs.append((i, j, sim))
            
    if not similarities:
        return [[item] for item in items]
        
    similarities.sort(reverse=True)
    cutoff_index = max(0, math.ceil(len(similarities) * percentile) - 1)
    dynamic_threshold = similarities[cutoff_index]
    
    for i, j, sim in pairs:
        if sim >= dynamic_threshold:
            adj[i].append(j)
            adj[j].append(i)
                
    # 找出所有連通分量 (Connected Components)
    visited = set()
    clusters: list[list[T]] = []
    
    for i in range(n):
        if i not in visited:
            component = []
            queue = [i]
            visited.add(i)
            
            while queue:
                curr = queue.pop(0)
                component.append(items[curr])
                
                for neighbor in adj[curr]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
                        
            clusters.append(component)
            
    return clusters
