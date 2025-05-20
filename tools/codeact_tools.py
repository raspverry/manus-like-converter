# tools/codeact_tools.py
"""
強化されたCodeActツール: LLMがPythonコードを生成し、それをDockerサンドボックスで実行する。
Manusのようなエージェントシステムで、コードをアクションとして使用する「CodeAct」パラダイムを実装。
本番環境向けに強化された実装。
"""
from core.logging_config import logger
from typing import Optional, Dict, Any, List, Union
import json
import time
import os
import tempfile
import re
from tools.tool_registry import tool
from sandbox.sandbox import get_sandbox

# 環境設定
ALLOWED_MODULES = os.getenv("CODEACT_ALLOWED_MODULES", "os,pandas,numpy,matplotlib,requests,bs4,json,csv,re,math,datetime,time").split(",")
MAX_CODE_SIZE = int(os.getenv("CODEACT_MAX_CODE_SIZE", "50000"))  # 最大コードサイズ（文字数）
EXECUTION_TIMEOUT = int(os.getenv("CODEACT_EXECUTION_TIMEOUT", "300"))  # 最大実行時間（秒）

@tool(
    name="code_execute",
    description="LLMが生成したPythonコードをDockerサンドボックスで実行する",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "実行するPythonコード"},
            "container_id": {"type": "string", "description": "(オプション) 既存コンテナID"},
            "description": {"type": "string", "description": "(オプション) コードの目的説明"},
            "save_output": {"type": "boolean", "description": "(オプション) 出力を保存するかどうか"},
            "output_file": {"type": "string", "description": "(オプション) 出力を保存するファイル名"}
        },
        "required": ["code"]
    }
)
def code_execute(
    code: str, 
    container_id: Optional[str] = None, 
    description: Optional[str] = None,
    save_output: bool = False,
    output_file: Optional[str] = None
):
    """
    LLMが生成したPythonコードをDockerサンドボックスで実行します。
    
    Args:
        code: 実行するPythonコード
        container_id: (オプション) 既存のコンテナID。指定しない場合は「codeact-session」
        description: (オプション) コードの目的説明、ログ記録用
        save_output: (オプション) 標準出力をファイルに保存するかどうか
        output_file: (オプション) 出力を保存するファイル名
    
    Returns:
        実行結果を含む文字列
    """
    # コードサイズチェック
    if len(code) > MAX_CODE_SIZE:
        return f"エラー: コードが大きすぎます({len(code)}文字)。最大{MAX_CODE_SIZE}文字まで。"
    
    # 禁止モジュールのチェック
    if _has_forbidden_modules(code):
        return "エラー: 許可されていないモジュールをインポートしようとしています。"
    
    # セキュリティチェック
    if _has_security_issues(code):
        return "エラー: コードにセキュリティリスクがあります。禁止されている操作が含まれています。"
    
    description_text = f"目的: {description}" if description else "コード実行"
    logger.info(f"{description_text} - コード実行開始")
    
    # コード実行の準備
    container = container_id or "codeact-session"
    
    # ファイル出力設定
    output_capture = ""
    if save_output and output_file:
        # 出力をキャプチャする関数を追加
        code = f"""
import sys
import io

# 元の標準出力を保存
original_stdout = sys.stdout

# 出力をキャプチャするバッファを作成
output_buffer = io.StringIO()
sys.stdout = output_buffer

try:
    # ユーザーコードを実行
{_indent_code(code, 4)}
finally:
    # 標準出力を元に戻す
    sys.stdout = original_stdout
    
    # キャプチャした出力を保存
    with open('{output_file}', 'w', encoding='utf-8') as f:
        f.write(output_buffer.getvalue())
    
    # コンソールにも出力
    print(output_buffer.getvalue())
"""
    
    start_time = time.time()
    sandbox = get_sandbox()
    
    try:
        # コードを実行
        stdout, stderr, exit_code = sandbox.execute_python(container, code)
        
        # 実行時間の計算
        execution_time = time.time() - start_time
        
        # 結果の整形
        if stderr:
            logger.warning(f"コード実行でエラー発生 (終了コード: {exit_code}): {stderr[:100]}...")
            
            # エラーが発生した場合は自動修正を試みる
            if exit_code != 0:
                fixed_result = _try_fix_code(code, stderr, container)
                if fixed_result:
                    return fixed_result
            
            result = f"[実行時間: {execution_time:.2f}秒]\n\n[stdout]\n{stdout}\n\n[stderr]\n{stderr}\nExitCode: {exit_code}"
        else:
            logger.info(f"コード実行成功 (実行時間: {execution_time:.2f}秒)")
            result = f"[実行時間: {execution_time:.2f}秒]\n\n[stdout]\n{stdout}\nExitCode: {exit_code}"
        
        # 出力ファイルが作成された場合は通知
        if save_output and output_file:
            if os.path.exists(output_file):
                file_size = os.path.getsize(output_file)
                result += f"\n\n出力をファイル '{output_file}' に保存しました（サイズ: {file_size} バイト）"
            else:
                result += f"\n\n警告: 出力ファイル '{output_file}' が作成されませんでした。"
        
        return result
    
    except Exception as e:
        logger.error(f"コード実行中に例外発生: {str(e)}")
        return f"コード実行中にシステムエラーが発生しました: {str(e)}"

def _has_forbidden_modules(code: str) -> bool:
    """
    コードに禁止されているモジュールがあるかチェックします。
    
    Args:
        code: チェックするPythonコード
        
    Returns:
        禁止モジュールがある場合はTrue
    """
    # インポート文を検索
    import_pattern = r'(?:import|from)\s+([a-zA-Z0-9_]+)(?:\s+import|\s*$)'
    imports = re.findall(import_pattern, code)
    
    # 許可されているモジュールリスト
    for module in imports:
        if module not in ALLOWED_MODULES and not any(module.startswith(f"{allowed}.") for allowed in ALLOWED_MODULES):
            logger.warning(f"禁止モジュール検出: {module}")
            return True
    
    return False

def _has_security_issues(code: str) -> bool:
    """
    コードにセキュリティ問題があるかチェックします。
    
    Args:
        code: チェックするPythonコード
        
    Returns:
        セキュリティ問題がある場合はTrue
    """
    # 危険なパターンのリスト
    dangerous_patterns = [
        r'(__import__\s*\(\s*["\']os["\'].*system)',  # OSコマンド実行の迂回方法
        r'(eval\s*\(\s*input\s*\()',  # 入力のeval
        r'(subprocess\..*?(?:call|Popen|run).*?shell\s*=\s*True)',  # シェルを有効にしたサブプロセス
        r'(open\s*\(.+?["\']w["\'])',  # ファイル書き込み (codeact_tools内では許可しない)
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, code):
            return True
    
    return False

def _indent_code(code: str, spaces: int) -> str:
    """コードをインデントします"""
    indent = " " * spaces
    return indent + code.replace("\n", f"\n{indent}")

def _try_fix_code(code: str, error_message: str, container_id: str) -> Optional[str]:
    """
    コードのエラーを自動的に修正します。
    
    Args:
        code: 元のコード
        error_message: エラーメッセージ
        container_id: 実行コンテナID
        
    Returns:
        修正結果またはNone
    """
    # ここに簡単な自動修正ロジックを実装
    # モジュールのインポートエラー修正
    if "ModuleNotFoundError" in error_message:
        match = re.search(r"No module named '([^']+)'", error_message)
        if match:
            module_name = match.group(1)
            
            # コンテナ内でパッケージをインストール
            logger.info(f"必要なモジュール {module_name} をインストール中...")
            sandbox = get_sandbox()
            cmd = f"pip install {module_name} --user"
            stdout, stderr, exit_code = sandbox.execute_command(container_id, cmd)
            
            if exit_code == 0:
                # 再実行
                new_stdout, new_stderr, new_exit_code = sandbox.execute_python(container_id, code)
                
                if new_exit_code == 0:
                    return f"必要なモジュール {module_name} をインストールして実行しました！\n\n[stdout]\n{new_stdout}"
                else:
                    return f"モジュール {module_name} をインストールしましたが、まだエラーがあります：\n\n{new_stderr}"
    
    # インデントエラー修正
    if "IndentationError" in error_message:
        # サンドボックスで修正ツールを実行
        fix_code = f"""
import re

code = '''{code}'''
lines = code.split('\\n')
fixed_lines = []

for line in lines:
    # タブをスペースに変換
    fixed_line = line.replace('\\t', '    ')
    fixed_lines.append(fixed_line)

fixed_code = '\\n'.join(fixed_lines)
print(fixed_code)
"""
        sandbox = get_sandbox()
        stdout, stderr, exit_code = sandbox.execute_python(container_id, fix_code)
        
        if exit_code == 0 and stdout:
            # 修正コードを再実行
            new_stdout, new_stderr, new_exit_code = sandbox.execute_python(container_id, stdout)
            
            if new_exit_code == 0:
                return f"インデントを修正して実行しました！\n\n[stdout]\n{new_stdout}"
            else:
                return f"インデントを修正しましたが、まだエラーがあります：\n\n{new_stderr}"
    
    # 一般的な構文エラー修正を試みる
    if "SyntaxError" in error_message:
        # バランスの取れていない括弧を修正
        fix_code = f"""
code = '''{code}'''

# 括弧のバランスチェックと修正
brackets = {{'(': ')', '[': ']', '{{': '}}'}}
bracket_stack = []
lines = code.split('\\n')

for i, line in enumerate(lines):
    for char in line:
        if char in brackets.keys():
            bracket_stack.append((char, i))
        elif char in brackets.values():
            if bracket_stack and char == brackets[bracket_stack[-1][0]]:
                bracket_stack.pop()

# 閉じられていない括弧を修正
fixed_code = code
if bracket_stack:
    print(f"未閉じの括弧を修正します...")
    for bracket, _ in reversed(bracket_stack):
        fixed_code += brackets[bracket]

print(fixed_code)
"""
        sandbox = get_sandbox()
        stdout, stderr, exit_code = sandbox.execute_python(container_id, fix_code)
        
        if exit_code == 0 and stdout and stdout != code:
            # 修正コードを再実行
            new_stdout, new_stderr, new_exit_code = sandbox.execute_python(container_id, stdout)
            
            if new_exit_code == 0:
                return f"構文エラーを修正して実行しました！\n\n[stdout]\n{new_stdout}"
    
    # 自動修正できなかった場合
    return None

