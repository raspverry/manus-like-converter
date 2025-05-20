# core/memory.py
"""
エージェントのメモリ機能。ファイル操作の記録やタスク進捗を追跡。
"""
from core.logging_config import logger
import os
from typing import Dict, Any



class Memory:
    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir
        self.file_registry = {}
        self.task_progress = {}
        self.variables = {}
    
    def update_from_observation(self, tool_call: Dict[str, Any], result: Any):
        # ファイル書き込みツールやtodoへの書き込み等を追跡
        name = tool_call.get("name", "")
        params = tool_call.get("parameters", {})
        
        if name == "file_write":
            file_path = params.get("file", "")
            if file_path:
                self.file_registry[file_path] = "written"
        
        if name == "file_str_replace":
            file_path = params.get("file", "")
            if file_path:
                self.file_registry[file_path] = "str_replaced"

    def get_relevant_state(self) -> str:
        """
        エージェントがプロンプト構築時に参照する簡易メモリ状態を返す。
        拡張メモリが無い場合でも空文字列で良い。
        """
        state_lines = []

        # 最近書き込まれたファイル（最大 5 件）
        if self.file_registry:
            state_lines.append("【ファイル操作履歴】")
            for i, path in enumerate(list(self.file_registry)[-5:], 1):
                state_lines.append(f"{i}. {os.path.basename(path)} -> {self.file_registry[path]}")

        # 任意の変数
        if self.variables:
            state_lines.append("【変数】")
            for k, v in list(self.variables.items())[-5:]:
                state_lines.append(f"{k}: {v}")

        return "\n".join(state_lines) if state_lines else ""
    
    def get_file_info(self, file_path: str):
        return self.file_registry.get(file_path, None)
