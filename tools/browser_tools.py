# tools/browser_tools.py
"""
強化されたブラウザ操作ツール。Playwrightを使用した高度なウェブスクレイピングと対話機能を提供。
"""
from core.logging_config import logger
import asyncio
import os
import json
import re
from typing import Optional, Union, Dict, Any, List, Tuple
from urllib.parse import urlparse
from sandbox.sandbox import get_sandbox
from tools.tool_registry import tool
from playwright.async_api import async_playwright, Page



# グローバル変数
_browser_context = None
_current_page = None

async def _ensure_browser(headless: bool = True):
    """ブラウザセッションが存在することを確認し、必要に応じて初期化する"""
    global _browser_context, _current_page
    
    if _browser_context is not None:
        return _browser_context, _current_page
    
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=headless)
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36"
    )
    
    _browser_context = context
    _current_page = await context.new_page()
    
    return context, _current_page

@tool(
    name="browser_navigate",
    description="Playwrightで指定URLにアクセスする",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "アクセスするURL"}
        },
        "required": ["url"]
    }
)
def browser_navigate(url: str):
    """
    指定されたURLにブラウザでアクセスします。
    
    Args:
        url: アクセスするURL
        
    Returns:
        ページの内容とタイトルを含む文字列
    """
    # 同期関数として実行
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_navigate_async(url))
    loop.close()
    return res

async def _navigate_async(url: str):
    """非同期でURLにアクセスし、ページ内容を取得"""
    context, page = await _ensure_browser(headless=True)
    
    try:
        # URLにプロトコルがなければ追加
        if not url.startswith(('http://', 'https://')):
            url = f"https://{url}"
        
        # ページにアクセス
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        
        # ページが完全に読み込まれるまで少し待機
        await asyncio.sleep(2)
        
        # ページのタイトルとURLを取得
        title = await page.title()
        current_url = page.url
        
        # ページの内容をMarkdown形式で抽出
        extracted_text = await _extract_content_as_markdown(page)
        
        # 結果を整形
        result = (
            f"## ページ情報\n"
            f"タイトル: {title}\n"
            f"URL: {current_url}\n\n"
            f"## ページ内容\n"
            f"{extracted_text}\n\n"
            f"※注意: コンテンツが多すぎる場合は一部のみ表示されます。browser_scroll_downを使用して下にスクロールすると、さらに表示できます。"
        )
        
        return result
    except Exception as e:
        error_message = f"ナビゲーションエラー: {str(e)}"
        logger.error(error_message)
        return error_message

async def _extract_content_as_markdown(page: Page) -> str:
    """ページの内容をMarkdown形式で抽出"""
    try:
        # ページからテキストコンテンツを抽出するJavaScriptを実行
        markdown = await page.evaluate("""() => {
            function getVisibleText(element, depth = 0) {
                if (!element) return '';
                
                // 非表示要素をスキップ
                const style = window.getComputedStyle(element);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                    return '';
                }
                
                // テキストノードの場合
                if (element.nodeType === Node.TEXT_NODE) {
                    return element.textContent.trim() ? element.textContent.trim() + ' ' : '';
                }
                
                // 要素の種類に基づいてマークダウン形式に変換
                let md = '';
                const tagName = element.tagName ? element.tagName.toLowerCase() : '';
                
                // 見出し
                if (tagName.match(/^h[1-6]$/)) {
                    const level = tagName.charAt(1);
                    let prefix = '';
                    for (let i = 0; i < parseInt(level); i++) {
                        prefix += '#';
                    }
                    md += `\\n${prefix} `;
                }
                // 段落
                else if (tagName === 'p') {
                    md += '\\n\\n';
                }
                // リスト項目
                else if (tagName === 'li') {
                    md += '\\n- ';
                }
                // テーブル行
                else if (tagName === 'tr') {
                    md += '\\n|';
                }
                // テーブルデータ
                else if (tagName === 'td' || tagName === 'th') {
                    md += ' ';
                }
                
                // 子要素を再帰的に処理
                for (const child of element.childNodes) {
                    md += getVisibleText(child, depth + 1);
                }
                
                // 特定の要素の後に改行を追加
                if (tagName === 'div' || tagName === 'section' || tagName === 'article') {
                    md += '\\n';
                }
                else if (tagName === 'td' || tagName === 'th') {
                    md += ' |';
                }
                
                return md;
            }
            
            return getVisibleText(document.body).replace(/\\n\\s*\\n\\s*\\n/g, '\\n\\n').trim();
        }""")
        
        # 長すぎる場合は切り詰める
        if len(markdown) > 10000:
            markdown = markdown[:10000] + "...\n\n(コンテンツが長すぎるため切り詰められました)"
        
        return markdown
    except Exception as e:
        logger.error(f"コンテンツ抽出エラー: {str(e)}")
        return f"コンテンツの抽出に失敗しました: {str(e)}"

@tool(
    name="browser_extract_elements",
    description="ページから特定の要素を抽出する",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "抽出する要素のCSSセレクタ"},
            "attribute": {"type": "string", "description": "(オプション) 抽出する属性名"}
        },
        "required": ["selector"]
    }
)
def browser_extract_elements(selector: str, attribute: Optional[str] = None):
    """
    現在のページから特定の要素を抽出します。
    
    Args:
        selector: 抽出する要素のCSSセレクタ
        attribute: 抽出する属性名（指定しない場合はテキスト内容を抽出）
        
    Returns:
        抽出された要素のリストを含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_extract_elements_async(selector, attribute))
    loop.close()
    return res

async def _extract_elements_async(selector: str, attribute: Optional[str] = None):
    """非同期で要素を抽出"""
    if _browser_context is None or _current_page is None:
        return "ブラウザが初期化されていません。まずbrowser_navigateを使用してください。"
    
    try:
        # セレクタに一致する要素を取得
        elements = await _current_page.query_selector_all(selector)
        
        if not elements:
            return f"セレクタ '{selector}' に一致する要素が見つかりませんでした。"
        
        results = []
        
        for i, element in enumerate(elements):
            if attribute:
                # 特定の属性を抽出
                value = await element.get_attribute(attribute)
                results.append(f"{i+1}. [{attribute}] {value}")
            else:
                # テキスト内容を抽出
                text = await element.text_content()
                results.append(f"{i+1}. {text.strip()}")
        
        return f"抽出された要素 (合計: {len(results)}件):\n\n" + "\n".join(results)
    
    except Exception as e:
        error_message = f"要素抽出エラー: {str(e)}"
        logger.error(error_message)
        return error_message

@tool(
    name="browser_extract_structured_data",
    description="ウェブページから構造化データを抽出する",
    parameters={
        "type": "object",
        "properties": {
            "data_type": {
                "type": "string",
                "enum": ["table", "list", "form", "links"],
                "description": "抽出するデータの種類"
            }
        },
        "required": ["data_type"]
    }
)
def browser_extract_structured_data(data_type: str):
    """
    現在のウェブページから構造化データを抽出します。
    
    Args:
        data_type: 抽出するデータの種類（table, list, form, links）
        
    Returns:
        抽出された構造化データを含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_extract_structured_data_async(data_type))
    loop.close()
    return res

