# core/planner.py
"""
タスクをステップに分解するプランナーモジュール。
"""
from core.logging_config import logger
import os
import json
from typing import Dict, Any, List, Optional



class Planner:
    def __init__(self, llm_client):
        self.llm_client = llm_client
        
        # プランニングプロンプトの読み込み
        prompt_dir = os.environ.get("PROMPT_DIR", "prompts")
        try:
            with open(os.path.join(prompt_dir, "planner_prompt.txt"), "r", encoding="utf-8") as f:
                self.planner_prompt = f.read()
        except FileNotFoundError:
            logger.warning("プランナープロンプトファイルが見つかりません。デフォルトを使用します。")
            self.planner_prompt = """
あなたは効率的なタスクプランナーです。
与えられたタスクを具体的で実行可能なステップに分解してください。
プランは以下の形式で提供してください：

```json
{
  "goal": "タスクの全体的な目標",
  "steps": [
    {
      "id": "1",
      "description": "ステップの詳細な説明",
      "reason": "このステップが必要な理由",
      "expected_tool": "使用する可能性の高いツール名（オプション）"
    },
    ...
  ]
}
```
"""
    
    def create_plan(self, task_description: str) -> str:
        """
        LLMを使用してタスクの詳細な計画を生成します。
        
        Args:
            task_description: ユーザーから与えられたタスクの説明
            
        Returns:
            計画のテキスト形式
        """
        # プランニングプロンプトを構築
        prompt = f"{self.planner_prompt}\n\nタスク: {task_description}\n\nプランを作成してください。"
        
        logger.info(f"タスクの計画を作成: {task_description[:80]}...")
        
        try:
            from config import CONFIG
            
            # LLMでプランを生成
            response_text = self.llm_client.call_azure_openai(
                prompt=prompt,
                system_prompt="あなたはManusエージェントのプランニングシステムです。あらゆるタスクを実行可能なステップに分割できます。",
                model=CONFIG["llm"]["planning_model"],
                temperature=0.2,  # プランニングは低温度が適切
                max_tokens=1500
            )
            try:
                # plan_data = json.loads(response_text)
                # 計画を人間可読なテキスト形式に変換
                return self._format_plan_to_text(response_text)
            except json.JSONDecodeError:
                logger.error("計画JSONの解析に失敗しました")
                # フォールバック: 生のテキストを返す
                return self._generate_fallback_plan(response_text, task_description)
            # JSONを抽出 (```json から ``` の間のテキスト)
            # import re
            # json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response_text)
            
            # if json_match:
                # json_str = json_match.group(1)
            #     try:
            #         plan_data = json.loads(json_str)
            #         # 計画を人間可読なテキスト形式に変換
            #         return self._format_plan_to_text(plan_data)
            #     except json.JSONDecodeError:
            #         logger.error("計画JSONの解析に失敗しました")
            #         # フォールバック: 生のテキストを返す
            #         return self._generate_fallback_plan(response_text, task_description)
            # else:
            #     logger.warning("LLMの応答からJSONプランを抽出できませんでした")
            #     return self._generate_fallback_plan(response_text, task_description)
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.error(f"プラン生成中にエラー: {str(e)}")
            # フォールバック: シンプルな計画を手動で生成
            return self._generate_fallback_plan(None, task_description)
    
    def _format_plan_to_text(self, plan_data: Dict[str, Any]) -> str:
        """JSONプランデータをテキスト形式に変換"""
        lines = [f"目標: {plan_data.get('goal', '目標が設定されていません')}", ""]
        
        for i, step in enumerate(plan_data.get("steps", []), 1):
            step_id = step.get("id", str(i))
            description = step.get("description", "説明なし")
            reason = step.get("reason", "")
            
            lines.append(f"{step_id}. {description}")
            if reason:
                lines.append(f"   理由: {reason}")
            
            # 期待されるツールの情報があれば追加
            if "expected_tool" in step:
                lines.append(f"   ツール候補: {step['expected_tool']}")
            
            lines.append("")  # 空行で区切り
        
        return "\n".join(lines)
    
    def _generate_fallback_plan(self, llm_response: Optional[str], task_description: str) -> str:
        """LLMの応答からプランを生成できなかった場合のフォールバックプラン"""
        # LLMからの応答があり、それがある程度構造化されている場合はそれを使用
        if llm_response and len(llm_response) > 50:
            # 単にテキストを段落として返す
            return f"目標: {task_description}\n\n{llm_response}"
        
        # 完全なフォールバック: シンプルな汎用プラン
        return f"""目標: {task_description}

1. タスク分析と要件の理解
2. 必要な情報の収集
3. コードやツールの実行計画
4. 実装または解決策の実行
5. 検証と確認
6. 結果をユーザーに提示
"""
    
    def update_plan(self, current_plan: str, new_info: str) -> str:
        """
        新しい情報に基づいて計画を更新
        
        Args:
            current_plan: 現在の計画
            new_info: 新たに判明した情報や変更点
            
        Returns:
            更新された計画
        """
        # プランの更新用プロンプト
        update_prompt = f"""
以下の現在の計画を、新しい情報に基づいて更新してください。
どのステップが完了したか、どのステップを修正すべきか、新しいステップが必要かを判断してください。

現在の計画:
{current_plan}

新しい情報:
{new_info}

更新された計画を同じフォーマットで提供してください。
"""
        
        try:
            from ..config import CONFIG
            from ..llm.azure_openai_client import call_azure_openai
            
            # LLMでプランを更新
            response_text = call_azure_openai(
                prompt=update_prompt,
                system_prompt="あなたはManusエージェントのプランニングシステムです。既存の計画を新しい情報に基づいて更新します。",
                model=CONFIG["llm"]["planning_model"],
                temperature=0.2,
                max_tokens=1500
            )
            
            # 通常はJSONではなく直接テキスト形式の計画が返ってくる想定
            return response_text
                
        except Exception as e:
            logger.error(f"プラン更新中にエラー: {str(e)}")
            # フォールバック: 元の計画に注記を追加
            return f"{current_plan}\n\n注: 新しい情報が反映されました: {new_info}"
