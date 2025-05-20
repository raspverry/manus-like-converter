# core/faiss_memory.py
"""
FAISSを使用したベクトルメモリ実装。
ChromaDBの代替としてより簡単にインストールできるFAISSを使用。
"""
import os
from core.logging_config import logger
import time
import json
import pickle
import numpy as np
from typing import Dict, List, Any, Optional, Tuple

from sentence_transformers import SentenceTransformer

try:
    import faiss
except ImportError:
    logging.error("FAISSがインストールされていません。'uv add faiss-cpu' を実行してください。")
    raise



class FAISSMemory:
    """
    FAISSを使用したベクトルメモリ実装。
    """
    
    def __init__(self, workspace_dir: str, embedding_model: str = "all-MiniLM-L6-v2"):
        """
        FAISSベースのベクトルメモリを初期化。
        
        Args:
            workspace_dir: ワークスペースディレクトリのパス
            embedding_model: 使用する文埋め込みモデル名
        """
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.db_dir = os.path.join(self.workspace_dir, ".vector_db")
        os.makedirs(self.db_dir, exist_ok=True)
        
        self.index_path = os.path.join(self.db_dir, "faiss_index.bin")
        self.metadata_path = os.path.join(self.db_dir, "faiss_metadata.json")
        
        # 埋め込みモデルの初期化
        self.model = SentenceTransformer(embedding_model)
        self.embedding_dim = self.model.get_sentence_embedding_dimension()
        
        # インデックスと関連データの初期化/読み込み
        self.index = None
        self.documents = []  # テキストドキュメント
        self.metadata = []   # 各ドキュメントに関連するメタデータ
        self.load_or_create_index()
        
        logger.info(f"FAISSメモリシステムが初期化されました (埋め込み次元: {self.embedding_dim})")
    
    def load_or_create_index(self):
        """既存のインデックスを読み込むか、新しいインデックスを作成"""
        try:
            if os.path.exists(self.index_path) and os.path.exists(self.metadata_path):
                # インデックスの読み込み
                self.index = faiss.read_index(self.index_path)
                
                # メタデータの読み込み
                with open(self.metadata_path, 'r', encoding='utf-8') as f:
                    metadata_dict = json.load(f)
                    self.documents = metadata_dict.get('documents', [])
                    self.metadata = metadata_dict.get('metadata', [])
                
                logger.info(f"既存のFAISSインデックスを読み込みました (ドキュメント数: {len(self.documents)})")
            else:
                # 新しいインデックスの作成
                self.index = faiss.IndexFlatL2(self.embedding_dim)
                self.documents = []
                self.metadata = []
                self.save_index()
                logger.info("新しいFAISSインデックスを作成しました")
        except Exception as e:
            logger.error(f"インデックス読み込み/作成中にエラー: {str(e)}")
            # フォールバック: 新しいインデックスを作成
            self.index = faiss.IndexFlatL2(self.embedding_dim)
            self.documents = []
            self.metadata = []
    
    def save_index(self):
        """インデックスとメタデータをディスクに保存"""
        try:
            # インデックスの保存
            faiss.write_index(self.index, self.index_path)
            
            # メタデータの保存
            metadata_dict = {
                'documents': self.documents,
                'metadata': self.metadata
            }
            with open(self.metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata_dict, f, ensure_ascii=False, indent=2)
            
            logger.info(f"FAISSインデックスを保存しました (ドキュメント数: {len(self.documents)})")
        except Exception as e:
            logger.error(f"インデックス保存中にエラー: {str(e)}")
    
    def add_document(self, text: str, source: str, metadata: Dict[str, Any] = None):
        """
        ドキュメントをインデックスに追加
        
        Args:
            text: ドキュメントテキスト
            source: 情報源の識別子
            metadata: 関連するメタデータ
        """
        if not text or len(text.strip()) < 10:
            return
        
        try:
            # メタデータの準備
            doc_metadata = metadata or {}
            doc_metadata.update({
                'source': source,
                'timestamp': time.time()
            })
            
            # テキストの埋め込み
            embedding = self.model.encode([text])[0]  # 1つのテキストの埋め込みを取得
            embedding_np = np.array([embedding]).astype('float32')
            
            # インデックスに追加
            self.index.add(embedding_np)
            self.documents.append(text)
            self.metadata.append(doc_metadata)
            
            # 定期的に保存
            if len(self.documents) % 10 == 0:
                self.save_index()
                
            logger.info(f"ドキュメントをFAISSインデックスに追加しました (source: {source})")
            return True
        except Exception as e:
            logger.error(f"ドキュメント追加中にエラー: {str(e)}")
            return False
    
    def add_conversation(self, user_message: str, agent_response: str):
        """
        会話をインデックスに追加
        
        Args:
            user_message: ユーザーのメッセージ
            agent_response: エージェントの応答
        """
        conversation_text = f"ユーザー: {user_message}\nエージェント: {agent_response}"
        return self.add_document(
            text=conversation_text,
            source="conversation",
            metadata={
                'type': 'conversation',
                'user_message': user_message[:100],  # 長すぎる場合は切り詰める
            }
        )
    
    def search(self, query: str, limit: int = 3) -> List[Tuple[str, Dict[str, Any], float]]:
        """
        クエリに近いドキュメントを検索
        
        Args:
            query: 検索クエリ
            limit: 返す結果の最大数
            
        Returns:
            (ドキュメント, メタデータ, スコア) のタプルのリスト
        """
        if not query or len(self.documents) == 0:
            return []
        
        try:
            # クエリの埋め込み
            query_embedding = self.model.encode([query])[0]
            query_embedding_np = np.array([query_embedding]).astype('float32')
            
            # 検索実行
            limit = min(limit, len(self.documents))  # インデックスサイズより大きくならないように
            distances, indices = self.index.search(query_embedding_np, limit)
            
            # 結果の整形
            results = []
            for i, idx in enumerate(indices[0]):
                if idx < len(self.documents):  # 安全チェック
                    results.append((
                        self.documents[idx],
                        self.metadata[idx],
                        float(distances[0][i])
                    ))
            
            return results
        except Exception as e:
            logger.error(f"検索中にエラー: {str(e)}")
            return []
    
    def get_relevant_context(self, query: str, limit: int = 3) -> str:
        """
        クエリに関連する文脈情報を取得してフォーマットされたテキストとして返す
        
        Args:
            query: 検索クエリ
            limit: 返す結果の最大数
            
        Returns:
            関連情報のテキスト
        """
        results = self.search(query, limit)
        
        if not results:
            return "関連情報は見つかりませんでした。"
        
        # 結果をテキスト形式でフォーマット
        formatted_results = []
        for i, (text, meta, score) in enumerate(results, 1):
            source = meta.get('source', 'unknown')
            timestamp = meta.get('timestamp', 0)
            
            # タイムスタンプをフォーマット
            from datetime import datetime
            time_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S') if timestamp else 'N/A'
            
            # テキストが長すぎる場合は切り詰める
            text_preview = text[:300] + "..." if len(text) > 300 else text
            
            formatted_results.append(
                f"関連情報 {i}:\n"
                f"出典: {source}\n"
                f"時間: {time_str}\n"
                f"関連度: {score:.2f}\n"
                f"内容:\n{text_preview}\n"
            )
        
        return "\n".join(formatted_results)