async def _extract_structured_data_async(data_type: str):
    """非同期で構造化データを抽出"""
    if _browser_context is None or _current_page is None:
        return "ブラウザが初期化されていません。まずbrowser_navigateを使用してください。"
    
    try:
        if data_type == "table":
            # テーブルデータを抽出
            tables = await _current_page.query_selector_all("table")
            
            if not tables:
                return "ページ内にテーブルが見つかりませんでした。"
            
            results = []
            
            for i, table in enumerate(tables):
                table_data = await _current_page.evaluate("""(table) => {
                    const rows = Array.from(table.querySelectorAll('tr'));
                    return rows.map(row => {
                        const cells = Array.from(row.querySelectorAll('th, td'));
                        return cells.map(cell => cell.textContent.trim());
                    });
                }""", table)
                
                if table_data and table_data[0]:
                    results.append(f"テーブル {i+1}:\n")
                    
                    # ヘッダー行とデータ行を分離
                    headers = table_data[0]
                    data_rows = table_data[1:]
                    
                    # ヘッダーを表示
                    results.append("| " + " | ".join(headers) + " |")
                    results.append("| " + " | ".join(["---" for _ in headers]) + " |")
                    
                    # データ行を表示
                    for row in data_rows:
                        results.append("| " + " | ".join(row) + " |")
                    
                    results.append("\n")
            
            return "\n".join(results)
        
        elif data_type == "list":
            # リストデータを抽出
            lists = await _current_page.query_selector_all("ul, ol")
            
            if not lists:
                return "ページ内にリストが見つかりませんでした。"
            
            results = []
            
            for i, list_element in enumerate(lists):
                list_type = await list_element.get_attribute("type")
                is_ordered = await list_element.evaluate("element => element.tagName.toLowerCase() === 'ol'")
                
                list_items = await list_element.query_selector_all("li")
                if not list_items:
                    continue
                
                results.append(f"\nリスト {i+1} ({('順序付き' if is_ordered else '順序なし')}):")
                
                for j, item in enumerate(list_items):
                    text = await item.text_content()
                    prefix = f"{j+1}." if is_ordered else "-"
                    results.append(f"{prefix} {text.strip()}")
            
            return "\n".join(results)
        
        elif data_type == "form":
            # フォーム要素を抽出
            forms = await _current_page.query_selector_all("form")
            
            if not forms:
                return "ページ内にフォームが見つかりませんでした。"
            
            results = []
            
            for i, form in enumerate(forms):
                form_action = await form.get_attribute("action") or "未指定"
                form_method = await form.get_attribute("method") or "GET"
                
                results.append(f"\nフォーム {i+1}:")
                results.append(f"アクション: {form_action}")
                results.append(f"メソッド: {form_method}")
                results.append("フィールド:")
                
                input_elements = await form.query_selector_all("input, select, textarea, button")
                
                for input_elem in input_elements:
                    elem_type = await input_elem.evaluate("element => element.tagName.toLowerCase()")
                    
                    if elem_type == "input":
                        input_type = await input_elem.get_attribute("type") or "text"
                        name = await input_elem.get_attribute("name") or "未指定"
                        placeholder = await input_elem.get_attribute("placeholder") or ""
                        
                        results.append(f"- Input: type={input_type}, name={name}" + (f", placeholder=\"{placeholder}\"" if placeholder else ""))
                    
                    elif elem_type == "select":
                        name = await input_elem.get_attribute("name") or "未指定"
                        options = await input_elem.query_selector_all("option")
                        option_values = []
                        
                        for option in options:
                            text = await option.text_content()
                            value = await option.get_attribute("value")
                            option_values.append(f"{text.strip()}={value}")
                        
                        results.append(f"- Select: name={name}, options=[{', '.join(option_values[:5])}]" + ("..." if len(option_values) > 5 else ""))
                    
                    elif elem_type == "textarea":
                        name = await input_elem.get_attribute("name") or "未指定"
                        results.append(f"- Textarea: name={name}")
                    
                    elif elem_type == "button":
                        button_type = await input_elem.get_attribute("type") or "button"
                        text = await input_elem.text_content()
                        results.append(f"- Button: type={button_type}, text=\"{text.strip()}\"")
            
            return "\n".join(results)
        
        elif data_type == "links":
            # リンクを抽出
            links = await _current_page.query_selector_all("a[href]")
            
            if not links:
                return "ページ内にリンクが見つかりませんでした。"
            
            results = ["抽出されたリンク:"]
            
            current_url = _current_page.url
            parsed_current = urlparse(current_url)
            current_base = f"{parsed_current.scheme}://{parsed_current.netloc}"
            
            link_data = []
            
            for link in links:
                text = await link.text_content()
                href = await link.get_attribute("href")
                
                if not href or href.startswith("javascript:"):
                    continue
                
                # 相対URLを絶対URLに変換
                if href.startswith("/"):
                    href = f"{current_base}{href}"
                elif not href.startswith(("http://", "https://")):
                    href = f"{current_base}/{href}"
                
                link_data.append({"text": text.strip() or "[画像/アイコン]", "href": href})
            
            # リンクを重複排除して表示
            unique_links = []
            seen_hrefs = set()
            
            for link in link_data:
                if link["href"] not in seen_hrefs and link["text"]:
                    unique_links.append(link)
                    seen_hrefs.add(link["href"])
            
            # リンクの表示（上位50件まで）
            for i, link in enumerate(unique_links[:50]):
                results.append(f"{i+1}. [{link['text']}]({link['href']})")
            
            if len(unique_links) > 50:
                results.append(f"\n...さらに {len(unique_links) - 50} 件のリンクがあります。")
            
            return "\n".join(results)
        
        else:
            return f"未対応のデータ種類: {data_type}"
    
    except Exception as e:
        error_message = f"構造化データ抽出エラー: {str(e)}"
        logger.error(error_message)
        return error_message

