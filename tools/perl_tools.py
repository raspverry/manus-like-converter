# tools/perl_tools.py
"""
Perlコード解析と変換のためのツール。
PerlコードをPythonに変換するためのユーティリティ関数と解析ツールを提供します。
"""
import os
import json
import re
import subprocess
import tempfile
from typing import Dict, Any, List, Optional, Tuple

from core.logging_config import logger
from tools.tool_registry import tool
from sandbox.sandbox import get_sandbox
from config import CONFIG

@tool(
    name="perl_code_parse",
    description="Perlコードを構造解析する",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "解析するPerlコード"},
            "save_output": {"type": "boolean", "description": "結果を出力ファイルに保存するかどうか"},
            "output_file": {"type": "string", "description": "結果を保存するファイル名"}
        },
        "required": ["code"]
    }
)
def perl_code_parse(code: str, save_output: bool = False, output_file: str = "perl_analysis.json"):
    """
    Perlコードを解析して構造情報を抽出します。
    
    選択されたパーサー（PPI、B::Deparse、perltidy など）を使用して、
    Perlコードの構造を解析します。
    
    Args:
        code: 解析するPerlコード
        save_output: 結果をファイルに保存するかどうか
        output_file: 結果を保存するファイル名
        
    Returns:
        Perlコードの構造解析結果（JSON形式）
    """
    parser = CONFIG["converter"].get("perl_parser", "ppi")
    logger.info(f"Perlコードの解析を開始 (パーサー: {parser})")
    
    try:
        if parser == "ppi":
            # PPIを使用した解析
            result = _parse_with_ppi(code)
        elif parser == "perltidy":
            # perltidyを使用した解析（整形）
            result = _parse_with_perltidy(code)
        elif parser == "deparse":
            # B::Deparseを使用した解析
            result = _parse_with_deparse(code)
        else:
            return f"サポートされていないパーサー: {parser}"
        
        # 結果を保存
        if save_output and output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            return f"解析結果を {output_file} に保存しました。\n\n{json.dumps(result, indent=2, ensure_ascii=False)}"
        
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Perlコード解析エラー: {str(e)}")
        return f"Perlコードの解析中にエラーが発生しました: {str(e)}"

def _parse_with_ppi(code: str) -> Dict[str, Any]:
    """PPIを使用してPerlコードを解析"""
    # サンドボックス内でPPIを実行
    sandbox = get_sandbox()
    
    # Perlスクリプトを一時ファイルに保存
    with tempfile.NamedTemporaryFile(suffix='.pl', delete=False, mode='w') as tmp:
        tmp_perl_file = tmp.name
        tmp.write(code)
    
    # PPIを使用した解析スクリプト
    ppi_script = """#!/usr/bin/perl
use strict;
use warnings;
use PPI;
use JSON;

# 解析するファイル
my $file = $ARGV[0];
my $doc = PPI::Document->new($file);

# 構造を保存する
my %structure;

# ドキュメントの基本情報
$structure{type} = 'PPI::Document';
$structure{elements} = [];

# 要素を解析する関数
sub analyze_element {
    my ($element) = @_;
    my %info;
    
    $info{type} = ref($element);
    $info{content} = "$element" if defined $element->content;
    
    # 子要素がある場合
    if ($element->can('children') && $element->children) {
        $info{children} = [];
        foreach my $child ($element->children) {
            push @{$info{children}}, analyze_element($child);
        }
    }
    
    return \%info;
}

# ドキュメントの各要素を解析
foreach my $element ($doc->children) {
    push @{$structure{elements}}, analyze_element($element);
}

# JSON形式で出力
print encode_json(\%structure);
"""
    
    # 一時ファイルにPPIスクリプトを保存
    with tempfile.NamedTemporaryFile(suffix='.pl', delete=False, mode='w') as tmp:
        ppi_script_file = tmp.name
        tmp.write(ppi_script)
    
    try:
        # サンドボックス内でPerlスクリプトを実行
        cmd = f"perl {ppi_script_file} {tmp_perl_file}"
        stdout, stderr, exit_code = sandbox.execute_command("perl-parse", cmd, "/home/ubuntu/workspace")
        
        if exit_code != 0:
            # PPIが利用できない場合は、簡易解析に切り替え
            logger.warning(f"PPI解析に失敗しました。簡易解析を使用します。エラー: {stderr}")
            return _simple_perl_analysis(code)
        
        # JSON結果を解析
        try:
            result = json.loads(stdout)
            return result
        except json.JSONDecodeError:
            logger.error(f"PPI出力のJSON解析に失敗しました: {stdout}")
            return _simple_perl_analysis(code)
    finally:
        # 一時ファイルの削除
        try:
            os.unlink(tmp_perl_file)
            os.unlink(ppi_script_file)
        except:
            pass
    