@tool(
    name="codeact_data_analysis",
    description="データ分析と処理のためのコードを実行します",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "実行するPythonコード"},
            "data_file": {"type": "string", "description": "分析対象のデータファイルパス"},
            "container_id": {"type": "string", "description": "(オプション) 既存コンテナID"},
            "output_format": {"type": "string", "enum": ["text", "json", "csv"], "description": "出力形式"},
            "generate_visualization": {"type": "boolean", "description": "可視化を生成するかどうか"}
        },
        "required": ["code", "data_file"]
    }
)
def codeact_data_analysis(
    code: str, 
    data_file: str, 
    container_id: Optional[str] = None,
    output_format: str = "text",
    generate_visualization: bool = False
):
    """
    データ分析と処理のためのコードを実行します。
    
    データファイルパスを指定して、pandas、numpy、matplotlib等のライブラリを使った
    データ分析コードを実行するために最適化されています。
    
    Args:
        code: 実行するPythonコード
        data_file: 分析対象のデータファイルパス
        container_id: 既存のコンテナID
        output_format: 出力形式（text, json, csv）
        generate_visualization: 可視化を生成するかどうか
        
    Returns:
        分析結果を含む文字列
    """
    # データファイルの存在確認
    if not os.path.exists(data_file):
        return f"エラー: 指定されたデータファイル '{data_file}' が存在しません。"
    
    # 可視化ファイルのパス設定
    image_path = ""
    if generate_visualization:
        # 一時ディレクトリに可視化ファイルを保存
        image_dir = os.path.dirname(data_file)
        image_filename = f"viz_{int(time.time())}.png"
        image_path = os.path.join(image_dir, image_filename)
    
    # 出力形式に応じたコード拡張
    if output_format == "json":
        enhanced_code = _prepare_json_output_code(code, data_file, image_path, generate_visualization)
    elif output_format == "csv":
        enhanced_code = _prepare_csv_output_code(code, data_file, image_path, generate_visualization)
    else:
        enhanced_code = _prepare_text_output_code(code, data_file, image_path, generate_visualization)
    
    # 分析実行のログ記録
    logger.info(f"データ分析を実行: {data_file}")
    
    # Dockerサンドボックスでコードを実行
    sandbox = get_sandbox()
    stdout, stderr, exit_code = sandbox.execute_python(container_id or "codeact-session", enhanced_code)
    
    # エラー処理
    if stderr and exit_code != 0:
        logger.warning(f"データ分析でエラー発生: {stderr[:100]}...")
        return f"データ分析エラー:\n\n[stdout]\n{stdout}\n\n[stderr]\n{stderr}\nExitCode: {exit_code}"
    
    # 結果の整形
    result = f"データ分析結果:\n\n{stdout}"
    
    # 可視化画像が作成されたか確認
    if generate_visualization and os.path.exists(image_path):
        result += f"\n\n可視化画像が '{image_path}' に保存されました。"
    
    return result

def _prepare_text_output_code(code: str, data_file: str, image_path: str, generate_visualization: bool) -> str:
    """テキスト出力用のコードを準備"""
    visualization_code = ""
    if generate_visualization and image_path:
        visualization_code = f"""
# プロットを画像ファイルに保存
import matplotlib.pyplot as plt
plt.savefig('{image_path}', dpi=300, bbox_inches='tight')
print(f"可視化を '{image_path}' に保存しました")
"""

    return f"""
# 必要なライブラリをインポート
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import os
import json
import sys
import traceback

# データファイルパスを設定
DATA_FILE = "{data_file}"

# データ形式を自動判定
data_ext = os.path.splitext(DATA_FILE)[1].lower()

# 分析メイン処理
try:
    # データ読み込み
    if data_ext == '.csv':
        df = pd.read_csv(DATA_FILE)
    elif data_ext in ['.xlsx', '.xls']:
        df = pd.read_excel(DATA_FILE)
    elif data_ext == '.json':
        df = pd.read_json(DATA_FILE)
    elif data_ext == '.tsv' or data_ext == '.txt':
        df = pd.read_csv(DATA_FILE, sep='\\t')
    else:
        print(f"未対応のファイル形式: {{data_ext}}")
        df = pd.read_csv(DATA_FILE, sep=None, engine='python')  # 区切り文字自動検出
    
    # データファイル情報
    print(f"データファイル: {{DATA_FILE}}")
    print(f"行数: {{len(df)}}, 列数: {{len(df.columns)}}")
    print(f"列名: {{list(df.columns)}}")
    print("\\n基本統計情報:")
    print(df.describe())
    
    # ユーザーコードを実行
    print("\\n分析実行:")
    {_indent_code(code, 4)}
    
    {visualization_code}
    
except Exception as e:
    print(f"エラーが発生しました: {{str(e)}}")
    traceback.print_exc()
"""

def _prepare_json_output_code(code: str, data_file: str, image_path: str, generate_visualization: bool) -> str:
    """JSON出力用のコードを準備"""
    visualization_code = ""
    if generate_visualization and image_path:
        visualization_code = f"""
# プロットを画像ファイルに保存
import matplotlib.pyplot as plt
plt.savefig('{image_path}', dpi=300, bbox_inches='tight')
viz_saved_path = '{image_path}'
"""

    return f"""
# 必要なライブラリをインポート
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import os
import json
import sys
import traceback
import io

# キャプチャ用の文字列バッファを作成
output_buffer = io.StringIO()
sys.stdout = output_buffer

# データファイルパスを設定
DATA_FILE = "{data_file}"

# データ形式を自動判定
data_ext = os.path.splitext(DATA_FILE)[1].lower()

# 分析結果
result = {{"success": False, "data": {{}}, "visualization": None, "error": None}}

# 分析メイン処理
try:
    # データ読み込み
    if data_ext == '.csv':
        df = pd.read_csv(DATA_FILE)
    elif data_ext in ['.xlsx', '.xls']:
        df = pd.read_excel(DATA_FILE)
    elif data_ext == '.json':
        df = pd.read_json(DATA_FILE)
    elif data_ext == '.tsv' or data_ext == '.txt':
        df = pd.read_csv(DATA_FILE, sep='\\t')
    else:
        df = pd.read_csv(DATA_FILE, sep=None, engine='python')  # 区切り文字自動検出
    
    # データファイル情報
    result["data"]["file_info"] = {{
        "path": DATA_FILE,
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": list(df.columns)
    }}
    
    # 基本統計情報
    result["data"]["summary"] = json.loads(df.describe().to_json())
    
    # ユーザーコードを実行
    {_indent_code(code, 4)}
    
    {visualization_code}
    if 'viz_saved_path' in locals():
        result["visualization"] = viz_saved_path
    
    result["success"] = True
    
except Exception as e:
    result["error"] = {{"message": str(e), "traceback": traceback.format_exc()}}

# 標準出力を元に戻す
sys.stdout = sys.__stdout__

# 結果をJSON形式で出力
result["output"] = output_buffer.getvalue()
print(json.dumps(result, indent=2))
"""

def _prepare_csv_output_code(code: str, data_file: str, image_path: str, generate_visualization: bool) -> str:
    """CSV出力用のコードを準備"""
    visualization_code = ""
    if generate_visualization and image_path:
        visualization_code = f"""
# プロットを画像ファイルに保存
import matplotlib.pyplot as plt
plt.savefig('{image_path}', dpi=300, bbox_inches='tight')
print(f"可視化を '{image_path}' に保存しました")
"""

    return f"""
# 必要なライブラリをインポート
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import os
import json
import sys
import traceback
import io

# データファイルパスを設定
DATA_FILE = "{data_file}"

# データ形式を自動判定
data_ext = os.path.splitext(DATA_FILE)[1].lower()

# 分析メイン処理
try:
    # データ読み込み
    if data_ext == '.csv':
        df = pd.read_csv(DATA_FILE)
    elif data_ext in ['.xlsx', '.xls']:
        df = pd.read_excel(DATA_FILE)
    elif data_ext == '.json':
        df = pd.read_json(DATA_FILE)
    elif data_ext == '.tsv' or data_ext == '.txt':
        df = pd.read_csv(DATA_FILE, sep='\\t')
    else:
        print(f"未対応のファイル形式: data_ext")
        df = pd.read_csv(DATA_FILE, sep=None, engine='python')  # 区切り文字自動検出
    
    # データファイル情報
    print(f"# データファイル: {{DATA_FILE}}")
    print(f"# 行数: {{len(df)}}, 列数: {{len(df.columns)}}")
    print(f"# 列名: {{list(df.columns)}}")
    
    # ユーザーコードを実行
    {{_indent_code(code, 4)}}
    
    {{visualization_code}}
    
    # もし分析結果がデータフレームの場合、CSV形式で出力
    result_vars = [var for var in dir() if not var.startswith('_') and var not in ['df', 'DATA_FILE', 'data_ext', 'Path', 'os', 'json', 'sys', 'traceback', 'io', 'pd', 'np', 'plt']]
    for var_name in result_vars:
        var = locals()[var_name]
        if isinstance(var, pd.DataFrame):
            print(f"\\n# 分析結果: {{var_name}}")
            print(var.to_csv(index=True))
    
except Exception as e:
    print(f"エラーが発生しました: {{str(e)}}")
    traceback.print_exc()
"""