@tool(
    name="browser_view",
    description="現在のページ内容を表示する",
    parameters={
        "type": "object",
        "properties": {}
    }
)
def browser_view():
    """
    現在開いているページの内容を表示します。
    
    Returns:
        ページの内容とタイトルを含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_view_async())
    loop.close()
    return res

async def _view_async():
    """非同期でページ内容を取得"""
    if _browser_context is None or _current_page is None:
        return "ブラウザが初期化されていません。まずbrowser_navigateを使用してください。"
    
    try:
        # ページのタイトルとURLを取得
        title = await _current_page.title()
        current_url = _current_page.url
        
        # ページの内容をMarkdown形式で抽出
        extracted_text = await _extract_content_as_markdown(_current_page)
        
        # 結果を整形
        result = (
            f"## 現在のページ情報\n"
            f"タイトル: {title}\n"
            f"URL: {current_url}\n\n"
            f"## ページ内容\n"
            f"{extracted_text}\n\n"
        )
        
        return result
    except Exception as e:
        error_message = f"ページ表示エラー: {str(e)}"
        logger.error(error_message)
        return error_message

@tool(
    name="browser_click",
    description="ページ内の要素をクリックする",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "クリックする要素のCSSセレクタ"},
            "index": {"type": "integer", "description": "(オプション) 複数ある場合のインデックス（0から開始）"}
        },
        "required": ["selector"]
    }
)
def browser_click(selector: str, index: int = 0):
    """
    指定されたセレクタの要素をクリックします。
    
    Args:
        selector: クリックする要素のCSSセレクタ
        index: 複数要素がある場合のインデックス（0から開始）
        
    Returns:
        クリック結果を含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_click_async(selector, index))
    loop.close()
    return res

async def _click_async(selector: str, index: int = 0):
    """非同期で要素をクリック"""
    if _browser_context is None or _current_page is None:
        return "ブラウザが初期化されていません。まずbrowser_navigateを使用してください。"
    
    try:
        # セレクタに一致する要素を取得
        elements = await _current_page.query_selector_all(selector)
        
        if not elements:
            return f"セレクタ '{selector}' に一致する要素が見つかりませんでした。"
        
        if index >= len(elements):
            return f"指定されたインデックス {index} が範囲外です（要素数: {len(elements)}）。"
        
        # 対象の要素をクリック
        element = elements[index]
        await element.scroll_into_view_if_needed()
        await element.click()
        
        # クリック後にページが変わる可能性があるので少し待機
        await asyncio.sleep(2)
        
        # 新しいページ情報を取得
        title = await _current_page.title()
        url = _current_page.url
        
        return f"要素をクリックしました。\n現在のページ: {title} ({url})"
    
    except Exception as e:
        error_message = f"クリックエラー: {str(e)}"
        logger.error(error_message)
        return error_message

@tool(
    name="browser_input",
    description="入力欄にテキストを入力する",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "入力欄のCSSセレクタ"},
            "text": {"type": "string", "description": "入力するテキスト"},
            "press_enter": {"type": "boolean", "description": "入力後にEnterキーを押すかどうか"}
        },
        "required": ["selector", "text"]
    }
)
def browser_input(selector: str, text: str, press_enter: bool = False):
    """
    指定されたセレクタの入力欄にテキストを入力します。
    
    Args:
        selector: 入力欄のCSSセレクタ
        text: 入力するテキスト
        press_enter: 入力後にEnterキーを押すかどうか
        
    Returns:
        入力結果を含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_input_async(selector, text, press_enter))
    loop.close()
    return res

async def _input_async(selector: str, text: str, press_enter: bool = False):
    """非同期で入力欄にテキストを入力"""
    if _browser_context is None or _current_page is None:
        return "ブラウザが初期化されていません。まずbrowser_navigateを使用してください。"
    
    try:
        # 入力欄を取得
        input_element = await _current_page.query_selector(selector)
        
        if not input_element:
            return f"セレクタ '{selector}' に一致する入力欄が見つかりませんでした。"
        
        # 現在の入力内容をクリア
        await input_element.click()
        await input_element.fill("")
        
        # 新しいテキストを入力
        await input_element.type(text, delay=50)  # 人間らしく少し遅延を入れて入力
        
        # Enterキーを押す（オプション）
        if press_enter:
            await input_element.press("Enter")
            # ページが変わる可能性があるので少し待機
            await asyncio.sleep(2)
        
        return f"テキスト「{text}」を入力しました。" + (" Enterキーを押しました。" if press_enter else "")
    
    except Exception as e:
        error_message = f"入力エラー: {str(e)}"
        logger.error(error_message)
        return error_message

@tool(
    name="browser_scroll_down",
    description="ページを下にスクロールする",
    parameters={
        "type": "object",
        "properties": {
            "amount": {"type": "integer", "description": "(オプション) スクロールする量（ピクセル）"},
            "to_bottom": {"type": "boolean", "description": "(オプション) ページ最下部までスクロールするかどうか"}
        }
    }
)
def browser_scroll_down(amount: int = 500, to_bottom: bool = False):
    """
    ページを下にスクロールします。
    
    Args:
        amount: スクロールする量（ピクセル）
        to_bottom: ページ最下部までスクロールするかどうか
        
    Returns:
        スクロール結果を含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_scroll_down_async(amount, to_bottom))
    loop.close()
    return res

