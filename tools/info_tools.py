# tools/info_tools.py
"""
検索エンジンを使用したWeb検索などの情報取得ツール。
本番環境向けに実際のAPIを使用する実装。
"""
from core.logging_config import logger
import requests
import json
import os
from typing import Optional, List, Dict, Any
from tools.tool_registry import tool

# 検索APIの設定
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "")
SEARCH_API_URL = os.getenv("SEARCH_API_URL", "https://api.bing.microsoft.com/v7.0/search")

@tool(
    name="info_search_web",
    description="検索エンジンでWeb検索を行う",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "検索クエリ"},
            "date_range": {
                "type": "string",
                "enum": ["all", "past_day", "past_week", "past_month", "past_year"],
                "description": "検索期間（任意）"
            },
            "result_count": {
                "type": "integer",
                "description": "取得する結果の数（任意）",
                "default": 5
            }
        },
        "required": ["query"]
    }
)
def info_search_web(query: str, date_range: str = "all", result_count: int = 5):
    """
    検索エンジンを使用してWeb検索を実行します。
    
    Args:
        query: 検索クエリ
        date_range: 検索期間
        result_count: 取得する結果の数
        
    Returns:
        検索結果を含む文字列
    """
    logger.info(f"Web検索実行: クエリ='{query}', 期間={date_range}, 結果数={result_count}")
    
    # API設定チェック
    if not SEARCH_API_KEY:
        # バックアップとしてデモデータを使用
        return _demo_search(query)
    
    try:
        # Bingの検索パラメータ設定
        params = {
            "q": query,
            "count": min(result_count, 10),  # 最大10件まで
            "responseFilter": "Webpages",
            "textFormat": "Raw"
        }
        
        # 期間フィルタを追加
        if date_range != "all":
            freshness_map = {
                "past_day": "Day",
                "past_week": "Week",
                "past_month": "Month",
                "past_year": "Year"
            }
            params["freshness"] = freshness_map.get(date_range, "")
        
        # ヘッダー設定
        headers = {
            "Ocp-Apim-Subscription-Key": SEARCH_API_KEY,
            "Accept": "application/json"
        }
        
        # API呼び出し
        response = requests.get(SEARCH_API_URL, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        # 結果の整形
        results = []
        if "webPages" in data and "value" in data["webPages"]:
            for i, result in enumerate(data["webPages"]["value"], 1):
                title = result.get("name", "タイトルなし")
                url = result.get("url", "")
                snippet = result.get("snippet", "説明なし")
                results.append(f"{i}. {title} (URL: {url})\n   概要: {snippet}\n")
        
        if not results:
            return f"クエリ '{query}' に一致する検索結果は見つかりませんでした。"
        
        output = f"検索クエリ: {query}\n\n" + "\n".join(results)
        
        # 結果の長さ制限
        if len(output) > 4000:
            output = output[:4000] + "...\n(結果が長すぎるため省略されました)"
            
        return output
        
    except Exception as e:
        logger.error(f"検索API呼び出しエラー: {str(e)}")
        # エラー時はデモデータにフォールバック
        return _demo_search(query) + f"\n\n注: 検索API呼び出し中にエラーが発生しました: {str(e)}"

def _demo_search(query: str) -> str:
    """デモ用の検索結果を返す（APIが利用できない場合のフォールバック）"""
    DEMO_SEARCH = {
        "ai": [
            {
                "title": "AI総合ガイド",
                "url": "https://example.com/ai-guide",
                "snippet": "AIとは何か、機械学習・深層学習・応用事例などをまとめた記事。"
            },
            {
                "title": "AI最新ニュース2025",
                "url": "https://example.com/ai-news2025",
                "snippet": "2025年のAI技術動向と今後の課題について。"
            }
        ],
        "python": [
            {
                "title": "Python公式サイト",
                "url": "https://www.python.org/",
                "snippet": "Python言語の公式情報。ダウンロードやドキュメント。"
            },
            {
                "title": "Python入門",
                "url": "https://example.com/python-intro",
                "snippet": "初心者向けにPythonの文法・実践例を紹介。"
            }
        ],
        "japan": [
            {
                "title": "日本観光ガイド",
                "url": "https://example.com/japan-tourism",
                "snippet": "日本の主要観光地と文化体験に関する情報。"
            }
        ],
        "korea": [
            {
                "title": "韓国旅行情報2025",
                "url": "https://example.com/korea-travel-2025",
                "snippet": "2025年の韓国旅行情報と観光スポット、グルメ情報など。"
            },
            {
                "title": "ソウル観光ガイド",
                "url": "https://example.com/seoul-guide",
                "snippet": "ソウルの人気観光スポットとアクセス方法、おすすめプラン。"
            }
        ]
    }
    
    keywords = query.lower().split()
    results = []
    for kw in keywords:
        if kw in DEMO_SEARCH:
            results.extend(DEMO_SEARCH[kw])
    
    if not results:
        import random
        # ランダムで返す
        all_results = []
        for vals in DEMO_SEARCH.values():
            all_results.extend(vals)
        results = random.sample(all_results, min(len(all_results), 2))
    
    out = f"検索クエリ: {query}\n"
    for i, r in enumerate(results, start=1):
        out += f"{i}. {r['title']} (URL: {r['url']})\n   概要: {r['snippet']}\n"
    
    return out + "\n(注: 検索APIキーが設定されていないため、デモデータを表示しています。)"