def _parse_with_perltidy(code: str) -> Dict[str, Any]:
    """perltidyを使用してPerlコードを整形・解析"""
    # サンドボックス内でperltidyを実行
    sandbox = get_sandbox()
    
    # Perlスクリプトを一時ファイルに保存
    with tempfile.NamedTemporaryFile(suffix='.pl', delete=False, mode='w') as tmp:
        tmp_perl_file = tmp.name
        tmp.write(code)
    
    try:
        # perltidyコマンドを実行
        cmd = f"perltidy {tmp_perl_file} -st -se"
        stdout, stderr, exit_code = sandbox.execute_command("perl-parse", cmd, "/home/ubuntu/workspace")
        
        if exit_code != 0:
            # perltidyが利用できない場合は、簡易解析に切り替え
            logger.warning(f"perltidy解析に失敗しました。簡易解析を使用します。エラー: {stderr}")
            return _simple_perl_analysis(code)
        
        # 整形されたコードを返す
        return {
            "type": "perltidy",
            "formatted_code": stdout,
            "original_code": code
        }
    finally:
        # 一時ファイルの削除
        try:
            os.unlink(tmp_perl_file)
        except:
            pass

def _parse_with_deparse(code: str) -> Dict[str, Any]:
    """B::Deparseを使用してPerlコードを解析"""
    # サンドボックス内でB::Deparseを実行
    sandbox = get_sandbox()
    
    # Perlスクリプトを一時ファイルに保存
    with tempfile.NamedTemporaryFile(suffix='.pl', delete=False, mode='w') as tmp:
        tmp_perl_file = tmp.name
        tmp.write(code)
    
    try:
        # B::Deparseコマンドを実行
        cmd = f"perl -MO=Deparse {tmp_perl_file}"
        stdout, stderr, exit_code = sandbox.execute_command("perl-parse", cmd, "/home/ubuntu/workspace")
        
        if exit_code != 0:
            # B::Deparseが利用できない場合は、簡易解析に切り替え
            logger.warning(f"B::Deparse解析に失敗しました。簡易解析を使用します。エラー: {stderr}")
            return _simple_perl_analysis(code)
        
        # 解析結果を返す
        return {
            "type": "B::Deparse",
            "deparsed_code": stdout,
            "original_code": code
        }
    finally:
        # 一時ファイルの削除
        try:
            os.unlink(tmp_perl_file)
        except:
            pass

