# core/converter_agent.py
"""
Perl から Python への変換を行う特化型エージェント。
既存の Agent クラスを拡張して、コード変換に特化した機能を追加します。
"""

import asyncio
import functools
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.agent import Agent
from core.context import Context
from core.memory import Memory
from core.enhanced_memory import EnhancedMemory
from core.planner import Planner
from tools.tool_registry import ToolRegistry
from llm.openai_client import OpenAIClient
from config import CONFIG


class ConverterAgent(Agent):
    """
    Perl から Python へのコード変換に特化したエージェント。
    """
    
    def __init__(
        self,
        llm_client: OpenAIClient,
        system_prompt: str,
        tool_registry: ToolRegistry,
        planner: Optional[Planner] = None,
        memory: Optional[Memory] = None,
    ) -> None:
        """
        変換エージェントを初期化します。
        
        Args:
            llm_client: LLMクライアント
            system_prompt: システムプロンプト
            tool_registry: ツールレジストリ
            planner: プランナー（オプション）
            memory: メモリ（オプション）
        """
        super().__init__(llm_client, system_prompt, tool_registry, planner, memory)
        
        # 変換固有のデータ構造
        self._conversion_segments = []  # 変換するコードセグメント
        self._converted_segments = {}   # 変換済みコードセグメント
        self._final_python_code = ""    # 最終的な変換結果
        
        # 変換コンテキスト
        self._perl_analysis = None      # Perlコードの解析結果
        self._python_issues = []        # 検出された問題点
        
        # 変換状態
        self._current_segment_index = 0  # 現在処理中のセグメントインデックス
        self._conversion_success = False # 変換が成功したかどうか
        
        logging.info("変換エージェントが初期化されました")
    
    def start_conversion(self, perl_code: str, output_path: Optional[str] = None) -> str:
        """
        Perl から Python への変換を開始します。
        
        Args:
            perl_code: 変換する Perl コード
            output_path: 出力ファイルパス（オプション）
            
        Returns:
            変換結果（Python コード）
        """
        # 変換タスクとしてスタート
        task_description = "Perlコードを解析し、Pythonコードに変換してください。"
        self.context.add_event({"type": "Message", "content": task_description})
        self.context.add_event({"type": "PerlCode", "content": perl_code})
        
        # 非同期変換を実行
        asyncio.run(self._conversion_loop_async(perl_code, output_path))
        
        # 最終結果を返す
        return self._final_python_code
    
    async def _conversion_loop_async(self, perl_code: str, output_path: Optional[str] = None) -> None:
        """
        変換ループを実行します。
        
        Args:
            perl_code: 変換する Perl コード
            output_path: 出力ファイルパス（オプション）
        """
        self._cancel_event = asyncio.Event()
        self._start_time = time.time()
        self._iterations = 0
        
        # 通知をクリア
        self._recent_notifications = []
        
        # ユーザーへの通知
        await self._safe_tool("message_notify_user", {"message": "Perlコードを受け取りました。変換を開始します。"})
        
        # 1. Perlコードの解析
        await self._safe_tool("message_notify_user", {"message": "ステップ1: Perlコードの解析"})
        perl_analysis_result = await self._to_thread(
            self.tool_registry.execute_tool,
            "perl_code_parse",
            {"code": perl_code, "save_output": True, "output_file": "perl_analysis.json"}
        )
        self.context.add_event({"type": "PerlAnalysis", "content": perl_analysis_result})
        
        try:
            self._perl_analysis = json.loads(perl_analysis_result)
        except:
            self._perl_analysis = {"error": "解析結果をJSONとして解析できませんでした"}
        
        # 2. 変換計画の作成
        await self._safe_tool("message_notify_user", {"message": "ステップ2: 変換計画の作成"})
        conversion_plan = await self._to_thread(self.planner.create_plan, f"Perlコードを解析し、Pythonコードに変換する計画を立ててください。\n\n```perl\n{perl_code}\n```")
        self.context.add_event({"type": "Plan", "content": conversion_plan})
        
        # 3. コードのセグメント分割
        await self._safe_tool("message_notify_user", {"message": "ステップ3: コードをセグメントに分割"})
        segmentation_result = await self._to_thread(
            self.tool_registry.execute_tool,
            "segment_perl_code",
            {"code": perl_code}
        )
        self.context.add_event({"type": "Segmentation", "content": segmentation_result})
        
        # セグメントを取得
        try:
            segmentation_data = json.loads(segmentation_result)
            self._conversion_segments = segmentation_data.get("segments", [])
            segment_count = len(self._conversion_segments)
            
            await self._safe_tool(
                "message_notify_user", 
                {"message": f"コードを {segment_count} 個のセグメントに分割しました。変換を開始します。"}
            )
        except:
            # セグメント分割に失敗した場合は、コード全体を1つのセグメントとして扱う
            self._conversion_segments = [perl_code]
            await self._safe_tool(
                "message_notify_user", 
                {"message": "セグメント分割に失敗しました。コード全体を1つのセグメントとして変換します。"}
            )
        
        # 4. セグメントごとに変換
        total_segments = len(self._conversion_segments)
        for i, segment in enumerate(self._conversion_segments):
            if self._cancel_event.is_set():
                await self._safe_tool("message_notify_user", {"message": "変換が中断されました。"})
                return
            
            self._current_segment_index = i
            segment_num = i + 1
            
            await self._safe_tool(
                "message_notify_user", 
                {"message": f"セグメント {segment_num}/{total_segments} を変換中..."}
            )
            
            # セグメントの変換
            python_segment = await self._to_thread(
                self.tool_registry.execute_tool,
                "perl_to_python_convert",
                {
                    "perl_code": segment,
                    "context": f"このセグメントは全体の {segment_num}/{total_segments} 部分です。",
                    "output_file": f"segment_{segment_num}.py"
                }
            )
            
            # 変換結果を保存
            self._converted_segments[i] = python_segment
            self.context.add_event({
                "type": "ConvertedSegment", 
                "segment": segment_num,
                "content": python_segment
            })
            
            # 進捗報告
            progress = int((segment_num / total_segments) * 100)
            await self._safe_tool(
                "message_notify_user", 
                {"message": f"変換進捗: {progress}% ({segment_num}/{total_segments} 完了)"}
            )
        
        # 5. 変換結果のマージ
        await self._safe_tool("message_notify_user", {"message": "ステップ5: 変換されたコードのマージと最適化"})
        
        # セグメントを順番に並べる
        ordered_segments = [self._converted_segments.get(i, "") for i in range(total_segments)]
        
        # セグメントをマージ
        output_file = output_path or "converted_code.py"
        merged_result = await self._to_thread(
            self.tool_registry.execute_tool,
            "merge_python_segments",
            {"segments": ordered_segments, "output_file": output_file}
        )
        
        # 結果を保存
        self._final_python_code = merged_result
        self.context.add_event({"type": "FinalCode", "content": merged_result})
        
        # 6. 変換コードのテスト（オプション）
        if CONFIG["converter"].get("test_conversion", True):
            await self._safe_tool("message_notify_user", {"message": "ステップ6: 変換コードのテスト"})
            
            test_result = await self._to_thread(
                self.tool_registry.execute_tool,
                "perl_test_conversion",
                {
                    "perl_code": perl_code,
                    "python_code": merged_result,
                    "compare_output": True
                }
            )
            
            self.context.add_event({"type": "TestResult", "content": test_result})
            
            try:
                test_data = json.loads(test_result)
                if test_data.get("success", False):
                    await self._safe_tool(
                        "message_notify_user", 
                        {"message": "テスト成功: 変換されたPythonコードは元のPerlコードと同等の出力を生成します。"}
                    )
                    self._conversion_success = True
                else:
                    await self._safe_tool(
                        "message_notify_user", 
                        {"message": f"テスト失敗: {test_data.get('message', '変換されたコードが元のコードと同等ではありません。')}"}
                    )
            except:
                await self._safe_tool(
                    "message_notify_user", 
                    {"message": "テスト結果の解析に失敗しました。変換結果を手動で確認してください。"}
                )
        
        # 7. 完了通知
        await self._safe_tool(
            "message_notify_user", 
            {
                "message": (
                    f"変換が完了しました！\n\n"
                    f"変換されたPythonコードは {output_file} に保存されました。\n\n"
                    f"変換処理時間: {time.time() - self._start_time:.2f}秒"
                )
            }
        )
        
        # 変換タスク完了
        await self._to_thread(
            self.tool_registry.execute_tool,
            "idle",
            {"reason": "変換タスクが完了しました"}
        )
    
    async def _to_thread(self, func, *args, **kwargs):
        """
        同期関数をスレッドプールで実行し、その結果を非同期で待機します。
        
        Args:
            func: 実行する関数
            *args: 関数の位置引数
            **kwargs: 関数のキーワード引数
            
        Returns:
            関数の実行結果
        """
        loop = asyncio.get_running_loop()
        if kwargs:
            func_with_kwargs = functools.partial(func, *args, **kwargs)
            return await loop.run_in_executor(None, func_with_kwargs)
        return await loop.run_in_executor(None, func, *args)
    
    async def _safe_tool(self, name: str, params: Dict[str, Any]):
        """
        ツールを安全に実行します。エラーが発生しても処理を継続します。
        
        Args:
            name: ツール名
            params: ツールのパラメータ
        """
        try:
            await self._to_thread(self.tool_registry.execute_tool, name, params)
        except Exception as exc:
            logging.error(f"ツール {name} の実行中にエラー: {exc}")