async def _scroll_down_async(amount: int = 500, to_bottom: bool = False):
    """非同期でページをスクロール"""
    if _browser_context is None or _current_page is None:
        return "ブラウザが初期化されていません。まずbrowser_navigateを使用してください。"
    
    try:
        if to_bottom:
            # ページ最下部までスクロール
            await _current_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            result = "ページ最下部までスクロールしました。"
        else:
            # 指定された量だけスクロール
            await _current_page.evaluate(f"window.scrollBy(0, {amount})")
            result = f"{amount}ピクセル下にスクロールしました。"
        
        # スクロール後に少し待機して、動的コンテンツがロードされる時間を確保
        await asyncio.sleep(1)
        
        return result
    
    except Exception as e:
        error_message = f"スクロールエラー: {str(e)}"
        logger.error(error_message)
        return error_message

@tool(
    name="browser_scroll_up",
    description="ページを上にスクロールする",
    parameters={
        "type": "object",
        "properties": {
            "amount": {"type": "integer", "description": "(オプション) スクロールする量（ピクセル）"},
            "to_top": {"type": "boolean", "description": "(オプション) ページ最上部までスクロールするかどうか"}
        }
    }
)
def browser_scroll_up(amount: int = 500, to_top: bool = False):
    """
    ページを上にスクロールします。
    
    Args:
        amount: スクロールする量（ピクセル）
        to_top: ページ最上部までスクロールするかどうか
        
    Returns:
        スクロール結果を含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_scroll_up_async(amount, to_top))
    loop.close()
    return res

async def _scroll_up_async(amount: int = 500, to_top: bool = False):
    """非同期でページを上にスクロール"""
    if _browser_context is None or _current_page is None:
        return "ブラウザが初期化されていません。まずbrowser_navigateを使用してください。"
    
    try:
        if to_top:
            # ページ最上部までスクロール
            await _current_page.evaluate("window.scrollTo(0, 0)")
            result = "ページ最上部までスクロールしました。"
        else:
            # 指定された量だけ上にスクロール
            await _current_page.evaluate(f"window.scrollBy(0, -{amount})")
            result = f"{amount}ピクセル上にスクロールしました。"
        
        return result
    
    except Exception as e:
        error_message = f"スクロールエラー: {str(e)}"
        logger.error(error_message)
        return error_message

@tool(
    name="browser_screenshot",
    description="現在のページのスクリーンショットを撮影する",
    parameters={
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "(オプション) 特定の要素のスクリーンショットを撮影する場合のCSSセレクタ"},
            "save_path": {"type": "string", "description": "スクリーンショットを保存するパス（.pngで終わる必要があります）"}
        },
        "required": ["save_path"]
    }
)
def browser_screenshot(save_path: str, selector: Optional[str] = None):
    """
    現在のページまたは特定の要素のスクリーンショットを撮影します。
    
    Args:
        save_path: スクリーンショットを保存するパス（.pngで終わる必要があります）
        selector: 特定の要素のスクリーンショットを撮影する場合のCSSセレクタ
        
    Returns:
        スクリーンショット結果を含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_screenshot_async(save_path, selector))
    loop.close()
    return res

async def _screenshot_async(save_path: str, selector: Optional[str] = None):
    """非同期でスクリーンショットを撮影"""
    if _browser_context is None or _current_page is None:
        return "ブラウザが初期化されていません。まずbrowser_navigateを使用してください。"
    
    try:
        # 保存パスを絶対パスに変換
        if not os.path.isabs(save_path):
            save_path = os.path.abspath(save_path)
        
        # 保存ディレクトリが存在しない場合は作成
        save_dir = os.path.dirname(save_path)
        os.makedirs(save_dir, exist_ok=True)
        
        if selector:
            # 特定の要素のスクリーンショットを撮影
            element = await _current_page.query_selector(selector)
            
            if not element:
                return f"セレクタ '{selector}' に一致する要素が見つかりませんでした。"
            
            await element.screenshot(path=save_path)
            return f"要素 '{selector}' のスクリーンショットを '{save_path}' に保存しました。"
        else:
            # ページ全体のスクリーンショットを撮影
            await _current_page.screenshot(path=save_path, full_page=True)
            return f"ページ全体のスクリーンショットを '{save_path}' に保存しました。"
    
    except Exception as e:
        error_message = f"スクリーンショットエラー: {str(e)}"
        logger.error(error_message)
        return error_message

@tool(
    name="browser_run_javascript",
    description="ページでJavaScriptコードを実行する",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "実行するJavaScriptコード"}
        },
        "required": ["code"]
    }
)
def browser_run_javascript(code: str):
    """
    現在のページでJavaScriptコードを実行します。
    
    Args:
        code: 実行するJavaScriptコード
        
    Returns:
        実行結果を含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_run_javascript_async(code))
    loop.close()
    return res

async def _run_javascript_async(code: str):
    """非同期でJavaScriptを実行"""
    if _browser_context is None or _current_page is None:
        return "ブラウザが初期化されていません。まずbrowser_navigateを使用してください。"
    
    try:
        # JavaScriptコードを実行
        result = await _current_page.evaluate(code)
        
        # 結果の型を確認して適切に処理
        if result is None:
            return "コードが実行されました。（戻り値なし）"
        elif isinstance(result, (dict, list)):
            # オブジェクトや配列はJSON文字列に変換
            return f"実行結果:\n```json\n{json.dumps(result, indent=2, ensure_ascii=False)}\n```"
        else:
            # プリミティブ型はそのまま文字列化
            return f"実行結果: {result}"
    
    except Exception as e:
        error_message = f"JavaScript実行エラー: {str(e)}"
        logger.error(error_message)
        return error_message

@tool(
    name="browser_extract_pdf",
    description="PDF文書からテキストを抽出する",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "PDFファイルのURL"},
            "pages": {"type": "string", "description": "抽出するページ範囲（例：1-5,10,15-20）。空の場合は全ページ"}
        },
        "required": ["url"]
    }
)
def browser_extract_pdf(url: str, pages: str = ""):
    """
    PDF文書からテキストを抽出します。
    
    Args:
        url: PDFファイルのURL
        pages: 抽出するページ範囲（例：1-5,10,15-20）。空の場合は全ページ
        
    Returns:
        抽出されたテキストを含む文字列
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    res = loop.run_until_complete(_extract_pdf_async(url, pages))
    loop.close()
    return res

