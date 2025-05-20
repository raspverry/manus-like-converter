# chainlit_frontend.py

import os
import json
import uuid
import asyncio
import logging
import chainlit as cl
import websockets
from typing import Dict, Any

# ログ設定: INFOレベルで出力
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("manus-chainlit")

# バックエンドAPIとWebSocketのURL（.envで設定可能）
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8001/api")
WS_BASE_URL = os.getenv("WS_BASE_URL", "ws://localhost:8001/ws")

# セッション情報の保持用
session_data: Dict[str, Any] = {
    "session_id": None,
    "ws_connection": None,
    "is_connected": False,
    "initialized": False  # 一度だけ初期化処理を走らせるためのフラグ
}

async def connect_to_websocket(session_id: str) -> bool:
    """
    バックエンドのWebSocketに接続。最大3回リトライを行う。
    成功するとTrueを返し、失敗時はErrorメッセージをUIに表示してFalseを返す。
    """
    for attempt in range(3):
        logger.info(f"WS_BASE_URL={WS_BASE_URL} に接続を試みます… (試行 {attempt+1}/3)")
        try:
            conn = await websockets.connect(f"{WS_BASE_URL}/{session_id}")
            logger.info(f"WebSocket 接続成功: セッションID={session_id}")
            session_data["ws_connection"] = conn
            session_data["is_connected"] = True
            # メッセージ受信の非同期タスクを開始
            asyncio.create_task(listen_for_messages(conn))
            return True
        except Exception as e:
            logger.warning(f"WS 接続失敗 (試行 {attempt+1}/3): {e}")
            await asyncio.sleep(1)

    logger.error(f"WebSocket の接続にすべて失敗しました: {WS_BASE_URL}/{session_id}")
    await cl.Message(content="WebSocketへの接続に失敗しました。サーバーを確認してください。", author="Error").send()
    return False

async def listen_for_messages(connection: websockets.WebSocketClientProtocol):
    """
    WebSocketからのメッセージを待ち受け、ChainlitのUIに表示する。
    """
    try:
        while session_data["is_connected"]:
            raw = await connection.recv()
            logger.info(f"Raw WS フレーム受信: {raw}")
            try:
                data = json.loads(raw)
                logger.info(f"Parsed Message: {data}")
                msg_type = data.get("type")
                content = data.get("content", "")

                if msg_type == "notify":
                    # 通知メッセージ
                    await cl.Message(content=content).send()
                elif msg_type == "ask":
                    # ユーザーへの質問
                    await cl.Message(content=content).send()
                    # ユーザーの回答を待ち、バックエンドに返送
                    response = await cl.AskUserMessage(content="").send()
                    logger.info(f"ユーザー応答: {response}")
                    await connection.send(json.dumps({"type": "response", "content": response}))
                elif msg_type == "status":
                    # ステータス更新
                    await cl.Message(content=content, author="System").send()
                elif msg_type == "error":
                    # エラー表示
                    await cl.Message(content=content, author="Error").send()
                else:
                    logger.warning(f"未知のメッセージタイプ: {msg_type}")
            except json.JSONDecodeError:
                logger.error(f"無効なJSONフォーマット: {raw}")
                await cl.Message(content="無効なメッセージを受信しました。", author="Error").send()
    except websockets.exceptions.ConnectionClosed:
        logger.warning("WebSocket接続が閉じられました。")
        session_data["is_connected"] = False
        await cl.Message(content="接続が切断されました。リロードして再接続してください。", author="System").send()
    except Exception as e:
        logger.error(f"受信中エラー: {e}")
        session_data["is_connected"] = False
        await cl.Message(content=f"受信エラー: {e}", author="Error").send()

@cl.on_chat_start
async def on_chat_start():
    """
    チャット開始時に一意のセッションIDを生成し、WebSocket接続を試みる。
    既に初期化済みなら再実行せずにスキップ。
    """
    # すでに初期化済みなら何もしない
    if session_data["initialized"]:
        logger.info("既に初期化済みのため on_chat_start をスキップします")
        return

    # 初期化フラグを立てる
    session_data["initialized"] = True
    session_data["session_id"] = str(uuid.uuid4())
    sid = session_data["session_id"]
    logger.info(f"新規チャットセッション開始: {sid}")

    # WebSocket接続
    if not await connect_to_websocket(sid):
        return

    # 接続成功ならウェルカムメッセージをUIに送信
    await cl.Message(
        content="Manus-Like Agent 🤖\n\nタスクを入力してください。",
        author="System"
    ).send()
    await cl.Message(
        content="このエージェントはコマンド実行、ファイル作成、ウェブ検索など、多彩なタスクをサポートします。",
        author="System",
        actions=[
            cl.Action(
                name="stop_agent",
                label="エージェントを停止",
                description="実行中のエージェントを停止する",
                payload={"session_id": sid}
            )
        ]
    ).send()

@cl.on_message
async def on_message(message: cl.Message):
    """
    ユーザー入力を受け取り、バックエンドへタスクとして送信する。
    """
    user_input = message.content
    logger.info(f"ユーザーメッセージ受信: {user_input}")

    # 未接続なら再接続
    if not session_data["is_connected"]:
        logger.info("未接続のため再接続を試みます。")
        if not await connect_to_websocket(session_data["session_id"]):
            return

    # タスクをWSで送信
    try:
        await session_data["ws_connection"].send(json.dumps({"type": "task", "content": user_input}))
    except Exception as e:
        logger.error(f"タスク送信エラー: {e}")
        await cl.Message(content=f"タスク送信エラー: {e}", author="Error").send()
        session_data["is_connected"] = False

@cl.action_callback("stop_agent")
async def on_stop_action(action: cl.Action):
    """
    「エージェントを停止」ボタン押下時の処理。
    """
    sid = action.payload.get("session_id")
    if not sid or not session_data["is_connected"]:
        await cl.Message(content="セッションが無効です。", author="Error").send()
        return

    logger.info(f"停止リクエスト: セッションID={sid}")
    try:
        # WebSocketで停止命令を送信
        await session_data["ws_connection"].send(json.dumps({"type": "stop"}))
        await cl.Message(content="停止リクエストを送信しました。", author="System").send()
    except Exception as e:
        logger.error(f"停止エラー: {e}")
        await cl.Message(content=f"停止中にエラーが発生しました: {e}", author="Error").send()