@tool(
    name="codeact_auto_debug",
    description="コードの自動デバッグと修正",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "デバッグするコード"},
            "error_message": {"type": "string", "description": "発生したエラーメッセージ"},
            "container_id": {"type": "string", "description": "（オプション）既存コンテナID"},
            "max_attempts": {"type": "integer", "description": "最大修正試行回数"}
        },
        "required": ["code", "error_message"]
    }
)
def codeact_auto_debug(
    code: str, 
    error_message: str, 
    container_id: Optional[str] = None,
    max_attempts: int = 3
):
    """
    コードのエラーを分析して修正する自動デバッガー。
    
    Args:
        code: エラーのあるコード
        error_message: 発生したエラーメッセージ
        container_id: コンテナID
        max_attempts: 最大修正試行回数
    
    Returns:
        デバッグ結果と修正されたコード
    """
    logger.info(f"自動デバッグ開始: エラーメッセージ長さ {len(error_message)}")
    
    # 元のコードを保存
    original_code = code
    
    # コンテナID設定
    container = container_id or "codeact-debug"
    
    # エラータイプの解析
    error_type = _analyze_error_type(error_message)
    logger.info(f"エラータイプ: {error_type}")
    
    # エラータイプ別の修正関数マッピング
    error_fixers = {
        "SyntaxError": _fix_syntax_error,
        "IndentationError": _fix_indentation_error,
        "NameError": _fix_name_error,
        "ImportError": _fix_import_error,
        "ModuleNotFoundError": _fix_module_not_found,
        "TypeError": _fix_type_error,
        "IndexError": _fix_index_error,
        "KeyError": _fix_key_error,
        "AttributeError": _fix_attribute_error,
        "FileNotFoundError": _fix_file_not_found,
        "ZeroDivisionError": _fix_zero_division,
        "ValueError": _fix_value_error,
        "UnboundLocalError": _fix_unbound_local_error
    }
    
    # 該当するエラー修正機能を使用
    if error_type in error_fixers:
        fixed_code, success = error_fixers[error_type](code, error_message, container)
        if success:
            # 修正コードをテスト
            sandbox = get_sandbox()
            stdout, stderr, exit_code = sandbox.execute_python(container, fixed_code)
            
            if exit_code == 0:
                # 修正成功
                return f"エラータイプ {error_type} を自動修正しました！\n\n修正後のコード:\n{fixed_code}\n\n実行結果:\n{stdout}"
            else:
                # まだエラーがある場合は再帰的に修正を試みる
                if max_attempts > 1:
                    return codeact_auto_debug(fixed_code, stderr, container, max_attempts - 1)
                else:
                    return
                

def _analyze_error_type(error_message: str) -> str:
    """エラーメッセージからエラータイプを抽出"""
    # 一般的なエラータイプのパターン
    error_patterns = [
        "SyntaxError", "IndentationError", "TabError", "NameError", "TypeError",
        "ValueError", "AttributeError", "ImportError", "ModuleNotFoundError",
        "IndexError", "KeyError", "FileNotFoundError", "ZeroDivisionError",
        "PermissionError", "OSError", "IOError", "RuntimeError", "UnboundLocalError"
    ]
    
    for error_type in error_patterns:
        if error_type in error_message:
            return error_type
    
    return "Unknown"

def _fix_syntax_error(code: str, error_message: str, container_id: str):
    """構文エラーの修正を試みる"""
    # 括弧のバランスをチェック・修正
    def fix_brackets(code):
        stack = []
        bracket_pairs = {')': '(', '}': '{', ']': '['}
        fixed_code = ""
        error_pos = -1
        
        # エラー行と位置を抽出
        match = re.search(r'line (\d+)', error_message)
        if match:
            error_line = int(match.group(1))
            lines = code.split('\n')
            line_pos = 0
            for i in range(error_line - 1):
                if i < len(lines):
                    line_pos += len(lines[i]) + 1
            
            pos_match = re.search(r'position (\d+)', error_message)
            if pos_match:
                error_pos = line_pos + int(pos_match.group(1))
        
        # 括弧のバランスを修正
        for i, char in enumerate(code):
            fixed_code += char
            if char in '({[':
                stack.append(char)
            elif char in ')}]':
                if not stack:  # 閉じ括弧が余分
                    if i == error_pos:
                        fixed_code = fixed_code[:-1]  # 余分な閉じ括弧を削除
                elif stack[-1] == bracket_pairs[char]:
                    stack.pop()
                else:  # 括弧の不一致
                    if i == error_pos:
                        fixed_code = fixed_code[:-1] + bracket_pairs[char]
        
        # 閉じ忘れ括弧の追加
        for char in reversed(stack):
            if char == '(': fixed_code += ')'
            elif char == '{': fixed_code += '}'
            elif char == '[': fixed_code += ']'
        
        return fixed_code
    
    # 文字列リテラルの閉じ忘れを修正
    def fix_string_literals(code):
        lines = code.split('\n')
        fixed_lines = []
        
        for line in lines:
            fixed_line = line
            # 文字列リテラルの数をカウント
            single_quotes = line.count("'")
            double_quotes = line.count('"')
            
            # 奇数個の場合、閉じていない
            if single_quotes % 2 == 1:
                fixed_line += "'"
            if double_quotes % 2 == 1:
                fixed_line += '"'
                
            fixed_lines.append(fixed_line)
        
        return '\n'.join(fixed_lines)
    
    # コロンの欠落を修正
    def fix_missing_colon(code):
        lines = code.split('\n')
        fixed_lines = []
        
        # エラー行を特定
        line_match = re.search(r'line (\d+)', error_message)
        if line_match:
            error_line = int(line_match.group(1)) - 1
            if 0 <= error_line < len(lines):
                # if, for, while, def, class, with, try, except, finally, else, elif
                # に対応する行で、:が欠けている場合は追加
                patterns = [
                    r'^(\s*(?:if|for|while|def|class|with|try|except|finally|else|elif).*[^\s:])$'
                ]
                for pattern in patterns:
                    match = re.match(pattern, lines[error_line])
                    if match:
                        lines[error_line] = match.group(1) + ':'
                        break
        
        return '\n'.join(lines)
    
    # 複数の修正方法を試す
    fixed_code = code
    fixed_code = fix_brackets(fixed_code)
    fixed_code = fix_string_literals(fixed_code)
    fixed_code = fix_missing_colon(fixed_code)
    
    # 修正前と後で違いがあるかチェック
    if fixed_code != code:
        return fixed_code, True
    
    # 他の構文エラーへの対処
    if "EOL while scanning string literal" in error_message:
        # 文字列リテラルの終了が欠けている
        pass  # すでに処理済み
    elif "unexpected EOF while parsing" in error_message:
        # ファイル終端での括弧の閉じ忘れ
        pass  # すでに処理済み
    elif "invalid syntax" in error_message:
        # 一般的な構文エラー
        line_match = re.search(r'line (\d+)', error_message)
        if line_match:
            line_num = int(line_match.group(1))
            # より複雑な構文修正ロジックをここに実装
    
    # 修正できなかった場合
    return code, False

def _fix_indentation_error(code: str, error_message: str, container_id: str):
    """インデント関連のエラーを修正"""
    lines = code.split('\n')
    fixed_lines = []
    
    # エラー行を特定
    line_match = re.search(r'line (\d+)', error_message)
    error_line = int(line_match.group(1)) - 1 if line_match else -1
    
    # タブとスペースの混在を修正
    for i, line in enumerate(lines):
        # タブをスペース4つに置換
        fixed_line = line.replace('\t', '    ')
        
        # エラー行の前後でインデントの一貫性をチェック
        if i == error_line:
            if "unexpected indent" in error_message and i > 0:
                # 前の行のインデントレベルを取得
                prev_indent = len(lines[i-1]) - len(lines[i-1].lstrip())
                curr_indent = len(fixed_line) - len(fixed_line.lstrip())
                
                # インデントが深すぎる場合は修正
                if curr_indent > prev_indent + 4:
                    fixed_line = ' ' * (prev_indent + 4) + fixed_line.lstrip()
            
            elif "expected an indented block" in error_message and i > 0:
                # 前の行がコロンで終わっている場合、インデントを追加
                if lines[i-1].rstrip().endswith(':'):
                    prev_indent = len(lines[i-1]) - len(lines[i-1].lstrip())
                    curr_indent = len(fixed_line) - len(fixed_line.lstrip())
                    
                    if curr_indent <= prev_indent:
                        fixed_line = ' ' * (prev_indent + 4) + fixed_line.lstrip()
        
        fixed_lines.append(fixed_line)
    
    fixed_code = '\n'.join(fixed_lines)
    return fixed_code, fixed_code != code

