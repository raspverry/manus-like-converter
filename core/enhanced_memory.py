# core/enhanced_memory.py
"""
強化されたメモリモジュール。

このモジュールは従来のファイルベースメモリとFAISSベクトルデータベースを
組み合わせて、より強力なメモリと検索機能を提供します。また、
コードアクトパラダイムのためのメモリ管理機能も強化しています。
"""
import os
from core.logging_config import logger
import json
import time
import re
import random
from typing import Dict, List, Any, Optional, Tuple, Set
from datetime import datetime
import pickle

from core.memory import Memory



class EnhancedMemory(Memory):
    """
    従来のMemoryクラスとFAISSMemoryを組み合わせた拡張メモリクラス。
    
    このクラスは両方のメモリシステムを使用して、ファイルの追跡と
    セマンティック検索の両方の機能を提供します。また、
    コードアクトのためのコード履歴管理も行います。
    """
    
    def __init__(self, workspace_dir: str):
        """
        拡張メモリを初期化します。
        
        Args:
            workspace_dir: 作業ディレクトリのパス
        """
        # 従来のメモリを初期化
        super().__init__(workspace_dir=workspace_dir)
        
        # 拡張機能のデータ構造を初期化
        self.code_history = []  # コード実行履歴
        self.execution_results = []  # 実行結果履歴
        self.knowledge_entries = []  # 収集された知識エントリ
        self.browsing_history = []  # ブラウジング履歴
        self.interaction_history = []  # ユーザーとのやり取り履歴
        
        # ベクトルメモリの初期化
        try:
            # ChromaDBの代わりにFAISSベースのメモリを使用
            from .faiss_memory import FAISSMemory
            self.vector_memory = FAISSMemory(workspace_dir=workspace_dir)
            self._vector_memory_available = True
            logger.info("FAISSベクトルメモリシステムが初期化されました")
        except ImportError as e:
            # FAISSが利用できない場合は警告を表示
            logger.warning(f"ベクトルメモリが利用できません: {str(e)}")
            logger.warning("基本的なメモリのみを使用します")
            self._vector_memory_available = False
        
        # ワークスペースにメモリディレクトリを作成
        self.memory_dir = os.path.join(workspace_dir, ".memory")
        os.makedirs(self.memory_dir, exist_ok=True)
        
        # 永続化されたメモリがあれば読み込む
        self._load_persistent_memory()
    
    def _load_persistent_memory(self):
        """永続化されたメモリを読み込む"""
        memory_file = os.path.join(self.memory_dir, "memory_state.pkl")
        try:
            if os.path.exists(memory_file):
                with open(memory_file, "rb") as f:
                    data = pickle.load(f)
                    
                    # データ構造を復元
                    self.file_registry = data.get("file_registry", {})
                    self.task_progress = data.get("task_progress", {})
                    self.variables = data.get("variables", {})
                    self.code_history = data.get("code_history", [])
                    self.execution_results = data.get("execution_results", [])
                    self.knowledge_entries = data.get("knowledge_entries", [])
                    self.browsing_history = data.get("browsing_history", [])
                    self.interaction_history = data.get("interaction_history", [])
                    
                    logger.info(f"永続化されたメモリを読み込みました（ファイル: {len(self.file_registry)}件、変数: {len(self.variables)}件）")
        except Exception as e:
            logger.error(f"メモリ読み込み中にエラー: {str(e)}")
    
    def _save_persistent_memory(self):
        """メモリ状態を永続化する"""
        memory_file = os.path.join(self.memory_dir, "memory_state.pkl")
        try:
            data = {
                "file_registry": self.file_registry,
                "task_progress": self.task_progress,
                "variables": self.variables,
                "code_history": self.code_history[-50:],  # 最新50件のみ保持
                "execution_results": self.execution_results[-50:],  # 最新50件のみ保持
                "knowledge_entries": self.knowledge_entries,
                "browsing_history": self.browsing_history[-30:],  # 最新30件のみ保持
                "interaction_history": self.interaction_history[-20:],  # 最新20件のみ保持
            }
            
            with open(memory_file, "wb") as f:
                pickle.dump(data, f)
                
            logger.info("メモリ状態を永続化しました")
        except Exception as e:
            logger.error(f"メモリ永続化中にエラー: {str(e)}")
    
    def update_from_observation(self, tool_call: Dict[str, Any], result: Any) -> None:
        """
        ツール実行の観察に基づいてメモリを更新します。
        
        Args:
            tool_call: 実行されたツール呼び出し
            result: ツール実行の結果
        """
        # 従来のメモリを更新
        super().update_from_observation(tool_call, result)
        
        # メモリ管理を強化
        tool_name = tool_call.get("name", "")
        params = tool_call.get("parameters", {})
        
        # コード履歴の記録 (CodeActパラダイム)
        if tool_name == "code_execute":
            code = params.get("code", "")
            description = params.get("description", "未指定")
            
            if code:
                # コード履歴に追加
                self.code_history.append({
                    "timestamp": time.time(),
                    "code": code,
                    "description": description,
                    "result_snippet": str(result)[:200] + ("..." if len(str(result)) > 200 else ""),
                })
                
                # 実行結果も記録
                self.execution_results.append({
                    "timestamp": time.time(),
                    "tool": tool_name,
                    "code_snippet": code[:50] + ("..." if len(code) > 50 else ""),
                    "result": result,
                })
                
                # ベクトルメモリに追加
                if self._vector_memory_available:
                    self.vector_memory.add_document(
                        text=f"コード: {code}\n\n実行結果: {result}",
                        source=f"code_execution:{time.time()}",
                        metadata={
                            "type": "code_execution",
                            "description": description,
                            "timestamp": time.time()
                        }
                    )
        
        # データ分析の記録
        elif tool_name == "codeact_data_analysis":
            code = params.get("code", "")
            data_file = params.get("data_file", "")
            
            if code and data_file:
                # 分析履歴に追加
                self.execution_results.append({
                    "timestamp": time.time(),
                    "tool": tool_name,
                    "data_file": data_file,
                    "code_snippet": code[:50] + ("..." if len(code) > 50 else ""),
                    "result_snippet": str(result)[:200] + ("..." if len(str(result)) > 200 else ""),
                })
                
                # ベクトルメモリに追加
                if self._vector_memory_available:
                    self.vector_memory.add_document(
                        text=f"データファイル: {data_file}\nコード: {code}\n\n分析結果: {result}",
                        source=f"data_analysis:{os.path.basename(data_file)}",
                        metadata={
                            "type": "data_analysis",
                            "data_file": data_file,
                            "timestamp": time.time()
                        }
                    )
        
        # ファイル操作から知識を獲得
        elif tool_name == "file_write":
            file_path = params.get("file", "")
            content = params.get("content", "")
            
            if file_path and content and len(content) > 10:
                # コンテキストファイルの場合は特別扱い
                context_files = ["todo.md", "notes.md", "plan.md", "report.md", "summary.md"]
                if any(os.path.basename(file_path).lower() == cf for cf in context_files):
                    self.variables["last_updated_context_file"] = file_path
                    self.variables["last_context_update_time"] = time.time()
                
                # ベクトルメモリに追加
                if self._vector_memory_available:
                    self.vector_memory.add_document(
                        text=content,
                        source=f"file:{os.path.basename(file_path)}",
                        metadata={
                            "file_path": file_path,
                            "operation": "write",
                            "timestamp": time.time()
                        }
                    )
        
        # ブラウザや検索結果から知識を獲得
        elif tool_name in ["browser_navigate", "browser_extract_elements", "browser_extract_structured_data"]:
            url = params.get("url", "")
            
            # URLがなくても現在のページを処理
            if isinstance(result, str) and len(result) > 100:
                source = f"web:{url}" if url else "web:current_page"
                
                # ブラウジング履歴に追加
                self.browsing_history.append({
                    "timestamp": time.time(),
                    "url": url or "current_page",
                    "action": tool_name,
                    "result_snippet": result[:200] + ("..." if len(result) > 200 else ""),
                })
                
                # ベクトルメモリに追加
                if self._vector_memory_available:
                    self.vector_memory.add_document(
                        text=result,
                        source=source,
                        metadata={
                            "url": url or "current_page",
                            "operation": tool_name,
                            "timestamp": time.time()
                        }
                    )
        
        elif tool_name == "info_search_web" and isinstance(result, str) and len(result) > 100:
            query = params.get("query", "")
            
            if query:
                # 検索履歴に追加
                self.knowledge_entries.append({
                    "timestamp": time.time(),
                    "query": query,
                    "result_snippet": result[:200] + ("..." if len(result) > 200 else ""),
                })
                
                # ベクトルメモリに追加
                if self._vector_memory_available:
                    self.vector_memory.add_document(
                        text=f"検索クエリ: {query}\n\n検索結果: {result}",
                        source=f"search:{query}",
                        metadata={
                            "query": query,
                            "operation": "search",
                            "timestamp": time.time()
                        }
                    )
        
        # ユーザーとのやり取りを記録
        elif tool_name in ["message_notify_user", "message_ask_user"]:
            message_text = params.get("text", "")
            
            if message_text:
                message_type = "通知" if tool_name == "message_notify_user" else "質問"
                self.interaction_history.append({
                    "timestamp": time.time(),
                    "type": message_type,
                    "message": message_text,
                    "response": result if tool_name == "message_ask_user" else None
                })
        
        # 定期的にメモリを永続化
        if random.random() < 0.1:  # 約10%の確率で保存（頻度を下げる）
            self._save_persistent_memory()
    
    def get_relevant_state(self) -> str:
        """
        現在のメモリ状態の関連する要約を取得します。
        
        Returns:
            現在のメモリ状態の文字列記述
        """
        # 従来のメモリ状態を取得
        traditional_state = super().get_relevant_state()
        
        # 拡張状態情報を追加
        enhanced_state = []
        
        # コンテキストファイル情報
        context_files = self._get_context_files_summary()
        if context_files:
            enhanced_state.append("【コンテキストファイル情報】")
            enhanced_state.append(context_files)
        
        # 最近の実行コード履歴
        if self.code_history:
            enhanced_state.append("【最近のコード実行】")
            recent_codes = self.code_history[-3:]  # 最新3件
            for i, code_entry in enumerate(reversed(recent_codes), 1):
                timestamp = datetime.fromtimestamp(code_entry["timestamp"]).strftime("%H:%M:%S")
                desc = code_entry["description"]
                enhanced_state.append(f"{i}. [{timestamp}] {desc}")
        
        # 最近のブラウジング履歴
        if self.browsing_history:
            enhanced_state.append("【最近のブラウジング】")
            recent_browsing = self.browsing_history[-3:]  # 最新3件
            for i, browse_entry in enumerate(reversed(recent_browsing), 1):
                timestamp = datetime.fromtimestamp(browse_entry["timestamp"]).strftime("%H:%M:%S")
                url = browse_entry["url"]
                enhanced_state.append(f"{i}. [{timestamp}] {url}")
        
        # 結合して返す
        if enhanced_state:
            return traditional_state + "\n\n" + "\n".join(enhanced_state)
        else:
            return traditional_state
    
    def _get_context_files_summary(self) -> str:
        """コンテキストファイルの概要を取得"""
        context_files = ["todo.md", "notes.md", "plan.md", "report.md", "summary.md"]
        found_files = []
        
        for cf in context_files:
            for file_path in self.file_registry:
                if os.path.basename(file_path).lower() == cf.lower():
                    state = self.file_registry[file_path]
                    found_files.append(f"- {os.path.basename(file_path)}: {state}")
                    break
        
        if found_files:
            return "\n".join(found_files)
        else:
            return ""
    
    def _expand_query(self, query: str) -> str:
        """
        検索クエリを拡張して関連性の幅を広げます。
        
        Args:
            query: 元のクエリ
            
        Returns:
            拡張されたクエリ
        """
        # 基本的なクエリ拡張（実際の実装ではより高度な手法を使用可能）
        # 例：キーワード抽出、同義語追加など
        expanded_terms = []
        
        # クエリから主要キーワードを抽出
        words = query.split()
        keywords = [word for word in words if len(word) > 3 and word.lower() not in 
                   ['with', 'that', 'this', 'from', 'what', 'when', 'where', 'which', 'about']]
        
        # 拡張クエリの作成
        if keywords:
            expanded_query = f"{query} {' '.join(keywords)}"
            return expanded_query
        
        return query
    
    def _rerank_results(self, results: List[Tuple[str, Dict[str, Any], float]], query: str) -> List[Tuple[str, Dict[str, Any], float]]:
        """
        検索結果を再ランク付けします。
        
        Args:
            results: 元の検索結果（テキスト、メタデータ、スコアのタプルリスト）
            query: 元のクエリ
            
        Returns:
            再ランク付けされた結果
        """
        if not results:
            return results
        
        # クエリ内の重要キーワードを抽出
        query_keywords = set([w.lower() for w in query.split() if len(w) > 3])
        
        # 各結果のスコアを再計算
        scored_results = []
        for text, metadata, original_score in results:
            # 基本スコアは元のベクトル類似度
            new_score = original_score
            
            # テキスト内のキーワード一致でボーナス
            for keyword in query_keywords:
                if keyword in text.lower():
                    new_score += 0.1  # キーワード一致ボーナス
            
            # 最近のエントリにボーナス
            if 'timestamp' in metadata:
                time_diff = time.time() - metadata['timestamp']
                if time_diff < 3600:  # 1時間以内
                    new_score += 0.1
                elif time_diff < 86400:  # 24時間以内
                    new_score += 0.05
            
            # メタデータタイプによるボーナス（例：コード実行結果は価値が高い）
            if metadata.get('type') == 'code_execution':
                new_score += 0.1
            
            scored_results.append((text, metadata, new_score))
        
        # スコアで降順ソート
        return sorted(scored_results, key=lambda x: x[2], reverse=True)
    
    def _format_knowledge_results(self, results: List[Tuple[str, Dict[str, Any], float]]) -> str:
        """
        検索結果を読みやすくフォーマットします。
        
        Args:
            results: ランク付けされた結果リスト
            
        Returns:
            フォーマットされたテキスト
        """
        if not results:
            return "関連情報は見つかりませんでした。"
        
        formatted_lines = ["## 関連知識"]
        
        for i, (text, metadata, score) in enumerate(results, 1):
            # メタデータからソース情報を抽出
            source_type = metadata.get('type', 'unknown')
            source = metadata.get('source', 'unknown')
            timestamp = metadata.get('timestamp', 0)
            time_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S') if timestamp else 'N/A'
            
            # エントリタイプに応じたヘッダーを作成
            if source_type == 'code_execution':
                header = f"### {i}. コード実行結果 (関連度: {score:.2f})"
            elif source_type == 'data_analysis':
                data_file = metadata.get('data_file', 'unknown')
                header = f"### {i}. データ分析: {os.path.basename(data_file)} (関連度: {score:.2f})"
            elif source.startswith('web:'):
                url = source.replace('web:', '')
                header = f"### {i}. Web情報: {url} (関連度: {score:.2f})"
            elif source.startswith('search:'):
                query = source.replace('search:', '')
                header = f"### {i}. 検索結果: '{query}' (関連度: {score:.2f})"
            elif source.startswith('file:'):
                filename = source.replace('file:', '')
                header = f"### {i}. ファイル: {filename} (関連度: {score:.2f})"
            else:
                header = f"### {i}. 関連情報 (関連度: {score:.2f})"
            
            # 結果テキストを加工（長すぎる場合は切り詰める）
            if len(text) > 500:
                display_text = text[:500] + "..."
            else:
                display_text = text
            
            # 最終的な結果エントリ
            formatted_lines.extend([
                header,
                f"時間: {time_str}",
                f"内容:",
                f"{display_text}",
                ""  # 空行を追加
            ])
        
        return "\n".join(formatted_lines)
    
    def get_relevant_knowledge(self, query: str, limit: int = 3) -> str:
        """
        クエリに関連する知識を取得します。
        
        Args:
            query: 検索クエリ
            limit: 返す結果の最大数
            
        Returns:
            関連知識のテキスト
        """
        if not self._vector_memory_available:
            return "ベクトルメモリシステムが利用できないため、関連知識を取得できません。"
        
        # クエリを拡張
        expanded_query = self._expand_query(query)
        
        # 関連コンテキストを取得
        results = self.vector_memory.search(expanded_query, limit)
        
        # 結果の再ランク付け
        reranked_results = self._rerank_results(results, query)
        
        # 結果のフォーマット
        return self._format_knowledge_results(reranked_results)
    
    def get_code_history_summary(self, limit: int = 5) -> str:
        """
        実行されたコードの履歴概要を取得します。
        
        Args:
            limit: 返す結果の最大数
            
        Returns:
            コード履歴の概要
        """
        if not self.code_history:
            return "コード実行履歴はありません。"
        
        recent_history = self.code_history[-limit:]
        
        lines = ["## 最近のコード実行履歴"]
        for i, entry in enumerate(reversed(recent_history), 1):
            timestamp = datetime.fromtimestamp(entry["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            description = entry["description"]
            result_snippet = entry["result_snippet"]
            
            lines.append(f"### {i}. {description} ({timestamp})")
            lines.append("```python")
            lines.append(entry["code"][:300] + ("..." if len(entry["code"]) > 300 else ""))
            lines.append("```")
            lines.append(f"結果: {result_snippet}")
            lines.append("")
        
        return "\n".join(lines)
    
    def get_browsing_history_summary(self, limit: int = 5) -> str:
        """
        ブラウジング履歴の概要を取得します。
        
        Args:
            limit: 返す結果の最大数
            
        Returns:
            ブラウジング履歴の概要
        """
        if not self.browsing_history:
            return "ブラウジング履歴はありません。"
        
        recent_history = self.browsing_history[-limit:]
        
        lines = ["## 最近のブラウジング履歴"]
        for i, entry in enumerate(reversed(recent_history), 1):
            timestamp = datetime.fromtimestamp(entry["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            url = entry["url"]
            action = entry["action"]
            
            lines.append(f"{i}. [{timestamp}] {action}: {url}")
        
        return "\n".join(lines)
    
    def add_user_interaction(self, user_message: str, agent_response: str) -> None:
        """
        ユーザーとエージェントの対話をメモリに追加します。
        
        Args:
            user_message: ユーザーのメッセージ
            agent_response: エージェントの応答
        """
        # インタラクション履歴に追加
        self.interaction_history.append({
            "timestamp": time.time(),
            "type": "対話",
            "user_message": user_message,
            "agent_response": agent_response
        })
        
        if self._vector_memory_available:
            self.vector_memory.add_conversation(user_message, agent_response)
            
        # メモリを永続化
        self._save_persistent_memory()
    
    def store_knowledge(self, topic: str, content: str, source: str = "unknown") -> None:
        """
        新しい知識エントリをメモリに保存します。
        
        Args:
            topic: 知識のトピック
            content: 知識の内容
            source: 知識のソース
        """
        # 知識エントリに追加
        self.knowledge_entries.append({
            "timestamp": time.time(),
            "topic": topic,
            "content": content,
            "source": source
        })
        
        # ベクトルメモリにも追加
        if self._vector_memory_available:
            self.vector_memory.add_document(
                text=f"トピック: {topic}\n\n{content}",
                source=f"knowledge:{source}",
                metadata={
                    "topic": topic,
                    "source": source,
                    "timestamp": time.time()
                }
            )
            
        # メモリを永続化
        self._save_persistent_memory()
    
    def get_todo_status(self) -> Dict[str, Any]:
        """
        ToDo.mdの状態を解析して取得します。
        
        Returns:
            ToDoの状態を含む辞書
        """
        todo_file = os.path.join(self.workspace_dir, "todo.md")
        if not os.path.exists(todo_file):
            return {"exists": False, "items": [], "completed": 0, "total": 0}
        
        try:
            with open(todo_file, "r", encoding="utf-8") as f:
                content = f.read()
            
            # タスク項目を抽出
            task_pattern = r"- \[([ x])\] (.*)"
            tasks = re.findall(task_pattern, content)
            
            # 完了/未完了をカウント
            total = len(tasks)
            completed = sum(1 for status, _ in tasks if status == "x")
            
            # タスクリストを作成
            items = []
            for status, task_text in tasks:
                items.append({
                    "completed": status == "x",
                    "text": task_text.strip()
                })
            
            return {
                "exists": True,
                "items": items,
                "completed": completed,
                "total": total,
                "progress_percent": (completed / total * 100) if total > 0 else 0
            }
        except Exception as e:
            logger.error(f"ToDo状態解析中にエラー: {str(e)}")
            return {"exists": True, "error": str(e), "items": [], "completed": 0, "total": 0}
    
    def save_variable(self, key: str, value: Any) -> None:
        """
        変数を保存します。
        
        Args:
            key: 変数名
            value: 変数の値
        """
        self.variables[key] = value
        
        # メモリを永続化
        if random.random() < 0.2:  # 20%の確率で保存
            self._save_persistent_memory()
    
    def get_variable(self, key: str, default: Any = None) -> Any:
        """
        保存された変数を取得します。
        
        Args:
            key: 変数名
            default: 変数が存在しない場合のデフォルト値
            
        Returns:
            変数の値またはデフォルト値
        """
        return self.variables.get(key, default)
    
    def clear_task_related_memory(self) -> None:
        """タスク関連のメモリをクリアする"""
        # コード履歴は残しつつ、タスク関連のメモリをクリア
        self.task_progress = {}
        self.browsing_history = []
        
        # メモリを永続化
        self._save_persistent_memory()
        
        logger.info("タスク関連のメモリをクリアしました")