def _simple_perl_analysis(code: str) -> Dict[str, Any]:
    """
    シンプルな正規表現ベースのPerlコード解析
    (外部ツールが利用できない場合のフォールバック)
    """
    # コードを行ごとに分割
    lines = code.split('\n')
    
    # 解析結果
    result = {
        "type": "simple_analysis",
        "line_count": len(lines),
        "packages": [],
        "subroutines": [],
        "variables": {
            "scalar": [],
            "array": [],
            "hash": []
        },
        "use_statements": [],
        "comments": [],
        "original_code": code
    }
    
    # 解析ルール
    package_re = re.compile(r'package\s+([^;]+);')
    sub_re = re.compile(r'sub\s+(\w+)\s*(?:\{|\()')
    scalar_re = re.compile(r'\$(\w+)')
    array_re = re.compile(r'\@(\w+)')
    hash_re = re.compile(r'\%(\w+)')
    use_re = re.compile(r'use\s+([^;]+);')
    comment_re = re.compile(r'^\s*#(.*)$')
    
    # コードを行ごとに解析
    for line in lines:
        # パッケージ
        package_match = package_re.search(line)
        if package_match:
            result["packages"].append(package_match.group(1).strip())
        
        # サブルーチン
        sub_match = sub_re.search(line)
        if sub_match:
            result["subroutines"].append(sub_match.group(1))
        
        # スカラー変数
        for var in set(scalar_re.findall(line)):
            if var not in result["variables"]["scalar"]:
                result["variables"]["scalar"].append(var)
        
        # 配列変数
        for var in set(array_re.findall(line)):
            if var not in result["variables"]["array"]:
                result["variables"]["array"].append(var)
        
        # ハッシュ変数
        for var in set(hash_re.findall(line)):
            if var not in result["variables"]["hash"]:
                result["variables"]["hash"].append(var)
        
        # use文
        use_match = use_re.search(line)
        if use_match:
            result["use_statements"].append(use_match.group(1).strip())
        
        # コメント
        comment_match = comment_re.search(line)
        if comment_match:
            result["comments"].append(comment_match.group(1).strip())
    
    return result

@tool(
    name="perl_to_python_convert",
    description="Perlコードセグメントを変換する",
    parameters={
        "type": "object",
        "properties": {
            "perl_code": {"type": "string", "description": "変換するPerlコードセグメント"},
            "context": {"type": "string", "description": "コンテキスト情報（オプション）"},
            "output_file": {"type": "string", "description": "出力ファイル（オプション）"}
        },
        "required": ["perl_code"]
    }
)
def perl_to_python_convert(perl_code: str, context: str = "", output_file: str = ""):
    """
    Perlコードセグメントを等価なPythonコードに変換します。
    
    Args:
        perl_code: 変換するPerlコードセグメント
        context: 変換のためのコンテキスト情報（オプション）
        output_file: 出力ファイル（オプション）
        
    Returns:
        変換されたPythonコード
    """
    logger.info(f"Perlコードの変換を開始 (長さ: {len(perl_code)}文字)")
    
    try:
        # LLMを使用してPerlコードをPythonに変換
        from llm.openai_client import OpenAIClient
        
        llm_client = OpenAIClient(use_langchain=CONFIG["llm"]["use_langchain"])
        
        system_prompt = """
        あなたはPerlからPythonへの変換の専門家です。以下のルールに従って変換を行ってください：
        
        1. 機能的等価性を維持する
        2. Pythonの慣用的な書き方を使用する
        3. Perl特有の構文を適切に変換する
        4. コメントと構造を保持する
        5. PEP 8スタイルガイドに従う
        
        特に注意すべき点：
        - スカラー変数($var)をPython変数に変換
        - 配列変数(@arr)をPythonリストに変換
        - ハッシュ変数(%hash)をPython辞書に変換
        - Perlの特殊変数($_, @_, $!, etc)を適切なPython表現に変換
        - 正規表現をPythonのre模塊に変換
        - ファイル操作をPythonのファイルオブジェクトに変換
        
        抽象構文木の解析に基づいて正確な変換を行ってください。解説は不要です。
        """
        
        prompt = f"""
        以下のPerlコードをPythonに変換してください：
        
        ```perl
        {perl_code}
        ```
        
        追加コンテキスト情報：
        {context}
        
        Python変換コードのみを出力してください。説明は不要です。
        """
        
        # LLMでコード変換
        python_code, _ = llm_client.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=2000
        )
        
        # コード抽出（マークダウンブロックから抽出する場合）
        python_code = _extract_code(python_code)
        
        # 出力ファイルに保存
        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(python_code)
            return f"変換されたPythonコードを {output_file} に保存しました。\n\n{python_code}"
        
        return python_code
    except Exception as e:
        logger.error(f"Perlコード変換エラー: {str(e)}")
        return f"Perlコードの変換中にエラーが発生しました: {str(e)}"

