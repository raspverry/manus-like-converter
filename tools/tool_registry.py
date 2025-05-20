# tools/tool_registry.py
"""
強化されたツールレジストリ：ツールを登録・取得・実行するクラス。
CodeActパラダイムのサポートとトレーサビリティを強化。
"""
from core.logging_config import logger
import json
import importlib
import functools
import time
import traceback
from typing import Dict, Any, Callable, Optional, List



def tool(name: str, description: str, parameters: Dict[str, Any]):
    """
    ツール関数用デコレータ。関数に'tool_spec'属性を追加し、ToolRegistryで自動登録できるようにします。
    
    Args:
        name: ツールの名前
        description: ツールの説明
        parameters: JSONスキーマ形式のパラメータ定義
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        
        # 関数にツール仕様を追加
        wrapper.tool_spec = {
            "name": name,
            "description": description,
            "parameters": parameters
        }
        
        return wrapper
    
    return decorator

class ToolRegistry:
    def __init__(self):
        self.tools = {}
        self.tool_specs = {}
        self.tool_history = []  # ツール使用履歴
        self.max_history = 100  # 履歴の最大サイズ
    
    def register_tool(self, name: str, func: Callable, spec: Dict[str, Any]):
        """
        ツールを登録します。
        
        Args:
            name: ツールの名前
            func: ツール関数
            spec: ツール仕様
        """
        self.tools[name] = func
        self.tool_specs[name] = spec
        logger.info(f"ツール登録: {name}")
    
    def register_tools_from_module(self, module_name: str):
        """
        モジュールからツールを自動登録します。
        
        Args:
            module_name: ツールを含むモジュール名
        """
        try:
            mod = importlib.import_module(module_name)
            registered_count = 0
            
            for attr_name in dir(mod):
                if attr_name.startswith("_"):
                    continue
                attr = getattr(mod, attr_name)
                if callable(attr) and hasattr(attr, "tool_spec"):
                    self.register_tool(attr.tool_spec["name"], attr, attr.tool_spec)
                    registered_count += 1
            
            logger.info(f"モジュール '{module_name}' から {registered_count} 個のツールを登録しました")
        except Exception as e:
            logger.error(f"ツール登録中エラー: {str(e)}")
            logger.error(traceback.format_exc())
    
    def get_tool_names(self) -> List[str]:
        """
        登録されているツール名のリストを取得します。
        
        Returns:
            ツール名のリスト
        """
        return list(self.tools.keys())
    
    def get_tool_spec(self, name: str) -> Optional[Dict[str, Any]]:
        """
        ツール仕様を取得します。
        
        Args:
            name: ツール名
            
        Returns:
            ツール仕様、存在しない場合はNone
        """
        return self.tool_specs.get(name)
    
    def get_tool_specs(self) -> Dict[str, Dict[str, Any]]:
        """
        すべてのツール仕様を取得します。
        
        Returns:
            ツール名をキー、仕様を値とする辞書
        """
        return self.tool_specs.copy()
    
    def execute_tool(self, name: str, params: Dict[str, Any]) -> Any:
        """
        ツールを実行します。
        
        Args:
            name: 実行するツールの名前
            params: ツールに渡すパラメータ
            
        Returns:
            ツール実行の結果
            
        Raises:
            ValueError: ツールが登録されていない場合
            Exception: ツール実行中にエラーが発生した場合
        """
        start_time = time.time()
        
        if name not in self.tools:
            raise ValueError(f"ツール '{name}' は登録されていません")
        
        func = self.tools[name]
        
        try:
            # 実行前にログ記録
            params_str = json.dumps(params, ensure_ascii=False)
            logger.info(f"ツール実行開始: {name}({params_str})")
            
            # ツール実行
            result = func(**params)
            
            # 実行時間の計算
            execution_time = time.time() - start_time
            
            # 履歴に追加
            self._add_to_history(name, params, result, execution_time)
            
            # 実行後のログ記録
            logger.info(f"ツール実行完了: {name} (実行時間: {execution_time:.2f}秒)")
            
            return result
        except Exception as e:
            # エラー情報を記録
            execution_time = time.time() - start_time
            logger.error(f"ツール '{name}' 実行中にエラー: {str(e)}")
            logger.error(traceback.format_exc())
            
            # 履歴に追加
            self._add_to_history(name, params, f"ERROR: {str(e)}", execution_time, error=True)
            
            # エラーを再度発生
            raise
    
    def _add_to_history(self, name: str, params: Dict[str, Any], result: Any, execution_time: float, error: bool = False):
        """
        ツール実行履歴に追加します。
        
        Args:
            name: ツール名
            params: 実行パラメータ
            result: 実行結果
            execution_time: 実行時間（秒）
            error: エラーが発生したかどうか
        """
        # 結果を文字列に変換（大きすぎる場合は切り詰める）
        if isinstance(result, str) and len(result) > 500:
            result_str = result[:500] + "..."
        else:
            try:
                result_str = str(result)[:500]
                if len(str(result)) > 500:
                    result_str += "..."
            except:
                result_str = "表示不可能な結果"
        
        # 履歴に追加
        history_entry = {
            "timestamp": time.time(),
            "tool": name,
            "params": params,
            "result": result_str,
            "execution_time": execution_time,
            "error": error
        }
        
        self.tool_history.append(history_entry)
        
        # 履歴サイズを制限
        if len(self.tool_history) > self.max_history:
            self.tool_history = self.tool_history[-self.max_history:]
    
    def get_recent_tools_usage(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        最近のツール使用履歴を取得します。
        
        Args:
            limit: 取得する履歴の最大数
            
        Returns:
            ツール使用履歴のリスト
        """
        return self.tool_history[-limit:]
    
    def get_tools_usage_stats(self) -> Dict[str, Any]:
        """
        ツール使用統計を取得します。
        
        Returns:
            ツール使用統計の辞書
        """
        if not self.tool_history:
            return {"total_calls": 0, "tools": {}}
        
        # ツールごとの使用回数と平均実行時間を計算
        tools_stats = {}
        for entry in self.tool_history:
            tool_name = entry["tool"]
            execution_time = entry["execution_time"]
            error = entry["error"]
            
            if tool_name not in tools_stats:
                tools_stats[tool_name] = {
                    "calls": 0,
                    "errors": 0,
                    "total_time": 0.0
                }
            
            tools_stats[tool_name]["calls"] += 1
            tools_stats[tool_name]["total_time"] += execution_time
            if error:
                tools_stats[tool_name]["errors"] += 1
        
        # 平均実行時間を計算
        for tool_name, stats in tools_stats.items():
            stats["avg_time"] = stats["total_time"] / stats["calls"]
        
        return {
            "total_calls": len(self.tool_history),
            "tools": tools_stats
        }