async def _extract_pdf_async(url: str, pages: str = ""):
    """非同期でPDFテキスト抽出"""
    if not url.lower().endswith('.pdf'):
        return "PDFファイルのURLではありません。.pdfで終わるURLを提供してください。"
    
    try:
        import tempfile
        import PyPDF2
        import aiohttp
        
        # PDFファイルをダウンロード
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return f"PDFダウンロード失敗: ステータスコード {response.status}"
                
                pdf_content = await response.read()
        
        # 一時ファイルに保存
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
            temp_file_path = temp_file.name
            temp_file.write(pdf_content)
        
        # ページ範囲を解析
        page_ranges = []
        if pages:
            for part in pages.split(','):
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    page_ranges.extend(range(start, end + 1))
                else:
                    page_ranges.append(int(part))
        
        # PyPDF2でテキスト抽出
        text_content = ""
        page_count = 0
        
        with open(temp_file_path, 'rb') as f:
            pdf_reader = PyPDF2.PdfReader(f)
            num_pages = len(pdf_reader.pages)
            
            if not page_ranges:  # 全ページ抽出
                page_ranges = range(1, num_pages + 1)
            
            for page_num in page_ranges:
                if page_num < 1 or page_num > num_pages:
                    continue
                
                # PyPDF2はゼロベースのインデックス
                page = pdf_reader.pages[page_num - 1]
                extracted_text = page.extract_text()
                
                if extracted_text:
                    page_count += 1
                    text_content += f"// ページ {page_num}\n{extracted_text}\n\n"
        
        # 一時ファイルを削除
        os.unlink(temp_file_path)
        
        # より高度な抽出を試みる
        if not text_content.strip() or page_count == 0:
            # PyMuPDFを試す
            try:
                import fitz  # PyMuPDF
                
                # 一時ファイルに再度保存
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
                    temp_file_path = temp_file.name
                    temp_file.write(pdf_content)
                
                text_content = ""
                page_count = 0
                
                with fitz.open(temp_file_path) as doc:
                    num_pages = len(doc)
                    
                    if not page_ranges:  # 全ページ抽出
                        page_ranges = range(1, num_pages + 1)
                    
                    for page_num in page_ranges:
                        if page_num < 1 or page_num > num_pages:
                            continue
                        
                        # PyMuPDFはゼロベースのインデックス
                        page = doc[page_num - 1]
                        extracted_text = page.get_text()
                        
                        if extracted_text:
                            page_count += 1
                            text_content += f"// ページ {page_num}\n{extracted_text}\n\n"
                
                # 一時ファイルを削除
                os.unlink(temp_file_path)
            except ImportError:
                # PyMuPDFがインストールされていない
                pass
        
        # それでも失敗した場合、OCRを試みる
        if not text_content.strip() or page_count == 0:
            try:
                import pytesseract
                from PIL import Image
                import pdf2image
                
                # 一時ファイルに再度保存
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
                    temp_file_path = temp_file.name
                    temp_file.write(pdf_content)
                
                text_content = ""
                page_count = 0
                
                # PDFを画像に変換して、OCRでテキスト抽出
                images = pdf2image.convert_from_path(temp_file_path)
                
                for i, image in enumerate(images):
                    page_num = i + 1
                    if page_ranges and page_num not in page_ranges:
                        continue
                    
                    extracted_text = pytesseract.image_to_string(image, lang='jpn+eng')
                    if extracted_text:
                        page_count += 1
                        text_content += f"// ページ {page_num}\n{extracted_text}\n\n"
                
                # 一時ファイルを削除
                os.unlink(temp_file_path)
            except ImportError:
                # PDF2Image or Tesseractがインストールされていない
                pass
        
        # 結果をフォーマット
        if not text_content.strip() or page_count == 0:
            return f"PDFからテキストを抽出できませんでした。このPDFはスキャン画像のみで、テキストレイヤーを持っていない可能性があります。OCRを試すには、pytesserartとpdf2imageをインストールしてください。"
        
        # 結果をフォーマット
        result = f"## PDFから抽出されたテキスト\n"
        result += f"ソース: {url}\n"
        result += f"抽出ページ数: {page_count}ページ\n\n"
        result += "### 内容\n\n"
        result += text_content
        
        # 長すぎる場合は切り詰める
        max_length = 15000
        if len(result) > max_length:
            result = result[:max_length] + f"\n\n... (抽出されたテキストが長すぎるため切り詰められました。全体で{len(text_content)}文字)"
        
        return result
    
    except Exception as e:
        return f"PDFテキスト抽出中にエラー: {str(e)}"
    
@tool(
    name="codeact_auto_debug",
    description="コードの自動デバッグと修正",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "デバッグするコード"},
            "error_message": {"type": "string", "description": "発生したエラーメッセージ"},
            "container_id": {"type": "string", "description": "（オプション）既存コンテナID"}
        },
        "required": ["code", "error_message"]
    }
)
def codeact_auto_debug(code: str, error_message: str, container_id: Optional[str] = None):
    """
    コードのエラーを分析して修正する自動デバッガー。
    
    Args:
        code: エラーのあるコード
        error_message: 発生したエラーメッセージ
        container_id: コンテナID
    
    Returns:
        デバッグ結果と修正されたコード
    """
    logger.info(f"自動デバッグ開始: エラーメッセージ長さ {len(error_message)}")
    
    # 元のコードを保存
    original_code = code
    
    # エラータイプの分析ロジック
    debug_comments = []
    fixes_applied = []
    
    # エラータイプの判別と修正の適用
    if "SyntaxError" in error_message:
        code, comments, fixes = _fix_syntax_errors(code, error_message)
        debug_comments.extend(comments)
        fixes_applied.extend(fixes)
    elif "NameError" in error_message:
        code, comments, fixes = _fix_name_errors(code, error_message)
        debug_comments.extend(comments)
        fixes_applied.extend(fixes)
    elif "ImportError" in error_message or "ModuleNotFoundError" in error_message:
        code, comments, fixes = _fix_import_errors(code, error_message)
        debug_comments.extend(comments)
        fixes_applied.extend(fixes)
    elif "TypeError" in error_message:
        code, comments, fixes = _fix_type_errors(code, error_message)
        debug_comments.extend(comments)
        fixes_applied.extend(fixes)
    elif "IndexError" in error_message or "KeyError" in error_message:
        code, comments, fixes = _fix_index_key_errors(code, error_message)
        debug_comments.extend(comments)
        fixes_applied.extend(fixes)
    
    # 修正したコードの実行テスト
    if fixes_applied:
        logger.info(f"修正適用: {', '.join(fixes_applied)}")
        debug_comments_str = "\n".join(debug_comments)
        code_with_comments = f"{debug_comments_str}\n\n{code}"
        
        # 修正したコードを実行
        sandbox = get_sandbox()
        stdout, stderr, exit_code = sandbox.execute_python(container_id or "codeact-debug", code)
        
        if exit_code == 0:
            return f"コード修正成功！\n\n適用した修正: {', '.join(fixes_applied)}\n\n修正後のコード:\n{code_with_comments}\n\n実行結果:\n{stdout}"
        else:
            return f"コード修正を試みましたが、まだエラーがあります:\n\n{stderr}\n\n部分的に修正されたコード:\n{code_with_comments}"
    
    # LLMに修正を依頼する
    if not fixes_applied:
        return _request_llm_code_fix(original_code, error_message, container_id)
    
    return f"コード分析完了しましたが、自動修正できません。エラーメッセージを確認してください:\n{error_message}"