def _extract_code(text: str) -> str:
    """
    テキストからコードブロックを抽出
    """
    # Python コードブロックの検索
    code_block_pattern = r'```(?:python)?\s*(.*?)```'
    code_match = re.search(code_block_pattern, text, re.DOTALL)
    
    if code_match:
        return code_match.group(1).strip()
    
    # コードブロックがない場合は全体を返す
    return text.strip()

@tool(
    name="perl_test_conversion",
    description="変換されたPythonコードをテストする",
    parameters={
        "type": "object",
        "properties": {
            "perl_code": {"type": "string", "description": "元のPerlコード"},
            "python_code": {"type": "string", "description": "変換後のPythonコード"},
            "test_input": {"type": "string", "description": "テスト入力（オプション）"},
            "compare_output": {"type": "boolean", "description": "出力を比較するかどうか"}
        },
        "required": ["perl_code", "python_code"]
    }
)
def perl_test_conversion(perl_code: str, python_code: str, test_input: str = "", compare_output: bool = True):
    """
    変換されたPythonコードをテストして、元のPerlコードと同等の出力を生成するか確認します。
    
    Args:
        perl_code: 元のPerlコード
        python_code: 変換後のPythonコード
        test_input: テスト入力（オプション）
        compare_output: 出力を比較するかどうか
        
    Returns:
        テスト結果
    """
    # サンドボックスを取得
    sandbox = get_sandbox()
    
    # 一時ファイルにコードを保存
    with tempfile.NamedTemporaryFile(suffix='.pl', delete=False, mode='w') as tmp_perl:
        perl_file = tmp_perl.name
        tmp_perl.write(perl_code)
    
    with tempfile.NamedTemporaryFile(suffix='.py', delete=False, mode='w') as tmp_python:
        python_file = tmp_python.name
        tmp_python.write(python_code)
    
    try:
        # テスト入力がある場合は保存
        input_file = None
        if test_input:
            with tempfile.NamedTemporaryFile(suffix='.txt', delete=False, mode='w') as tmp_input:
                input_file = tmp_input.name
                tmp_input.write(test_input)
        
        # Perlコードの実行
        if input_file:
            cmd_perl = f"perl {perl_file} < {input_file}"
        else:
            cmd_perl = f"perl {perl_file}"
        
        perl_stdout, perl_stderr, perl_exit = sandbox.execute_command(
            "perl-test", cmd_perl, "/home/ubuntu/workspace"
        )
        
        # Pythonコードの実行
        if input_file:
            cmd_python = f"python3 {python_file} < {input_file}"
        else:
            cmd_python = f"python3 {python_file}"
        
        python_stdout, python_stderr, python_exit = sandbox.execute_command(
            "perl-test", cmd_python, "/home/ubuntu/workspace"
        )
        
        # 結果の比較
        result = {
            "perl_output": perl_stdout,
            "perl_error": perl_stderr,
            "perl_exit": perl_exit,
            "python_output": python_stdout,
            "python_error": python_stderr,
            "python_exit": python_exit
        }
        
        # 出力比較
        if compare_output:
            # 出力が等価かどうかをチェック
            output_match = _normalize_output(perl_stdout) == _normalize_output(python_stdout)
            exit_match = perl_exit == python_exit
            
            result["output_match"] = output_match
            result["exit_match"] = exit_match
            result["success"] = output_match and exit_match
            
            # 結果メッセージ
            if result["success"]:
                result["message"] = "テスト成功: 変換されたPythonコードは元のPerlコードと同等の出力を生成します。"
            else:
                differences = []
                if not output_match:
                    differences.append("出力が一致しません")
                if not exit_match:
                    differences.append("終了コードが一致しません")
                
                result["message"] = f"テスト失敗: {', '.join(differences)}"
        
        return json.dumps(result, indent=2, ensure_ascii=False)
    
    finally:
        # 一時ファイルの削除
        try:
            os.unlink(perl_file)
            os.unlink(python_file)
            if input_file:
                os.unlink(input_file)
        except:
            pass