def _fix_name_error(code: str, error_message: str, container_id: str):
    """名前エラー（未定義変数）の修正"""
    # エラーメッセージから変数名を抽出
    match = re.search(r"name '([^']+)' is not defined", error_message)
    if not match:
        return code, False
    
    var_name = match.group(1)
    fixed_code = code
    
    # よくある間違いを修正
    common_typos = {
        'pint': 'print',
        'lenght': 'length',
        'lenght': 'len',
        'legnth': 'length',
        'legnth': 'len',
        'flase': 'False',
        'ture': 'True',
        'Ture': 'True',
        'Flase': 'False',
        'defualt': 'default',
        'Flase': 'False',
        'imoprt': 'import',
        'Fasle': 'False',
        'Ture': 'True',
        'nulll': 'null',
        'Nulll': 'None',
        'null': 'None',
        'Null': 'None',
        'nil': 'None',
        'Nil': 'None',
        'flaot': 'float',
        'boolen': 'bool',
        'booleen': 'bool',
        'booleean': 'bool',
        'Liste': 'List',
        'liste': 'list',
        'printt': 'print',
        'Flase': 'False',
        'fasle': 'False'
    }
    
    if var_name.lower() in common_typos:
        # よくあるタイプミスを修正
        correct_name = common_typos[var_name.lower()]
        fixed_code = re.sub(r'\b' + re.escape(var_name) + r'\b', correct_name, code)
        return fixed_code, True
    
    # モジュールのインポート忘れの可能性をチェック
    common_modules = {
        'np': 'import numpy as np',
        'pd': 'import pandas as pd',
        'plt': 'import matplotlib.pyplot as plt',
        're': 'import re',
        'os': 'import os',
        'sys': 'import sys',
        'json': 'import json',
        'math': 'import math',
        'datetime': 'from datetime import datetime',
        'time': 'import time',
        'random': 'import random'
    }
    
    if var_name in common_modules:
        # モジュールのインポート文を追加
        import_statement = common_modules[var_name]
        lines = fixed_code.split('\n')
        
        # 最初のインポート文の後に追加するか、ファイルの先頭に追加
        import_added = False
        for i, line in enumerate(lines):
            if line.startswith('import ') or line.startswith('from '):
                # 既存のインポート文の後に追加
                lines.insert(i + 1, import_statement)
                import_added = True
                break
        
        if not import_added:
            # ファイルの先頭に追加
            lines.insert(0, import_statement)
            if len(lines) > 1:
                lines.insert(1, '')  # 空行を追加
        
        fixed_code = '\n'.join(lines)
        return fixed_code, True
    
    # 他の一般的なエラーを修正
    lines = code.split('\n')
    pattern = re.compile(r'\b' + re.escape(var_name) + r'\b')
    
    # 初期化忘れの変数を検出して修正
    for i, line in enumerate(lines):
        if re.search(pattern, line) and "=" in line:
            # 変数への代入がある行を見つけた
            parts = line.split("=", 1)
            assigned_var = parts[0].strip()
            
            # 変数名が似ている場合、タイプミスの可能性
            if (var_name in assigned_var or assigned_var in var_name) and var_name != assigned_var:
                # タイプミスを修正
                fixed_line = re.sub(r'\b' + re.escape(var_name) + r'\b', assigned_var, line)
                lines[i] = fixed_line
                fixed_code = '\n'.join(lines)
                return fixed_code, True
    
    # 変数の宣言が見つからない場合、適切な初期化を追加
    var_type_hints = {
        'i': '0',
        'j': '0',
        'k': '0',
        'index': '0',
        'count': '0',
        'sum': '0',
        'total': '0',
        'result': '0',
        'lst': '[]',
        'arr': '[]',
        'array': '[]',
        'data': '[]',
        'items': '[]',
        'dict': '{}',
        'map': '{}',
        'results': '[]',
        'text': '""',
        'name': '""',
        'string': '""',
        'str': '""',
        'flag': 'False',
        'done': 'False'
    }
    
    # 変数名に基づいて適切な初期化を推測
    default_value = None
    for pattern, value in var_type_hints.items():
        if pattern in var_name.lower():
            default_value = value
            break
    
    if not default_value:
        if var_name.startswith(('is_', 'has_', 'can_', 'should_')):
            default_value = 'False'
        elif var_name.endswith(('_list', '_array', '_arr', '_items')):
            default_value = '[]'
        elif var_name.endswith(('_dict', '_map')):
            default_value = '{}'
        elif var_name.endswith(('_str', '_string', '_name', '_text')):
            default_value = '""'
        elif var_name.endswith(('_num', '_count', '_total', '_sum', '_index', '_i')):
            default_value = '0'
        else:
            default_value = 'None'
    
    # エラー行の直前に変数初期化を追加
    line_match = re.search(r'line (\d+)', error_message)
    if line_match:
        error_line = int(line_match.group(1)) - 1
        if 0 <= error_line < len(lines):
            indent = len(lines[error_line]) - len(lines[error_line].lstrip())
            indent_str = ' ' * indent
            lines.insert(error_line, f"{indent_str}{var_name} = {default_value}  # 自動追加された初期化")
            fixed_code = '\n'.join(lines)
            return fixed_code, True
    
    # エラー行が特定できない場合は、最初の出現の前に追加
    for i, line in enumerate(lines):
        if var_name in line and "=" not in line:
            indent = len(line) - len(line.lstrip())
            indent_str = ' ' * indent
            lines.insert(i, f"{indent_str}{var_name} = {default_value}  # 自動追加された初期化")
            fixed_code = '\n'.join(lines)
            return fixed_code, True
    
    return code, False

def _fix_import_error(code: str, error_message: str, container_id: str):
    """インポートエラーの修正"""
    # エラーメッセージから必要な情報を抽出
    module_match = re.search(r"No module named ['\"](.*?)['\"]", error_message)
    import_match = re.search(r"cannot import name ['\"](.*?)['\"]", error_message)
    
    if module_match:
        # モジュールがインストールされていない場合
        module_name = module_match.group(1)
        
        # モジュールをpipでインストールしてみる
        sandbox = get_sandbox()
        install_cmd = f"pip install {module_name} --user"
        stdout, stderr, exit_code = sandbox.execute_command(container_id, install_cmd)
        
        if exit_code == 0:
            # インストール成功
            return code, True
        else:
            # インストール失敗 - 一般的なモジュール名の間違いを修正
            common_typos = {
                'numpy': 'numpy',
                'np': 'numpy',
                'pd': 'pandas',
                'pandas': 'pandas',
                'matplotlib.pylab': 'matplotlib',
                'sklearn': 'scikit-learn',
                'bs4': 'beautifulsoup4',
                'beautifulsoup': 'beautifulsoup4',
                'bs': 'beautifulsoup4',
                'PIL': 'pillow',
                'Image': 'pillow',
                'cv2': 'opencv-python',
                'opencv': 'opencv-python',
                'tf': 'tensorflow',
                'torch': 'torch',
                'plt': 'matplotlib',
                'sns': 'seaborn',
                'requests': 'requests',
                'django': 'django',
                'flask': 'flask',
                'scipy': 'scipy'
            }
            
            if module_name in common_typos:
                correct_name = common_typos[module_name]
                install_cmd = f"pip install {correct_name} --user"
                stdout, stderr, exit_code = sandbox.execute_command(container_id, install_cmd)
                
                if exit_code == 0:
                    # インストール成功
                    # インポート文の修正
                    lines = code.split('\n')
                    for i, line in enumerate(lines):
                        if f"import {module_name}" in line:
                            if module_name != correct_name:
                                # 正しいモジュール名に置き換え
                                lines[i] = line.replace(module_name, correct_name)
                    
                    fixed_code = '\n'.join(lines)
                    return fixed_code, True
    
    if import_match:
        # モジュールの特定の機能をインポートできない場合
        name = import_match.module_name
        
        # よくあるインポートエラーの修正
        common_fixes = {
            'numpy': {
                'array': 'from numpy import array',
                'ndarray': 'from numpy import ndarray',
            },
            'pandas': {
                'DataFrame': 'from pandas import DataFrame',
                'Series': 'from pandas import Series',
            },
            'matplotlib.pyplot': {
                'plot': 'from matplotlib.pyplot import plot',
                'figure': 'from matplotlib.pyplot import figure',
            }
        }
        
        from_module_match = re.search(r"from (.*?) import", error_message)
        if from_module_match and name in common_fixes.get(from_module_match.group(1), {}):
            # 適切なインポート文に修正
            correct_import = common_fixes[from_module_match.group(1)][name]
            lines = code.split('\n')
            
            # 現在の間違ったインポート行を修正
            for i, line in enumerate(lines):
                if f"from {from_module_match.group(1)} import" in line and name in line:
                    lines[i] = correct_import
                    fixed_code = '\n'.join(lines)
                    return fixed_code, True
    
    return code, False

def _fix_module_not_found(code: str, error_message: str, container_id: str):
    """モジュールが見つからないエラーの修正"""
    # モジュール名を抽出
    match = re.search(r"No module named '([^']+)'", error_message)
    if not match:
        return code, False
    
    module_name = match.group(1)
    module_base = module_name.split('.')[0]
    
    # 一般的なパッケージ名のマッピング
    package_map = {
        'numpy': 'numpy',
        'np': 'numpy',
        'pandas': 'pandas',
        'pd': 'pandas',
        'matplotlib': 'matplotlib',
        'plt': 'matplotlib',
        'sklearn': 'scikit-learn',
        'tensorflow': 'tensorflow',
        'tf': 'tensorflow',
        'torch': 'torch',
        'cv2': 'opencv-python',
        'bs4': 'beautifulsoup4',
        'requests': 'requests',
        'PIL': 'pillow',
        'Image': 'pillow',
        'flask': 'flask',
        'django': 'django',
        'scipy': 'scipy',
        'sns': 'seaborn'
    }
    
    # 適切なパッケージ名を特定
    package_name = package_map.get(module_base, module_base)
    
    # サンドボックスでパッケージをインストール
    sandbox = get_sandbox()
    logger.info(f"パッケージのインストールを試行: {package_name}")
    
    install_cmd = f"pip install {package_name} --user"
    stdout, stderr, exit_code = sandbox.execute_command(container_id, install_cmd)
    
    if exit_code == 0:
        logger.info(f"パッケージ {package_name} のインストールに成功しました")
        return code, True
    else:
        logger.warning(f"パッケージ {package_name} のインストールに失敗: {stderr}")
        
        # よくある間違いの修正を試みる
        lines = code.split('\n')
        fixed_lines = []
        for line in lines:
            if f"import {module_name}" in line:
                if module_name in package_map and module_name != package_map[module_name]:
                    # モジュール名を修正
                    fixed_line = line.replace(module_name, package_map[module_name])
                    fixed_lines.append(fixed_line)
                    fixed_lines.append(f"# 注意: {module_name} ではなく {package_map[module_name]} を使用")
                    continue
            
            # よくある間違い: matplotlib.pyplotの代わりにmatplotlib.pylabなど
            if 'import matplotlib.pylab' in line:
                fixed_lines.append('import matplotlib.pyplot as plt  # 修正')
                continue
                
            # その他の修正ルール
                
            fixed_lines.append(line)
        
        fixed_code = '\n'.join(fixed_lines)
        if fixed_code != code:
            return fixed_code, True
    
    return code, False