def _fix_syntax_errors(code: str, error_message: str) -> Tuple[str, List[str], List[str]]:
    """
    構文エラーを修正する
    
    Args:
        code: コード
        error_message: エラーメッセージ
        
    Returns:
        修正されたコード、デバッグコメント、適用された修正のリスト
    """
    debug_comments = []
    fixes_applied = []
    
    # 文字列リテラルが閉じられていない問題を解決
    if "EOL while scanning string literal" in error_message:
        debug_comments.append("# 文字列リテラルが閉じられていません")
        
        # 行番号を取得
        line_match = re.search(r"line (\d+)", error_message)
        if line_match:
            line_num = int(line_match.group(1))
            lines = code.split('\n')
            
            if 0 < line_num <= len(lines):
                problem_line = lines[line_num - 1]
                
                # シングルクォートかダブルクォートかを判断
                if "'" in problem_line and problem_line.count("'") % 2 == 1:
                    lines[line_num - 1] = problem_line + "'"
                    fixes_applied.append("閉じていないシングルクォートを追加")
                elif '"' in problem_line and problem_line.count('"') % 2 == 1:
                    lines[line_num - 1] = problem_line + '"'
                    fixes_applied.append("閉じていないダブルクォートを追加")
                
                code = '\n'.join(lines)
    
    # インデントエラーを修正
    elif "unexpected indent" in error_message or "expected an indented block" in error_message:
        debug_comments.append("# インデントエラーがあります")
        
        line_match = re.search(r"line (\d+)", error_message)
        if line_match:
            line_num = int(line_match.group(1))
            lines = code.split('\n')
            
            if 0 < line_num <= len(lines):
                # インデントの問題がある行
                current_line = lines[line_num - 1]
                prev_line = lines[line_num - 2] if line_num > 1 else ""
                
                # インデントレベルを調整
                if "unexpected indent" in error_message:
                    # インデントが多すぎる場合はタブスペースを減らす
                    current_indent = len(current_line) - len(current_line.lstrip())
                    prev_indent = len(prev_line) - len(prev_line.lstrip())
                    
                    if current_indent > prev_indent:
                        # 前の行と同じインデントに修正
                        lines[line_num - 1] = ' ' * prev_indent + current_line.lstrip()
                        fixes_applied.append("過剰なインデントを修正")
                
                elif "expected an indented block" in error_message:
                    # インデントが足りない場合はタブスペースを追加
                    current_indent = len(current_line) - len(current_line.lstrip())
                    if prev_line.strip().endswith(':'):
                        # コロンの後は4スペースインデント追加
                        lines[line_num - 1] = ' ' * (current_indent + 4) + current_line.lstrip()
                        fixes_applied.append("足りないインデントを追加")
                
                code = '\n'.join(lines)
    
    # 対応する括弧の閉じ忘れ
    elif "unexpected EOF while parsing" in error_message:
        debug_comments.append("# 括弧が閉じられていない可能性があります")
        
        # 括弧カウントを確認
        open_parentheses = code.count('(')
        close_parentheses = code.count(')')
        open_brackets = code.count('[')
        close_brackets = code.count(']')
        open_braces = code.count('{')
        close_braces = code.count('}')
        
        # 括弧不足を追加
        if open_parentheses > close_parentheses:
            code += ')' * (open_parentheses - close_parentheses)
            fixes_applied.append(f"閉じ括弧 ) を {open_parentheses - close_parentheses} 個追加")
        if open_brackets > close_brackets:
            code += ']' * (open_brackets - close_brackets)
            fixes_applied.append(f"閉じ括弧 ] を {open_brackets - close_brackets} 個追加")
        if open_braces > close_braces:
            code += '}' * (open_braces - close_braces)
            fixes_applied.append(f"閉じ括弧 }} を {open_braces - close_braces} 個追加")
    
    return code, debug_comments, fixes_applied