def _normalize_output(output: str) -> str:
    """
    出力を正規化して比較しやすくする
    """
    # 末尾の空白を取り除く
    lines = [line.rstrip() for line in output.splitlines()]
    
    # 空行を無視
    lines = [line for line in lines if line.strip()]
    
    # 再結合
    return '\n'.join(lines)

@tool(
    name="segment_perl_code",
    description="Perlコードを変換しやすいセグメントに分割する",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "分割するPerlコード"},
            "max_segment_size": {"type": "integer", "description": "最大セグメントサイズ"}
        },
        "required": ["code"]
    }
)
def segment_perl_code(code: str, max_segment_size: int = 0):
    """
    Perlコードを変換しやすい論理的なセグメントに分割します。
    
    Args:
        code: 分割するPerlコード
        max_segment_size: 最大セグメントサイズ (0の場合はデフォルト値を使用)
        
    Returns:
        分割されたコードセグメントのJSON配列
    """
    # デフォルトのセグメントサイズ
    if max_segment_size <= 0:
        max_segment_size = CONFIG["converter"].get("segment_size", 500)
    
    logger.info(f"Perlコードをセグメントに分割 (最大サイズ: {max_segment_size}文字)")
    
    try:
        # 解析結果を取得
        analysis_result = _simple_perl_analysis(code)
        
        # コードを行で分割
        lines = code.split('\n')
        
        # セグメントを保持するリスト
        segments = []
        current_segment = []
        current_segment_lines = 0
        
        # 重要な区切り（パッケージ、サブルーチン）の正規表現
        package_re = re.compile(r'^\s*package\s+[^;]+;')
        sub_re = re.compile(r'^\s*sub\s+\w+\s*(?:\{|\()')
        block_start_re = re.compile(r'{\s*$')
        block_end_re = re.compile(r'^\s*}')
        
        # スコープの深さを追跡
        scope_depth = 0
        
        for line in lines:
            # スコープの変化を追跡
            if block_start_re.search(line):
                scope_depth += 1
            if block_end_re.search(line):
                scope_depth -= 1
            
            # 重要な区切りとスコープレベル0の位置で新しいセグメントを開始
            if ((package_re.search(line) or sub_re.search(line)) and scope_depth == 0 and 
                    current_segment_lines > 0):
                # 現在のセグメントを追加
                segments.append('\n'.join(current_segment))
                current_segment = []
                current_segment_lines = 0
            
            # 行を現在のセグメントに追加
            current_segment.append(line)
            current_segment_lines += 1
            
            # セグメントサイズチェック（スコープレベル0の場合のみ）
            if (scope_depth == 0 and current_segment_lines >= max_segment_size and 
                    not (package_re.search(line) or sub_re.search(line) or block_start_re.search(line))):
                segments.append('\n'.join(current_segment))
                current_segment = []
                current_segment_lines = 0
        
        # 最後のセグメントを追加
        if current_segment:
            segments.append('\n'.join(current_segment))
        
        # 結果を返す
        result = {
            "total_lines": len(lines),
            "segment_count": len(segments),
            "segments": segments
        }
        
        return json.dumps(result, indent=2, ensure_ascii=False)
    
    except Exception as e:
        logger.error(f"Perlコードセグメント分割エラー: {str(e)}")
        return f"Perlコードのセグメント分割中にエラーが発生しました: {str(e)}"