def _fix_type_error(code: str, error_message: str, container_id: str):
    """型エラーの修正"""
    # エラーメッセージから情報を抽出
    # 例: "can't multiply sequence by non-int of type 'float'"
    # 例: "unsupported operand type(s) for +: 'int' and 'str'"
    
    # 数値と文字列の混合操作
    if "unsupported operand type(s) for" in error_message and "str" in error_message:
        # 行番号を抽出
        line_match = re.search(r"line (\d+)", error_message)
        if line_match:
            line_num = int(line_match.group(1))
            lines = code.split('\n')
            
            if 0 <= line_num - 1 < len(lines):
                line = lines[line_num - 1]
                
                # 数値と文字列の連結を検出して修正
                if "+" in line and not "++" in line:
                    parts = line.split("+")
                    new_parts = []
                    for part in parts:
                        part = part.strip()
                        # 数字のみの場合はstr()で囲む
                        if re.match(r'^\d+(\.\d+)?$', part):
                            new_parts.append(f"str({part})")
                        # 変数かもしれない場合
                        elif re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', part):
                            # 型を推測する必要があるが、ここでは単純化
                            new_parts.append(f"str({part})")
                        else:
                            new_parts.append(part)
                    
                    # 修正された行を構築
                    fixed_line = " + ".join(new_parts)
                    lines[line_num - 1] = fixed_line
                    fixed_code = '\n'.join(lines)
                    return fixed_code, True
    
    # リストやタプルのインデックスが整数でない
    if "sequence index must be integer" in error_message:
        line_match = re.search(r"line (\d+)", error_message)
        if line_match:
            line_num = int(line_match.group(1))
            lines = code.split('\n')
            
            if 0 <= line_num - 1 < len(lines):
                line = lines[line_num - 1]
                
                # インデックスを検出 (例: arr[1.5] -> arr[int(1.5)])
                index_match = re.search(r'(\w+)\[(.*?)\]', line)
                if index_match:
                    var_name = index_match.group(1)
                    index_expr = index_match.group(2)
                    
                    # 数値か数値っぽい変数の場合
                    if re.match(r'^[\d\.]+$', index_expr) or re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', index_expr):
                        fixed_line = line.replace(f"{var_name}[{index_expr}]", f"{var_name}[int({index_expr})]")
                        lines[line_num - 1] = fixed_line
                        fixed_code = '\n'.join(lines)
                        return fixed_code, True
    
    # その他のTypeError
    if "takes" in error_message and "positional argument" in error_message:
        # 引数の数が不一致
        pass
    
    return code, False

def _fix_index_error(code: str, error_message: str, container_id: str):
    """インデックスエラーの修正"""
    # "index out of range" などのエラーメッセージを検出
    if "index out of range" in error_message or "list index out of range" in error_message:
        line_match = re.search(r"line (\d+)", error_message)
        if line_match:
            line_num = int(line_match.group(1))
            lines = code.split('\n')
            
            if 0 <= line_num - 1 < len(lines):
                line = lines[line_num - 1]
                
                # インデックスアクセスを検出
                index_match = re.search(r'(\w+)\[([^\]]+)\]', line)
                if index_match:
                    var_name = index_match.group(1)
                    index_expr = index_match.group(2)
                    
                    # 簡単な修正: 範囲チェックを追加
                    indent = len(line) - len(line.lstrip())
                    indent_str = ' ' * indent
                    
                    # 修正コードを挿入
                    check_line = f"{indent_str}if {index_expr} < len({var_name}):"
                    fixed_line = f"{' ' * (indent + 4)}{line.strip()}"
                    else_line = f"{indent_str}else:"
                    warning_line = f"{' ' * (indent + 4)}print(f\"警告: インデックス {{{index_expr}}} が範囲外です (配列の長さ: {{{len(var_name)}}})\")"
                    
                    lines[line_num - 1] = check_line
                    lines.insert(line_num, fixed_line)
                    lines.insert(line_num + 1, else_line)
                    lines.insert(line_num + 2, warning_line)
                    
                    fixed_code = '\n'.join(lines)
                    return fixed_code, True
    
    return code, False

def _fix_key_error(code: str, error_message: str, container_id: str):
    """キーエラーの修正"""
    # "KeyError: 'key'" パターンを検出
    key_match = re.search(r"KeyError: ['\"]([^'\"]+)['\"]", error_message)
    if key_match:
        key_name = key_match.group(1)
        line_match = re.search(r"line (\d+)", error_message)
        
        if line_match:
            line_num = int(line_match.group(1))
            lines = code.split('\n')
            
            if 0 <= line_num - 1 < len(lines):
                line = lines[line_num - 1]
                
                # 辞書アクセスを検出
                dict_match = re.search(r'(\w+)\[(.*?)\]', line)
                if dict_match:
                    dict_name = dict_match.group(1)
                    
                    # get()メソッドを使用するように変更
                    indent = len(line) - len(line.lstrip())
                    indent_str = ' ' * indent
                    
                    # 行全体を置換するのではなく、特定の部分だけを置換
                    fixed_line = line.replace(
                        f"{dict_name}['{key_name}']", 
                        f"{dict_name}.get('{key_name}')"
                    ).replace(
                        f'{dict_name}["{key_name}"]', 
                        f'{dict_name}.get("{key_name}")'
                    ).replace(
                        f"{dict_name}[{key_name}]", 
                        f"{dict_name}.get({key_name})"
                    )
                    
                    # コメントを追加
                    fixed_line += "  # KeyErrorを避けるためにget()メソッドを使用"
                    
                    lines[line_num - 1] = fixed_line
                    fixed_code = '\n'.join(lines)
                    return fixed_code, True
    
    return code, False

def _fix_attribute_error(code: str, error_message: str, container_id: str):
    """属性エラーの修正"""
    # 'module' has no attribute 'X' パターンを検出
    attr_match = re.search(r"'([^']+)' object has no attribute '([^']+)'", error_message)
    module_match = re.search(r"module '([^']+)' has no attribute '([^']+)'", error_message)
    
    if attr_match:
        obj_type = attr_match.group(1)
        attr_name = attr_match.group(2)
        line_match = re.search(r"line (\d+)", error_message)
        
        if line_match:
            line_num = int(line_match.group(1))
            lines = code.split('\n')
            
            if 0 <= line_num - 1 < len(lines):
                line = lines[line_num - 1]
                
                # よくある属性の間違いを修正
                common_typos = {
                    'append': ['add', 'insert', 'push'],
                    'extend': ['concat', 'merge', 'join'],
                    'items': ['keys', 'values', 'elements'],
                    'shape': ['size', 'dimensions', 'dim'],
                    'columns': ['cols', 'column_names', 'fields'],
                    'index': ['indices', 'indexes', 'keys'],
                    'iloc': ['loc', 'ix', 'at'],
                    'imread': ['read', 'load_image', 'open_image'],
                    'savefig': ['save', 'save_plot', 'save_figure']
                }
                
                # 逆方向のマッピングを作成
                reverse_map = {}
                for correct, variants in common_typos.items():
                    for variant in variants:
                        reverse_map[variant] = correct
                
                # 属性名の修正
                if attr_name in reverse_map:
                    correct_attr = reverse_map[attr_name]
                    # 属性アクセスパターン検出
                    obj_match = re.search(r'(\w+)\.' + re.escape(attr_name), line)
                    if obj_match:
                        obj_name = obj_match.group(1)
                        fixed_line = line.replace(f"{obj_name}.{attr_name}", f"{obj_name}.{correct_attr}")
                        lines[line_num - 1] = fixed_line + f"  # 属性名を修正: {attr_name} -> {correct_attr}"
                        fixed_code = '\n'.join(lines)
                        return fixed_code, True
    
    if module_match:
        module_name = module_match.group(1)
        attr_name = module_match.group(2)
        
        # 一般的なモジュール属性の間違い
        module_attrs = {
            'numpy': {
                'array': 'numpy.array',
                'ndarray': 'numpy.ndarray',
                'Matrix': 'numpy.matrix',
                'random': 'numpy.random'
            },
            'pandas': {
                'dataframe': 'pandas.DataFrame',
                'series': 'pandas.Series',
                'read_excel': 'pandas.read_excel'
            },
            'matplotlib.pyplot': {
                'figure': 'matplotlib.pyplot.figure',
                'plot': 'matplotlib.pyplot.plot',
                'show': 'matplotlib.pyplot.show'
            }
        }
        
        if module_name in module_attrs and attr_name.lower() in [a.lower() for a in module_attrs[module_name]]:
            # 大文字小文字の違いを修正
            for correct_attr in module_attrs[module_name]:
                if attr_name.lower() == correct_attr.lower():
                    line_match = re.search(r"line (\d+)", error_message)
                    if line_match:
                        line_num = int(line_match.group(1))
                        lines = code.split('\n')
                        
                        if 0 <= line_num - 1 < len(lines):
                            line = lines[line_num - 1]
                            fixed_line = line.replace(f"{module_name}.{attr_name}", f"{module_name}.{correct_attr}")
                            lines[line_num - 1] = fixed_line + f"  # 属性名の大文字小文字を修正"
                            fixed_code = '\n'.join(lines)
                            return fixed_code, True
    
    return code, False