def _fix_name_errors(code: str, error_message: str) -> Tuple[str, List[str], List[str]]:
    """
    名前エラーを修正する
    
    Args:
        code: コード
        error_message: エラーメッセージ
        
    Returns:
        修正されたコード、デバッグコメント、適用された修正のリスト
    """
    debug_comments = []
    fixes_applied = []
    
    # 'X' is not defined エラーの修正
    name_match = re.search(r"name '(.+)' is not defined", error_message)
    if name_match:
        var_name = name_match.group(1)
        debug_comments.append(f"# 変数 '{var_name}' が定義されていません")
        
        # 組み込み関数/モジュールの誤字修正
        common_builtins = {
            'prit': 'print',
            'lne': 'len',
            'ragne': 'range',
            'iput': 'input',
            'mian': 'main',
            'strig': 'string',
            'flase': 'False',
            'ture': 'True',
            'noe': 'None'
        }
        
        # 変数名が誤字の場合、修正
        if var_name.lower() in common_builtins:
            correct_name = common_builtins[var_name.lower()]
            code = re.sub(r'\b' + re.escape(var_name) + r'\b', correct_name, code)
            fixes_applied.append(f"誤字を修正: {var_name} → {correct_name}")
            return code, debug_comments, fixes_applied
        
        # インポートの追加
        common_modules = {
            'pd': 'import pandas as pd',
            'np': 'import numpy as np',
            'plt': 'import matplotlib.pyplot as plt',
            'os': 'import os',
            're': 'import re',
            'json': 'import json',
            'requests': 'import requests',
            'math': 'import math',
            'datetime': 'from datetime import datetime'
        }
        
        if var_name in common_modules:
            import_line = common_modules[var_name]
            code = import_line + '\n\n' + code
            fixes_applied.append(f"インポート追加: {import_line}")
            return code, debug_comments, fixes_applied
        
        # 未定義の変数に初期値を設定
        # 特定のパターンに対応するダミー値を割り当て
        if var_name.lower().endswith(('list', 'array', 'items', 'elements')):
            code = f"{var_name} = []\n" + code
            fixes_applied.append(f"空リストを初期化: {var_name} = []")
        elif var_name.lower().endswith(('dict', 'map', 'mapping')):
            code = f"{var_name} = {{}}\n" + code
            fixes_applied.append(f"空辞書を初期化: {var_name} = {{}}")
        elif var_name.lower().endswith(('str', 'string', 'text', 'name')):
            code = f"{var_name} = ''\n" + code
            fixes_applied.append(f"空文字列を初期化: {var_name} = ''")
        elif var_name.lower().endswith(('num', 'count', 'index', 'i', 'j')):
            code = f"{var_name} = 0\n" + code
            fixes_applied.append(f"数値を初期化: {var_name} = 0")
        else:
            code = f"{var_name} = None  # 自動修正で追加\n" + code
            fixes_applied.append(f"変数を初期化: {var_name} = None")
    
    return code, debug_comments, fixes_applied

def _fix_import_errors(code: str, error_message: str) -> Tuple[str, List[str], List[str]]:
    """
    インポートエラーを修正する
    
    Args:
        code: コード
        error_message: エラーメッセージ
        
    Returns:
        修正されたコード、デバッグコメント、適用された修正のリスト
    """
    debug_comments = []
    fixes_applied = []
    
    # モジュールインポートエラーの修正
    module_match = re.search(r"No module named '(.+)'", error_message)
    if module_match:
        module_name = module_match.group(1)
        debug_comments.append(f"# モジュール '{module_name}' がインストールされていません")
        
        # 誤字修正
        common_typos = {
            'padas': 'pandas',
            'nummpy': 'numpy',
            'matplolib': 'matplotlib',
            'sicpy': 'scipy',
            'sklearn': 'scikit-learn',
            'beautifulsop': 'beautifulsoup4',
            'requets': 'requests'
        }
        
        if module_name in common_typos:
            correct_name = common_typos[module_name]
            code = code.replace(f"import {module_name}", f"import {correct_name}")
            code = code.replace(f"from {module_name}", f"from {correct_name}")
            fixes_applied.append(f"モジュール名の誤字を修正: {module_name} → {correct_name}")
            
            # pip installコメントを追加
            debug_comments.append(f"# 注: '{correct_name}' が必要な場合は pip install {correct_name} でインストール")
        else:
            # インストールコメントを追加
            debug_comments.append(f"# 注: '{module_name}' が必要な場合は pip install {module_name} でインストール")
            
            # 代替モジュールの提案
            if module_name == 'pandas':
                debug_comments.append("# 代替: 基本的なCSV処理にはcsv標準モジュールを使用できます")
                fixes_applied.append("pandasの代わりにcsvモジュールを提案")
            elif module_name == 'numpy':
                debug_comments.append("# 代替: 単純な数値計算ならmathモジュールを使用できます")
                fixes_applied.append("numpyの代わりにmathモジュールを提案")
            elif module_name == 'matplotlib':
                debug_comments.append("# 代替: データ出力には標準ライブラリの出力機能を使用できます")
                fixes_applied.append("matplotlibの代わりに標準出力を提案")
    
    # 名前インポートエラーの修正
    import_name_match = re.search(r"cannot import name '(.+)' from '(.+)'", error_message)
    if import_name_match:
        name = import_name_match.group(1)
        module = import_name_match.group(2)
        debug_comments.append(f"# モジュール '{module}' から '{name}' をインポートできません")
        
        # 一般的な修正
        common_fixes = {
            ('pyplot', 'matplotlib'): 'from matplotlib import pyplot',
            ('DataFrame', 'pandas'): 'from pandas import DataFrame',
            ('train_test_split', 'sklearn'): 'from sklearn.model_selection import train_test_split'
        }
        
        fix_key = (name, module)
        if fix_key in common_fixes:
            correct_import = common_fixes[fix_key]
            # 元のインポート文を探して置き換え
            import_pattern = rf"from\s+{re.escape(module)}\s+import\s+.*{re.escape(name)}"
            if re.search(import_pattern, code):
                code = re.sub(import_pattern, correct_import, code)
            else:
                code = correct_import + '\n' + code
            fixes_applied.append(f"インポート文を修正: {correct_import}")
    
    return code, debug_comments, fixes_applied