class ConversionPlanner(Planner):
    """変換タスク特化型プランナー"""
    
    def create_conversion_plan(self, perl_code: str) -> str:
        """
        Perl コードから Python コードへの変換計画を作成します。
        
        Args:
            perl_code: 変換する Perl コード
            
        Returns:
            変換計画のテキスト
        """
        prompt = f"""
        以下の Perl コードを Python に変換するための詳細な計画を作成してください：
        
        ```perl
        {perl_code}
        ```
        
        計画には以下の内容を含めてください：
        1. Perl コードの構造分析
        2. 変換が難しい部分の特定
        3. ステップバイステップの変換プロセス
        4. テスト戦略
        
        以下の形式で返してください：
        
        ```json
        {{
          "analysis": "コードの簡単な分析",
          "challenges": ["変換が難しい要素のリスト"],
          "steps": [
            {{
              "id": "1",
              "description": "ステップの説明",
              "perl_segment": "関連する Perl コード",
              "conversion_approach": "このセグメントの変換方法"
            }},
            ...
          ],
          "testing": "変換されたコードのテスト方法"
        }}
        ```
        """
        
        response_text = self.llm_client.call_openai(
            prompt=prompt,
            system_prompt="あなたはコード変換の専門家で、詳細な変換計画を作成します。",
            model=CONFIG["llm"]["planning_model"],
            temperature=0.2,
            max_tokens=2000
        )
        
        # 計画を返す
        return response_text