def _fix_file_not_found(code: str, error_message: str, container_id: str):
    """ファイルが見つからないエラーの修正"""
    # "No such file or directory: 'filename'" パターンを検出
    file_match = re.search(r"No such file or directory: ['\"](.*?)['\"]", error_message)
    if file_match:
        file_path = file_match.group(1)
        line_match = re.search(r"line (\d+)", error_message)
        
        if line_match:
            line_num = int(line_match.group(1))
            lines = code.split('\n')
            
            if 0 <= line_num - 1 < len(lines):
                line = lines[line_num - 1]
                
                # ファイルパスの修正を試みる
                if '/' in file_path or '\\' in file_path:
                    # 相対パスをより柔軟に
                    basename = os.path.basename(file_path)
                    
                    # ファイルの存在確認を行うコードを追加
                    indent = len(line) - len(line.lstrip())
                    indent_str = ' ' * indent
                    
                    # オリジナルの行を保存
                    original_line = line
                    
                    # パスを修正
                    lines[line_num - 1] = f"{indent_str}import os"
                    lines.insert(line_num, f"{indent_str}file_path = '{file_path}'")
                    lines.insert(line_num + 1, f"{indent_str}if not os.path.exists(file_path):")
                    lines.insert(line_num + 2, f"{indent_str}    # 様々なパターンでファイルを探す")
                    lines.insert(line_num + 3, f"{indent_str}    alt_paths = [")
                    lines.insert(line_num + 4, f"{indent_str}        '{basename}',")
                    lines.insert(line_num + 5, f"{indent_str}        os.path.join('data', '{basename}'),")
                    lines.insert(line_num + 6, f"{indent_str}        os.path.join('..', '{basename}'),")
                    lines.insert(line_num + 7, f"{indent_str}        os.path.join('input', '{basename}')")
                    lines.insert(line_num + 8, f"{indent_str}    ]")
                    lines.insert(line_num + 9, f"{indent_str}    for path in alt_paths:")
                    lines.insert(line_num + 10, f"{indent_str}        if os.path.exists(path):")
                    lines.insert(line_num + 11, f"{indent_str}            file_path = path")
                    lines.insert(line_num + 12, f"{indent_str}            print(f'ファイルが見つかりました: {{path}}')")
                    lines.insert(line_num + 13, f"{indent_str}            break")
                    
                    # 元の行のファイルパスをfile_pathに置換
                    modified_line = original_line.replace(f"'{file_path}'", "file_path").replace(f'"{file_path}"', "file_path")
                    lines.insert(line_num + 14, modified_line)
                    
                    fixed_code = '\n'.join(lines)
                    return fixed_code, True
    
    return code, False

def _fix_zero_division(code: str, error_message: str, container_id: str):
    """ゼロ除算エラーの修正"""
    if "division by zero" in error_message:
        line_match = re.search(r"line (\d+)", error_message)
        
        if line_match:
            line_num = int(line_match.group(1))
            lines = code.split('\n')
            
            if 0 <= line_num - 1 < len(lines):
                line = lines[line_num - 1]
                
                # 除算演算子を検出
                division_match = re.search(r'(.*?)/(.*)', line)
                if division_match:
                    numerator = division_match.group(1).strip()
                    denominator = division_match.group(2).strip()
                    
                    # インデントを保持
                    indent = len(line) - len(line.lstrip())
                    indent_str = ' ' * indent
                    
                    # ゼロ除算チェックを追加
                    lines[line_num - 1] = f"{indent_str}if {denominator} != 0:"
                    lines.insert(line_num, f"{indent_str}    {line.strip()}")
                    lines.insert(line_num + 1, f"{indent_str}else:")
                    lines.insert(line_num + 2, f"{indent_str}    print('警告: ゼロ除算を防止しました')")
                    lines.insert(line_num + 3, f"{indent_str}    # 代替値を割り当て")
                    lines.insert(line_num + 4, f"{indent_str}    # 行の左辺を抽出")
                    
                    # 代入文を解析して左辺を取得
                    assignment_match = re.search(r'(.*?)=', line)
                    if assignment_match:
                        lhs = assignment_match.group(1).strip()
                        lines.insert(line_num + 5, f"{indent_str}    {lhs} = float('inf')  # または適切なデフォルト値")
                    else:
                        # 代入でない場合はコメントアウト
                        lines.insert(line_num + 5, f"{indent_str}    # {line.strip()} # ゼロ除算をスキップ")
                    
                    fixed_code = '\n'.join(lines)
                    return fixed_code, True
    
    return code, False

def _fix_value_error(code: str, error_message: str, container_id: str):
    """ValueError の修正"""
    # 様々なValueErrorパターンを検出
    
    # 数値変換エラー
    if "invalid literal for int()" in error_message or "could not convert string to float" in error_message:
        line_match = re.search(r"line (\d+)", error_message)
        
        if line_match:
            line_num = int(line_match.group(1))
            lines = code.split('\n')
            
            if 0 <= line_num - 1 < len(lines):
                line = lines[line_num - 1]
                
                # int() または float() の呼び出しを検出
                conversion_match = re.search(r'(int|float)\((.*?)\)', line)
                if conversion_match:
                    conversion_func = conversion_match.group(1)
                    arg = conversion_match.group(2).strip()
                    
                    # 変換エラーを捕捉するように修正
                    indent = len(line) - len(line.lstrip())
                    indent_str = ' ' * indent
                    
                    # 元の行を保存
                    original_line = line
                    
                    # try-except ブロックで囲む
                    lines[line_num - 1] = f"{indent_str}try:"
                    lines.insert(line_num, f"{indent_str}    {original_line.strip()}")
                    lines.insert(line_num + 1, f"{indent_str}except ValueError:")
                    lines.insert(line_num + 2, f"{indent_str}    print(f'変換エラー: {{{{f\"{{arg}}\"}}}}を{conversion_func}に変換できません')")
                    
                    # 代入文の場合はデフォルト値を設定
                    assignment_match = re.search(r'(.*?)=', original_line)
                    if assignment_match:
                        lhs = assignment_match.group(1).strip()
                        default_value = "0" if conversion_func == "int" else "0.0"
                        lines.insert(line_num + 3, f"{indent_str}    {lhs} = {default_value}  # デフォルト値")
                    
                    fixed_code = '\n'.join(lines)
                    return fixed_code, True
    
    # リスト操作エラー
    if "needs more than 1 value to unpack" in error_message or "not enough values to unpack" in error_message:
        # TODO: アンパックエラーの修正
        pass
    
    return code, False

def _fix_unbound_local_error(code: str, error_message: str, container_id: str):
    """UnboundLocalError の修正"""
    # "local variable 'x' referenced before assignment" パターンを検出
    var_match = re.search(r"local variable '([^']+)' referenced before assignment", error_message)
    if var_match:
        var_name = var_match.group(1)
        line_match = re.search(r"line (\d+)", error_message)
        
        if line_match:
            line_num = int(line_match.group(1))
            lines = code.split('\n')
            
            if 0 <= line_num - 1 < len(lines):
                # 関数内でグローバル変数を参照している可能性
                # 関数定義を探す
                func_start = line_num - 1
                while func_start >= 0 and not lines[func_start].strip().startswith("def "):
                    func_start -= 1
                
                if func_start >= 0:
                    # 関数内でグローバル変数を宣言
                    func_line = lines[func_start]
                    indent = len(lines[func_start + 1]) - len(lines[func_start + 1].lstrip())
                    indent_str = ' ' * indent
                    
                    # global宣言を追加
                    lines.insert(func_start + 1, f"{indent_str}global {var_name}  # グローバル変数として宣言")
                    
                    fixed_code = '\n'.join(lines)
                    return fixed_code, True
                
                # 関数が見つからない場合は、変数の初期化が必要
                indent = len(lines[line_num - 1]) - len(lines[line_num - 1].lstrip())
                indent_str = ' ' * indent
                
                # 一般的な型に基づいて初期化
                if var_name.endswith(('_list', '_arr', '_array', 'list', 'arr', 'array')):
                    default_value = "[]"
                elif var_name.endswith(('_dict', 'dict', 'map')):
                    default_value = "{}"
                elif var_name.endswith(('_str', 'str', 'name', 'text')):
                    default_value = "''"
                elif var_name.endswith(('_num', 'num', 'count', 'sum', 'total')):
                    default_value = "0"
                elif var_name.startswith(('is_', 'has_', 'can_')):
                    default_value = "False"
                else:
                    default_value = "None"
                
                # 変数初期化を追加
                lines.insert(line_num - 1, f"{indent_str}{var_name} = {default_value}  # 未初期化変数を初期化")
                
                fixed_code = '\n'.join(lines)
                return fixed_code, True
    
    return code, False

@tool(
    name="codeact_comprehensive_analysis",
    description="様々なデータファイルに対する包括的な分析を実行",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "分析対象のデータファイルパス"},
            "analysis_type": {"type": "string", "enum": ["summary", "exploratory", "visualization", "full"], "description": "実行する分析タイプ"},
            "output_format": {"type": "string", "enum": ["text", "json", "html"], "description": "結果の出力形式"},
            "container_id": {"type": "string", "description": "(オプション) 既存コンテナID"}
        },
        "required": ["file_path", "analysis_type"]
    }
)
def codeact_comprehensive_analysis(
    file_path: str,
    analysis_type: str = "summary",
    output_format: str = "text",
    container_id: Optional[str] = None
):
    """
    データファイルに対する包括的な分析を実行します。
    
    対応ファイル形式: CSV, Excel, JSON, TSV, SQLite, Parquet, HDF5, および一般的なテキストファイル
    
    Args:
        file_path: 分析対象のデータファイルパス
        analysis_type: 実行する分析タイプ（summary, exploratory, visualization, full）
        output_format: 結果の出力形式（text, json, html）
        container_id: 既存のコンテナID
        
    Returns:
        分析結果を含む文字列
    """
    # データファイルの存在確認
    if not os.path.exists(file_path):
        return f"エラー: 指定されたデータファイル '{file_path}' が存在しません。"
    
    # ファイル形式を判断
    file_ext = os.path.splitext(file_path)[1].lower()
    
    # 分析タイプに応じたコードを生成
    analysis_code = _generate_analysis_code(file_path, file_ext, analysis_type, output_format)
    
    # 実行
    sandbox = get_sandbox()
    stdout, stderr, exit_code = sandbox.execute_python(container_id or "codeact-analysis", analysis_code)
    
    # エラー処理
    if stderr and exit_code != 0:
        logger.warning(f"データ分析でエラー発生: {stderr[:100]}...")
        return f"データ分析エラー:\n\n[stdout]\n{stdout}\n\n[stderr]\n{stderr}\nExitCode: {exit_code}"
    
    # 結果を返す
    return f"データ分析結果:\n\n{stdout}"

