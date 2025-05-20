# llm/openai_client.py
"""
OpenAI / LangChain クライアント
====================================================
* OpenAI API を利用して ChatCompletion を呼び出す
* LangChain を利用した統合もサポート
* JSON モード対応
* トークン使用量を含む usage 辞書を返却
"""

from __future__ import annotations
import os
import re
import json
import logging
from typing import Any, Dict, List, Tuple, Optional

from openai import OpenAI
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from config import CONFIG

# ロガーの設定
logger = logging.getLogger(__name__)

class OpenAIClient:
    """OpenAI および LangChain 対応のクライアント。"""

    def __init__(self, use_langchain: bool = False) -> None:
        """
        OpenAI クライアントを初期化します。
        
        Args:
            use_langchain: LangChain を使用するかどうか
        """
        # APIキーの確認
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise EnvironmentError("OPENAI_API_KEY 環境変数が設定されていません。")
        
        # モデル名の取得
        self.model_name = os.getenv("LLM_MODEL", CONFIG["llm"]["model"])
        
        # LangChain 使用フラグの設定
        self.use_langchain = use_langchain
        
        # クライアントの初期化
        if use_langchain:
            self._init_langchain_client()
        else:
            self._init_openai_client()
        
        logger.info(f"OpenAI クライアント初期化完了 (model: {self.model_name}, LangChain: {use_langchain})")

    def _init_openai_client(self):
        """OpenAI 公式クライアントを初期化"""
        self._client = OpenAI(api_key=self.api_key)
    
    def _init_langchain_client(self):
        """LangChain クライアントを初期化"""
        self._langchain_client = ChatOpenAI(
            model_name=self.model_name,
            openai_api_key=self.api_key,
            temperature=CONFIG["llm"]["temperature"],
            max_tokens=CONFIG["llm"]["max_tokens"]
        )

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        force_json: bool = False,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        ChatCompletion 呼び出し。

        Args:
            messages: ChatCompletion メッセージ
            temperature: 温度パラメータ
            max_tokens: 最大トークン数
            force_json: JSON 形式での応答を強制するかどうか
            
        Returns:
            content: 生成テキスト
            usage:   {prompt_tokens, completion_tokens, total_tokens}
        """
        if self.use_langchain:
            return self._langchain_chat_completion(messages, temperature, max_tokens, force_json)
        else:
            return self._openai_chat_completion(messages, temperature, max_tokens, force_json)

    def _openai_chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        force_json: bool,
    ) -> Tuple[str, Dict[str, Any]]:
        """OpenAI 公式クライアントでの ChatCompletion 呼び出し"""
        params: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        # JSON形式を強制する場合
        if force_json:
            params["response_format"] = {"type": "json_object"}

        try:
            response = self._client.chat.completions.create(**params)
            
            # 応答から内容を抽出
            content = response.choices[0].message.content or ""
            
            # 使用量情報を抽出
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            }
            
            # JSONモードが強制されていない場合でもJSONを抽出
            if force_json or self._is_json_content(content):
                return self._extract_json(content), usage
            
            return content, usage
        except Exception as exc:
            logger.error(f"OpenAI 呼び出し失敗: {exc}")
            raise

    def _langchain_chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        force_json: bool,
    ) -> Tuple[str, Dict[str, Any]]:
        """LangChain クライアントでの ChatCompletion 呼び出し"""
        # メッセージを LangChain 形式に変換
        langchain_messages = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            
            if role == "system":
                langchain_messages.append(SystemMessage(content=content))
            elif role == "user":
                langchain_messages.append(HumanMessage(content=content))
            # その他のメッセージタイプは必要に応じて追加
        
        # パラメータを設定
        self._langchain_client.temperature = temperature
        self._langchain_client.max_tokens = max_tokens
        
        try:
            # LangChain で呼び出し
            response = self._langchain_client.invoke(langchain_messages)
            content = response.content
            
            # 使用量情報を抽出
            usage = {}
            if hasattr(response, 'response_metadata') and response.response_metadata:
                token_usage = response.response_metadata.get('token_usage', {})
                usage = {
                    "prompt_tokens": token_usage.get('prompt_tokens', 0),
                    "completion_tokens": token_usage.get('completion_tokens', 0),
                    "total_tokens": token_usage.get('total_tokens', 0)
                }
            
            # JSONモードが強制されていない場合でもJSONを抽出
            if force_json or self._is_json_content(content):
                return self._extract_json(content), usage
            
            return content, usage
        except Exception as exc:
            logger.error(f"LangChain 呼び出し失敗: {exc}")
            raise

    def _is_json_content(self, content: str) -> bool:
        """コンテンツがJSON形式かどうかを判定"""
        if not content:
            return False
        
        # JSONブロックの検索
        json_pattern = r'```json\s*(.*?)\s*```'
        json_match = re.search(json_pattern, content, re.DOTALL)
        if json_match:
            return True
            
        # 単純なJSON形式かどうか
        try:
            content_stripped = content.strip()
            if content_stripped.startswith('{') and content_stripped.endswith('}'):
                json.loads(content_stripped)
                return True
        except json.JSONDecodeError:
            pass
            
        return False

    def _extract_json(self, content: str) -> Dict[str, Any]:
        """テキストからJSONを抽出"""
        # JSONブロックの検索
        json_pattern = r'```json\s*(.*?)\s*```'
        json_match = re.search(json_pattern, content, re.DOTALL)
        
        if json_match:
            json_text = json_match.group(1).strip()
        else:
            # JSONブロックがない場合は全体をJSONとして解釈
            json_text = content.strip()
            
            # { で始まっていない場合は探す
            if not json_text.startswith('{'):
                brace_start = json_text.find('{')
                if brace_start >= 0:
                    json_text = json_text[brace_start:]
        
        try:
            return json.loads(json_text)
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析エラー: {e}")
            return {"error": "JSONの解析に失敗しました", "content": content}

    def call_openai(
        self,
        prompt: str,
        system_prompt: str,
        model: str,  # 互換性のために残すが実際は self.model_name を使用
        temperature: float,
        max_tokens: int,
        force_json: bool = False,
    ) -> str:
        """
        互換性のために残す簡易呼び出しメソッド
        
        Args:
            prompt: プロンプト
            system_prompt: システムプロンプト
            model: モデル名（無視）
            temperature: 温度
            max_tokens: 最大トークン数
            force_json: JSON形式を強制するかどうか
            
        Returns:
            レスポンスのコンテンツ
        """
        content, _ = self.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            force_json=force_json,
        )
        return content