def create_converter_agent() -> ConverterAgent:
    """
    変換エージェントを作成して返します。
    
    Returns:
        設定済みの変換エージェント
    """
    # システムプロンプト
    prompt_path = os.path.join(CONFIG["system"]["prompt_dir"], "converter_prompt.txt")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            system_prompt = f.read()
    except:
        # デフォルトのプロンプト
        system_prompt = """あなたはPerlからPythonへのコード変換エージェントです。

<変換プロセス>
1. Perlコードを解析して構造と機能を理解する
2. コードを論理的なセグメントに分割する
3. 各セグメントをPythonに変換する
4. 変換されたコードをテストして検証する
5. エラーがあれば修正する
6. コードベース全体が正常に変換されるまで繰り返す
</変換プロセス>

<変換ルール>
- 何よりも元のコードの機能を維持する
- Perl構文をPythonの慣用的な表現に変換する
- Perl特有の構文（特殊変数など）を適切に処理する
- コードの構造と編成を維持する
- コメントとドキュメントを保持し、必要に応じて翻訳する
- 元のコードと変換されたコードの関係を追跡する
</変換ルール>

<一般的なPerl-Python変換マッピング>
- Perlハッシュ → Python辞書
- Perl配列 → Pythonリスト
- Perlリファレンス → Pythonオブジェクト
- Perl正規表現 → Pythonのreモジュール
- Perlファイルハンドル → Pythonファイルオブジェクト
- Perlモジュール → Pythonモジュール/パッケージ
- Perl特殊変数 → Python適切な同等物
- Perl OOP → Pythonクラスとメソッド
</一般的なPerl-Python変換マッピング>
"""
    
    # LLMクライアント
    llm_client = OpenAIClient(use_langchain=CONFIG["llm"].get("use_langchain", False))
    
    # ツールレジストリ
    registry = ToolRegistry()
    
    for mod in [
        "tools.message_tools",
        "tools.shell_tools",
        "tools.file_tools",
        "tools.perl_tools",
        "tools.codeact_tools",
        "tools.system_tools",
    ]:
        registry.register_tools_from_module(mod)
    
    # プランナー
    planner = ConversionPlanner(llm_client)
    
    # メモリ
    if CONFIG["memory"].get("use_vector_memory", False):
        memory = EnhancedMemory(workspace_dir=CONFIG["system"]["workspace_dir"])
    else:
        memory = Memory(workspace_dir=CONFIG["system"]["workspace_dir"])
    
    # エージェントを作成して返す
    return ConverterAgent(llm_client, system_prompt, registry, planner, memory)