def _generate_analysis_code(file_path: str, file_ext: str, analysis_type: str, output_format: str) -> str:
    """分析タイプと出力形式に応じたコードを生成"""
    # 基本的なインポート
    code = """
# 必要なライブラリをインポート
import os
import json
import sys
import traceback
import pandas as pd
import numpy as np

# データ可視化ライブラリ
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # バックエンドをAggに設定（ヘッドレス環境用）

try:
    import seaborn as sns
    sns.set(style="whitegrid")
except ImportError:
    print("seabornがインストールされていません。基本的なmatplotlibグラフを使用します。")

# 出力形式の設定
output_format = "{output_format}"

# ユーティリティ関数
def check_missing_values(df):
    # データフレームの欠損値を検査
    missing = df.isnull().sum()
    missing_percent = (missing / len(df)) * 100
    missing_stats = pd.DataFrame({{'欠損値数': missing, '欠損率(%)': missing_percent}})
    return missing_stats[missing_stats['欠損値数'] > 0].sort_values('欠損値数', ascending=False)

def check_duplicates(df):
    # 重複行を検査
    n_duplicates = df.duplicated().sum()
    return {{'重複行数': n_duplicates, '重複率(%)': (n_duplicates / len(df)) * 100}}

def get_numeric_columns(df):
    # 数値型カラムを取得 
    return df.select_dtypes(include=[np.number]).columns.tolist()

def get_categorical_columns(df):
    # カテゴリ型カラムを取得
    return df.select_dtypes(include=['object', 'category']).columns.tolist()

def get_datetime_columns(df):
    # 日時型カラムを取得
    return df.select_dtypes(include=['datetime']).columns.tolist()

def detect_outliers(df, columns=None):
    # 外れ値を検出
    if columns is None:
        columns = get_numeric_columns(df)
    
    outliers = {{}}
    for col in columns:
        Q1 = df[col].quantile(0.25)
        Q3 = df[col].quantile(0.75)
        IQR = Q3 - Q1
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        outliers[col] = {{
            '下限': lower_bound,
            '上限': upper_bound,
            '外れ値数': len(df[(df[col] < lower_bound) | (df[col] > upper_bound)]),
            '外れ値率(%)': len(df[(df[col] < lower_bound) | (df[col] > upper_bound)]) / len(df) * 100
        }}
    return outliers

# 可視化ディレクトリを作成
viz_dir = 'viz_output'
os.makedirs(viz_dir, exist_ok=True)
""".format(output_format=output_format)
    
    # ファイル読み込みコード
    code += f"""
# ファイルパス設定
file_path = "{file_path}"
    
# データ読み込み
try:
"""
    
    # ファイル形式に応じた読み込みコード
    if file_ext == '.csv':
        code += """
    # CSVファイル読み込み
    df = pd.read_csv(file_path, low_memory=False)
    print(f"CSVファイル '{file_path}' を読み込みました")
"""
    elif file_ext in ['.xlsx', '.xls']:
        code += """
    # Excelファイル読み込み
    df = pd.read_excel(file_path)
    print(f"Excelファイル '{file_path}' を読み込みました")
"""
    elif file_ext == '.json':
        code += """
    # JSONファイル読み込み
    df = pd.read_json(file_path)
    print(f"JSONファイル '{file_path}' を読み込みました")
"""
    elif file_ext == '.sqlite' or file_ext == '.db':
        code += """
    # SQLiteファイル読み込み
    import sqlite3
    conn = sqlite3.connect(file_path)
    
    # テーブルリストを取得
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    
    if not tables:
        print("SQLiteファイルにテーブルが見つかりません")
        sys.exit(1)
    
    # 最初のテーブルを読み込む
    table_name = tables[0][0]
    df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
    print(f"SQLiteファイル '{file_path}' のテーブル '{table_name}' を読み込みました")
"""
    elif file_ext == '.parquet':
        code += """
    # Parquetファイル読み込み
    try:
        import pyarrow.parquet as pq
        df = pq.read_table(file_path).to_pandas()
        print(f"Parquetファイル '{file_path}' を読み込みました")
    except ImportError:
        try:
            df = pd.read_parquet(file_path)
            print(f"Parquetファイル '{file_path}' を読み込みました")
        except:
            print("Parquetファイルを読み込むにはpyarrowまたはfastparquetが必要です")
            !pip install pyarrow
            df = pd.read_parquet(file_path)
"""
    elif file_ext == '.h5' or file_ext == '.hdf5':
        code += """
    # HDF5ファイル読み込み
    try:
        df = pd.read_hdf(file_path)
        print(f"HDF5ファイル '{file_path}' を読み込みました")
    except:
        print("HDF5ファイルを読み込むにはtablesが必要です")
        !pip install tables
        df = pd.read_hdf(file_path)
"""
    else:
        # 自動判別
        code += """
    # 形式を自動判別して読み込み
    try:
        df = pd.read_csv(file_path, sep=None, engine='python')
        print(f"ファイル '{file_path}' をCSVとして読み込みました")
    except:
        try:
            df = pd.read_excel(file_path)
            print(f"ファイル '{file_path}' をExcelとして読み込みました")
        except:
            try:
                df = pd.read_json(file_path)
                print(f"ファイル '{file_path}' をJSONとして読み込みました")
            except:
                with open(file_path, 'r') as f:
                    content = f.read()
                print(f"ファイル '{file_path}' をテキストとして読み込みました（データフレーム分析は実行できません）")
                # テキスト分析コードをここに追加
                sys.exit(0)
"""
    
    # エラーハンドリング
    code += """
except Exception as e:
    print(f"ファイル読み込みエラー: {str(e)}")
    traceback.print_exc()
    sys.exit(1)
"""
    
    # 分析タイプに応じたコード
    if analysis_type == "summary" or analysis_type == "full":
        code += """
# 基本サマリー
print("\\n===== 基本情報 =====")
print(f"行数: {len(df)}, 列数: {len(df.columns)}")
print(f"データサイズ: {df.memory_usage(deep=True).sum() / (1024*1024):.2f} MB")

print("\\n===== カラム情報 =====")
columns_info = pd.DataFrame({
    'データ型': df.dtypes,
    '非欠損値数': df.count(),
    '欠損値数': df.isnull().sum(),
    '欠損率(%)': df.isnull().sum() / len(df) * 100,
    'ユニーク値数': df.nunique(),
})
print(columns_info)

print("\\n===== 数値カラムの統計 =====")
numeric_columns = get_numeric_columns(df)
if numeric_columns:
    print(df[numeric_columns].describe().T)
else:
    print("数値型カラムはありません")

print("\\n===== カテゴリカラムの情報 =====")
categorical_columns = get_categorical_columns(df)
if categorical_columns:
    for col in categorical_columns[:5]:  # 最大5カラムまで表示
        print(f"\\nカラム: {col}")
        value_counts = df[col].value_counts().head(10)
        print(value_counts)
        print(f"ユニーク値数: {df[col].nunique()}")
else:
    print("カテゴリ型カラムはありません")

print("\\n===== 欠損値情報 =====")
missing_stats = check_missing_values(df)
if not missing_stats.empty:
    print(missing_stats)
else:
    print("欠損値はありません")

print("\\n===== 重複データ =====")
duplicates = check_duplicates(df)
print(duplicates)
"""
    
    if analysis_type == "exploratory" or analysis_type == "full":
        code += """
print("\\n===== 相関分析 =====")
numeric_columns = get_numeric_columns(df)
if len(numeric_columns) >= 2:
    correlation = df[numeric_columns].corr()
    print("数値カラム間の相関係数:")
    print(correlation)
    
    # 相関マトリックスのヒートマップを作成
    plt.figure(figsize=(10, 8))
    sns.heatmap(correlation, annot=True, cmap='coolwarm', vmin=-1, vmax=1, linewidths=0.5)
    plt.title('相関マトリックス')
    plt.tight_layout()
    correlation_file = os.path.join(viz_dir, 'correlation_matrix.png')
    plt.savefig(correlation_file)
    plt.close()
    print(f"相関マトリックスを {correlation_file} に保存しました")
else:
    print("相関分析には2つ以上の数値カラムが必要です")

print("\\n===== 外れ値分析 =====")
if numeric_columns:
    outliers = detect_outliers(df)
    for col, stats in outliers.items():
        print(f"カラム: {col}")
        print(f"  下限: {stats['下限']:.2f}, 上限: {stats['上限']:.2f}")
        print(f"  外れ値数: {stats['外れ値数']}, 外れ値率: {stats['外れ値率(%)']:.2f}%")
else:
    print("外れ値分析には数値カラムが必要です")
"""
    
    if analysis_type == "visualization" or analysis_type == "full":
        code += """
print("\\n===== データ可視化 =====")
# 数値列のヒストグラム
numeric_columns = get_numeric_columns(df)
if numeric_columns:
    print("\\n数値カラムのヒストグラム生成:")
    for i, col in enumerate(numeric_columns[:5]):  # 最大5カラムまで
        plt.figure(figsize=(10, 6))
        sns.histplot(df[col].dropna(), kde=True)
        plt.title(f'{col} の分布')
        plt.xlabel(col)
        plt.ylabel('頻度')
        hist_file = os.path.join(viz_dir, f'histogram_{col}.png')
        plt.savefig(hist_file)
        plt.close()
        print(f"  {col} のヒストグラムを {hist_file} に保存しました")

# 上位のカテゴリ列のカウントプロット
categorical_columns = get_categorical_columns(df)
if categorical_columns:
    print("\\nカテゴリカラムのカウントプロット生成:")
    for i, col in enumerate(categorical_columns[:3]):  # 最大3カラムまで
        if df[col].nunique() <= 20:  # カテゴリが多すぎる場合はスキップ
            plt.figure(figsize=(12, 6))
            value_counts = df[col].value_counts().head(10)
            sns.barplot(x=value_counts.index, y=value_counts.values)
            plt.title(f'{col} の上位カテゴリ')
            plt.xticks(rotation=45, ha='right')
            plt.tight_layout()
            bar_file = os.path.join(viz_dir, f'barplot_{col}.png')
            plt.savefig(bar_file)
            plt.close()
            print(f"  {col} のカウントプロットを {bar_file} に保存しました")

# 数値列間の散布図
if len(numeric_columns) >= 2:
    print("\\n数値カラム間の散布図生成:")
    for i in range(min(3, len(numeric_columns))):  # 最大3組の組み合わせ
        for j in range(i+1, min(4, len(numeric_columns))):
            col1, col2 = numeric_columns[i], numeric_columns[j]
            plt.figure(figsize=(10, 6))
            sns.scatterplot(x=df[col1], y=df[col2])
            plt.title(f'{col1} vs {col2}')
            plt.xlabel(col1)
            plt.ylabel(col2)
            scatter_file = os.path.join(viz_dir, f'scatter_{col1}_vs_{col2}.png')
            plt.savefig(scatter_file)
            plt.close()
            print(f"  {col1} vs {col2} の散布図を {scatter_file} に保存しました")

# 時系列データの可視化
date_columns = get_datetime_columns(df)
if date_columns and numeric_columns:
    print("\\n時系列データの可視化:")
    date_col = date_columns[0]
    for num_col in numeric_columns[:2]:  # 最大2つの数値カラム
        plt.figure(figsize=(12, 6))
        df.set_index(date_col)[num_col].plot()
        plt.title(f'{num_col} の時系列変化')
        plt.tight_layout()
        time_file = os.path.join(viz_dir, f'timeseries_{num_col}.png')
        plt.savefig(time_file)
        plt.close()
        print(f"  {num_col} の時系列プロットを {time_file} に保存しました")
"""
    
    # 出力形式に応じた処理
    if output_format == "json":
        code += """
# 分析結果をJSON形式で出力
result = {
    "ファイル情報": {
        "ファイルパス": file_path,
        "行数": len(df),
        "列数": len(df.columns),
        "サイズ": f"{df.memory_usage(deep=True).sum() / (1024*1024):.2f} MB"
    },
    "カラム情報": {col: {"タイプ": str(df[col].dtype), "欠損値": int(df[col].isnull().sum()), 
                   "ユニーク値数": int(df[col].nunique())} for col in df.columns},
    "基本統計": json.loads(df.describe().to_json()),
    "欠損値情報": json.loads(check_missing_values(df).to_json()) if not check_missing_values(df).empty else "欠損値なし",
    "重複データ": check_duplicates(df),
    "可視化ファイル": [f for f in os.listdir(viz_dir) if f.endswith('.png')]
}

print(json.dumps(result, ensure_ascii=False, indent=2))
"""
    elif output_format == "html":
        code += """
# 分析結果をHTML形式で出力
html_output = f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>データ分析レポート</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1, h2, h3 {{ color: #2c3e50; }}
        table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        tr:nth-child(even) {{ background-color: #f9f9f9; }}
        .viz-container {{ display: flex; flex-wrap: wrap; gap: 20px; }}
        .viz-item {{ flex: 1; min-width: 300px; margin-bottom: 20px; }}
        img {{ max-width: 100%; height: auto; border: 1px solid #ddd; }}
    </style>
</head>
<body>
    <h1>データ分析レポート</h1>
    <h2>ファイル情報</h2>
    <p>ファイルパス: {file_path}</p>
    <p>行数: {len(df)}, 列数: {len(df.columns)}</p>
    <p>データサイズ: {df.memory_usage(deep=True).sum() / (1024*1024):.2f} MB</p>
    
    <h2>カラム情報</h2>
    <table>
        <tr>
            <th>カラム名</th>
            <th>データ型</th>
            <th>非欠損値数</th>
            <th>欠損値数</th>
            <th>欠損率(%)</th>
            <th>ユニーク値数</th>
        </tr>
'''

for col in df.columns:
    html_output += f'''
        <tr>
            <td>{col}</td>
            <td>{df[col].dtype}</td>
            <td>{df[col].count()}</td>
            <td>{df[col].isnull().sum()}</td>
            <td>{df[col].isnull().sum() / len(df) * 100:.2f}</td>
            <td>{df[col].nunique()}</td>
        </tr>
    '''

html_output += '''
    </table>
    
    <h2>数値カラムの統計</h2>
'''

numeric_columns = get_numeric_columns(df)
if numeric_columns:
    stats = df[numeric_columns].describe().T
    html_output += '<table><tr><th>カラム</th>'
    
    for stat in stats.columns:
        html_output += f'<th>{stat}</th>'
    
    html_output += '</tr>'
    
    for col in stats.index:
        html_output += f'<tr><td>{col}</td>'
        for stat in stats.columns:
            html_output += f'<td>{stats.loc[col, stat]:.2f}</td>'
        html_output += '</tr>'
    
    html_output += '</table>'
else:
    html_output += '<p>数値型カラムはありません</p>'

html_output += '''
    <h2>欠損値情報</h2>
'''

missing_stats = check_missing_values(df)
if not missing_stats.empty:
    html_output += '<table><tr><th>カラム</th><th>欠損値数</th><th>欠損率(%)</th></tr>'
    
    for col in missing_stats.index:
        html_output += f'''
            <tr>
                <td>{col}</td>
                <td>{missing_stats.loc[col, '欠損値数']}</td>
                <td>{missing_stats.loc[col, '欠損率(%)']:.2f}</td>
            </tr>
        '''
    
    html_output += '</table>'
else:
    html_output += '<p>欠損値はありません</p>'

html_output += '''
    <h2>可視化結果</h2>
    <div class="viz-container">
'''

# 生成された可視化を含める
viz_files = [f for f in os.listdir(viz_dir) if f.endswith('.png')]
for viz_file in viz_files:
    viz_path = os.path.join(viz_dir, viz_file)
    # 画像をBase64エンコード
    import base64
    with open(viz_path, "rb") as image_file:
        encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
    
    html_output += f'''
        <div class="viz-item">
            <h3>{viz_file.replace('.png', '').replace('_', ' ').title()}</h3>
            <img src="data:image/png;base64,{encoded_image}" alt="{viz_file}">
        </div>
    '''

html_output += '''
    </div>
</body>
</html>
'''

# HTMLファイルに保存
html_file = os.path.join(viz_dir, 'analysis_report.html')
with open(html_file, 'w', encoding='utf-8') as f:
    f.write(html_output)

print(f"HTML形式のレポートを {html_file} に保存しました")
print(html_output)
"""
    else:  # text format (default)
        # 必要に応じた追加処理
        pass
    
    return code