def _fix_type_errors(code: str, error_message: str) -> Tuple[str, List[str], List[str]]:
    """
    型エラーを修正する
    
    Args:
        code: コード
        error_message: エラーメッセージ
        
    Returns:
        修正されたコード、デバッグコメント、適用された修正のリスト
    """
    debug_comments = []
    fixes_applied = []
    
    # 'X' is not callable エラーの修正
    not_callable_match = re.search(r"'(.+)' object is not callable", error_message)
    if not_callable_match:
        obj_name = not_callable_match.group(1)
        debug_comments.append(f"# '{obj_name}' オブジェクトは呼び出し可能ではありません")
        
        # 関数名と変数名の混同チェック
        # 例: `list = [1, 2, 3]` の後に `list(x)` を呼ぶ
        if obj_name in ['list', 'dict', 'int', 'str', 'set', 'tuple']:
            # 変数名を変更
            var_pattern = rf"{obj_name}\s*="
            if re.search(var_pattern, code):
                new_var_name = f"my_{obj_name}"
                code = re.sub(var_pattern, f"{new_var_name} =", code)
                fixes_applied.append(f"組み込み型名の変数を改名: {obj_name} → {new_var_name}")
    
    # 'X' is not subscriptable エラーの修正
    not_subscriptable_match = re.search(r"'(.+)' object is not subscriptable", error_message)
    if not_subscriptable_match:
        obj_name = not_subscriptable_match.group(1)
        debug_comments.append(f"# '{obj_name}' オブジェクトはインデックス付け可能ではありません")
        
        # よくある間違い: intやNoneにインデックス付けしている
        if obj_name == 'int':
            debug_comments.append("# 数値型にはインデックス付けできません。リストや辞書を使う必要があります")
            fixes_applied.append("int型へのインデックス付けを特定")
        elif obj_name == 'NoneType':
            debug_comments.append("# None型にはインデックス付けできません。変数が初期化されているか確認してください")
            fixes_applied.append("None型へのインデックス付けを特定")
    
    # シーケンス結合エラーの修正
    concat_match = re.search(r"can only concatenate (.+) \(not \"(.+)\"\) to (.+)", error_message)
    if concat_match:
        type1 = concat_match.group(1)
        type2 = concat_match.group(2)
        debug_comments.append(f"# {type1}型と{type2}型を直接連結できません")
        
        # 文字列と数値の連結
        if (type1 == 'str' and type2 in ['int', 'float']) or (type1 in ['int', 'float'] and type2 == 'str'):
            # 文字列連結を + から f-stringまたはstr()に変更
            # 正確なコード箇所を特定できないので、コメントで提案
            debug_comments.append("# 修正案: 数値を文字列に変換してから連結する")
            debug_comments.append("# 例: value + 5  →  value + str(5) または f\"{value}{5}\"")
            fixes_applied.append("型変換による連結エラーの修正を提案")
    
    return code, debug_comments, fixes_applied

def _fix_index_key_errors(code: str, error_message: str) -> Tuple[str, List[str], List[str]]:
    """
    インデックスまたはキーエラーを修正する
    
    Args:
        code: コード
        error_message: エラーメッセージ
        
    Returns:
        修正されたコード、デバッグコメント、適用された修正のリスト
    """
    debug_comments = []
    fixes_applied = []
    
    # インデックスエラーを修正
    if "IndexError: list index out of range" in error_message:
        debug_comments.append("# リストのインデックスが範囲外です")
        debug_comments.append("# 修正案: アクセス前にリストの長さをチェックする")
        debug_comments.append("# 例: if i < len(my_list): value = my_list[i]")
        fixes_applied.append("インデックスチェックを提案")
    
    # キーエラーを修正
    key_match = re.search(r"KeyError: '(.+)'", error_message)
    if key_match:
        key_name = key_match.group(1)
        debug_comments.append(f"# 辞書にキー '{key_name}' が存在しません")
        debug_comments.append(f"# 修正案: 辞書アクセス前にキーの存在をチェックする")
        debug_comments.append(f"# 例: if '{key_name}' in my_dict: value = my_dict['{key_name}']")
        debug_comments.append(f"# または: value = my_dict.get('{key_name}', default_value)")
        fixes_applied.append("キー存在チェックと.getメソッドの使用を提案")
    
    return code, debug_comments, fixes_applied

def _request_llm_code_fix(code: str, error_message: str, container_id: Optional[str] = None) -> str:
    """
    LLMにコード修正を依頼する
    
    Args:
        code: 修正前コード
        error_message: エラーメッセージ
        container_id: コンテナID
        
    Returns:
        修正結果の説明
    """
    from config import CONFIG
    
    try:
        # LLMクライアントを取得
        from llm.azure_openai_client import AzureOpenAIClient
        llm_client = AzureOpenAIClient()
        
        # 構造化出力を要求するシステムプロンプト
        system_prompt = """あなたはPythonデバッグの専門家です。エラーの原因を分析し、修正したコードを提供してください。
以下の形式で応答してください:

{
    "analysis": "エラーの原因と問題点の詳細な分析",
    "fixed_code": "修正されたPythonコード全体",
    "changes": "行った変更の説明"
}

必ず有効なJSONとして解析できるように応答してください。"""

        # LLMにコード修正を依頼するプロンプト
        prompt = f"""
以下のPythonコードでエラーが発生しました。エラーの原因を分析し、修正したコードを提供してください。

## 元のコード
{code}

## エラーメッセージ
{error_message}
"""
        
        # LLMの応答を取得
        response_text = llm_client.call_azure_openai(
            prompt=prompt,
            system_prompt=system_prompt,
            model=CONFIG["llm"]["model"],
            temperature=0.2,  # デバッグは低温度が適切
            max_tokens=2000
        )
        
        # JSONを抽出して解析
        import re
        import json
        
        # 応答からJSONを抽出
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if not json_match:
            return f"LLMは構造化された応答を返しませんでした。生の応答:\n\n{response_text}"
        
        try:
            response_data = json.loads(json_match.group(0))
            analysis = response_data.get("analysis", "分析情報なし")
            fixed_code = response_data.get("fixed_code", "")
            changes = response_data.get("changes", "変更点の説明なし")
            
            if not fixed_code:
                return f"LLMは修正コードを提供できませんでした。分析結果:\n\n{analysis}"
            
            # 修正されたコードをテスト実行
            if container_id:
                sandbox = get_sandbox()
                stdout, stderr, exit_code = sandbox.execute_python(container_id, fixed_code)
                
                if exit_code == 0:
                    return f"LLMによる修正が成功しました！\n\n【分析】\n{analysis}\n\n【変更点】\n{changes}\n\n【修正コード】\n{fixed_code}\n\n【実行結果】\n{stdout}"
                else:
                    return f"LLMは修正を試みましたが、まだエラーがあります:\n\n【エラー】\n{stderr}\n\n【分析】\n{analysis}\n\n【変更点】\n{changes}\n\n【提案されたコード】\n{fixed_code}"
            
            return f"LLMによる修正提案:\n\n【分析】\n{analysis}\n\n【変更点】\n{changes}\n\n【修正コード】\n{fixed_code}"
            
        except json.JSONDecodeError:
            return f"LLMの応答をJSONとして解析できませんでした。生の応答:\n\n{response_text}"
    
    except Exception as e:
        logger.error(f"LLMコード修正中にエラー: {str(e)}")
        return f"コード修正中にエラーが発生しました: {str(e)}\n\nエラーメッセージを確認して手動で修正することをお勧めします。"
