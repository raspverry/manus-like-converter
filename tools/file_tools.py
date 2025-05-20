# tools/file_tools.py
"""
ファイル操作を行うツール。
"""
import os
from core.logging_config import logger
import re
from tools.tool_registry import tool
from sandbox.sandbox import get_sandbox



@tool(
    name="file_read",
    description="ファイルを読み込む",
    parameters={
        "type": "object",
        "properties": {
            "file": {"type": "string"}
        },
        "required": ["file"]
    }
)
def file_read(file: str):
    if not os.path.exists(file):
        return f"ファイルが存在しません: {file}"
    try:
        with open(file, "r", encoding="utf-8") as f:
            content = f.read()
        return content
    except Exception as e:
        return f"読み込み失敗: {str(e)}"

@tool(
    name="file_write",
    description="ファイルに文字列を書き込み(上書き or 追記)",
    parameters={
        "type": "object",
        "properties": {
            "file": {"type": "string"},
            "content": {"type": "string"},
            "append": {"type": "boolean"}
        },
        "required": ["file", "content"]
    }
)
def file_write(file: str, content: str, append: bool = False):
    mode = "a" if append else "w"
    os.makedirs(os.path.dirname(file), exist_ok=True)
    try:
        with open(file, mode, encoding="utf-8") as f:
            f.write(content)
        action = "追記" if append else "上書き"
        return f"ファイル '{file}' に{action}完了"
    except Exception as e:
        return f"書き込み失敗: {str(e)}"

@tool(
    name="file_str_replace",
    description="ファイル内の文字列を置換する",
    parameters={
        "type": "object",
        "properties": {
            "file": {"type": "string"},
            "old_str": {"type": "string"},
            "new_str": {"type": "string"}
        },
        "required": ["file", "old_str", "new_str"]
    }
)
def file_str_replace(file: str, old_str: str, new_str: str):
    if not os.path.exists(file):
        return f"ファイルが存在しません: {file}"
    try:
        with open(file, "r", encoding="utf-8") as f:
            content = f.read()
        replaced = content.replace(old_str, new_str)
        with open(file, "w", encoding="utf-8") as f:
            f.write(replaced)
        return "置換完了"
    except Exception as e:
        return f"置換失敗: {str(e)}"

@tool(
    name="file_find_in_content",
    description="ファイル内容の中で正規表現検索",
    parameters={
        "type": "object",
        "properties": {
            "file": {"type": "string"},
            "regex": {"type": "string"}
        },
        "required": ["file", "regex"]
    }
)
def file_find_in_content(file: str, regex: str):
    if not os.path.exists(file):
        return f"ファイルが存在しません: {file}"
    try:
        pattern = re.compile(regex)
        matches = []
        with open(file, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                if pattern.search(line):
                    matches.append(f"{i}行目: {line.strip()}")
        if not matches:
            return "該当なし"
        return "\n".join(matches)
    except Exception as e:
        return f"検索失敗: {str(e)}"