@tool(
    name="codeact_generation",
    description="特定要件に基づいてコードを生成",
    parameters={
        "type": "object",
        "properties": {
            "requirements": {"type": "string", "description": "コード生成要件の詳細説明"},
            "language": {"type": "string", "description": "生成するコードの言語"},
            "code_type": {"type": "string", "enum": ["script", "library", "webapp", "api", "data_processing"], "description": "生成するコードのタイプ"},
            "output_file": {"type": "string", "description": "出力ファイル名（オプション）"}
        },
        "required": ["requirements", "language", "code_type"]
    }
)
def codeact_generation(
    requirements: str,
    language: str,
    code_type: str,
    output_file: Optional[str] = None
):
    """
    指定された要件に基づいてコードを生成します。
    
    Args:
        requirements: コード生成要件の詳細説明
        language: 生成するコードの言語（python, javascript, java, etc）
        code_type: 生成するコードのタイプ（script, library, webapp, api, data_processing）
        output_file: 出力ファイル名（オプション）
        
    Returns:
        生成されたコードを含む文字列
    """
    from llm.azure_openai_client import AzureOpenAIClient
    from config import CONFIG
    
    # 出力ファイル名が指定されていない場合のデフォルト設定
    if not output_file:
        ext_map = {
            "python": "py",
            "javascript": "js",
            "typescript": "ts",
            "java": "java",
            "c#": "cs",
            "c++": "cpp",
            "c": "c",
            "ruby": "rb",
            "go": "go",
            "rust": "rs",
            "php": "php",
            "scala": "scala",
            "kotlin": "kt",
            "swift": "swift",
            "sql": "sql",
            "html": "html",
            "css": "css"
        }
        ext = ext_map.get(language.lower(), "txt")
        output_file = f"generated_code.{ext}"
    
    # コード生成用LLMプロンプトの構築
    prompt_template = f"""
あなたは優れたプログラマーです。以下の要件に基づいて{language}コードを生成してください。

## 要件
{requirements}

## コードタイプ
{code_type}

## 言語
{language}

コードは以下の点を考慮してください：
1. わかりやすいコメントを含める
2. エラー処理を適切に実装する
3. 変数名や関数名は明確で説明的なものを使用
4. コードの再利用性と保守性を高める
5. 最新のベストプラクティスに従う

完全なコードを生成し、返してください。コメントではなくコードのみが必要です。
"""
    
    # LLMを使用してコードを生成
    try:
        llm_client = AzureOpenAIClient()
        generated_code = llm_client.call_azure_openai(
            prompt=prompt_template,
            system_prompt="あなたは熟練したプログラマーで、要件やベストプラクティスに基づく高品質なコードを生成します。",
            model=CONFIG["llm"]["model"],
            temperature=0.2,
            max_tokens=3000
        )
        
        # コードをファイルに保存（必要な場合）
        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(generated_code)
            return f"要件に基づいて{language}のコードを生成し、{output_file}に保存しました:\n\n{generated_code}"
        else:
            return f"要件に基づいて{language}のコードを生成しました:\n\n{generated_code}"
    
    except Exception as e:
        logger.error(f"コード生成中にエラー発生: {str(e)}")
        return f"コード生成中にエラーが発生しました: {str(e)}"
