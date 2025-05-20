# api_server.py

import os
import json
import uuid
import threading
import logging
import asyncio
from typing import Optional, Dict, Any
from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from dotenv import load_dotenv
import uvicorn

# 環境変数のロード
load_dotenv()

# ログ設定: INFOレベルで出力
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("manus-api")

app = FastAPI(title="Manus-Like Agent API")

# セッションごとのキュー＆ループ、エージェント保持
active_sessions: Dict[str, asyncio.Queue] = {}
user_response_queues: Dict[str, asyncio.Queue] = {}
session_loops: Dict[str, asyncio.AbstractEventLoop] = {}
active_agents: Dict[str, Any] = {}

class TaskRequest(BaseModel):
    task: str
    session_id: Optional[str] = None

class UserResponse(BaseModel):
    response: str

def create_agent(session_id: str):
    # 各種コンポーネントのインポートと初期化
    from config import CONFIG
    from core.agent import Agent
    from tools.tool_registry import ToolRegistry
    from llm.azure_openai_client import AzureOpenAIClient
    from core.planner import Planner
    from core.memory import Memory
    from core.enhanced_memory import EnhancedMemory

    # システムプロンプト読み込み
    prompt_path = os.path.join(CONFIG["system"]["prompt_dir"], "system_prompt.txt")
    if os.path.exists(prompt_path):
        with open(prompt_path, encoding="utf-8") as f:
            system_prompt = f.read()
    else:
        system_prompt = "あなたはManusのようなエージェントです。"
    system_prompt += """
<interaction_rules>
- ユーザーから情報を得たいときは必ず message_ask_user を使用すること
- message_notify_user は一方向通知のみで使用すること
- message_ask_user 後はユーザー応答を待ち、繰り返しは避けること
</interaction_rules>
"""

    # LLMクライアント＆ツールレジストリ初期化
    llm_client = AzureOpenAIClient()
    planner = Planner(llm_client)
    registry = ToolRegistry()
    for mod in [
        "tools.shell_tools",
        "tools.file_tools",
        "tools.info_tools",
        "tools.deploy_tools",
        "tools.browser_tools",
        "tools.codeact_tools",
        "tools.system_tools",
    ]:
        registry.register_tools_from_module(mod)

    # message_notify_user ハンドラ
    def message_notify_handler(message: str, attachments=None):
        logger.info(f"[{session_id}] Notify: {message[:100]}...")
        loop = session_loops.get(session_id)
        queue = active_sessions.get(session_id)
        if loop and queue:
            loop.call_soon_threadsafe(queue.put_nowait, {
                "type": "notify",
                "content": message,
                "attachments": attachments
            })
        return "メッセージを送信しました"

    # message_ask_user ハンドラ
    def message_ask_handler(message: str, attachments=None, suggest_user_takeover="none"):
        logger.info(f"[{session_id}] Ask: {message[:100]}...")
        loop = session_loops.get(session_id)
        notify_q = active_sessions.get(session_id)
        response_q = user_response_queues.get(session_id)
        if loop and notify_q:
            loop.call_soon_threadsafe(notify_q.put_nowait, {
                "type": "ask",
                "content": message,
                "attachments": attachments,
                "suggest_user_takeover": suggest_user_takeover
            })
        if response_q and loop:
            fut = asyncio.run_coroutine_threadsafe(response_q.get(), loop)
            try:
                return fut.result(timeout=300)
            except asyncio.TimeoutError:
                return "タイムアウトしました"
        return "セッションが無効です"

    registry.register_tool(
        "message_notify_user",
        message_notify_handler,
        registry.get_tool_spec("message_notify_user")
    )
    registry.register_tool(
        "message_ask_user",
        message_ask_handler,
        registry.get_tool_spec("message_ask_user")
    )

    # メモリ初期化
    workspace_dir = os.path.join(CONFIG["system"]["workspace_dir"], session_id)
    os.makedirs(workspace_dir, exist_ok=True)
    if CONFIG["memory"].get("use_vector_memory", False):
        memory = EnhancedMemory(workspace_dir=workspace_dir)
    else:
        memory = Memory(workspace_dir=workspace_dir)

    agent = Agent(llm_client, system_prompt, registry, planner, memory)
    active_agents[session_id] = agent
    return agent

def start_agent_thread(agent, task: str, session_id: str):
    try:
        agent.start(task)
        loop = session_loops.get(session_id)
        queue = active_sessions.get(session_id)
        if loop and queue:
            loop.call_soon_threadsafe(queue.put_nowait, {
                "type": "status",
                "content": "タスクが完了しました"
            })
    except Exception as e:
        loop = session_loops.get(session_id)
        queue = active_sessions.get(session_id)
        if loop and queue:
            loop.call_soon_threadsafe(queue.put_nowait, {
                "type": "error",
                "content": f"エラー発生: {e}"
            })

async def run_agent(task: str, session_id: str):
    # イベントループとキューの設定
    loop = asyncio.get_running_loop()
    session_loops.setdefault(session_id, loop)
    active_sessions.setdefault(session_id, asyncio.Queue())
    user_response_queues.setdefault(session_id, asyncio.Queue())

    agent = create_agent(session_id)

    # エージェント起動ステータスをフロントへ送信
    await active_sessions[session_id].put({
        "type": "status",
        "content": "エージェントが起動しました"
    })
    # 接続確認用テストメッセージを送信
    await active_sessions[session_id].put({
        "type": "notify",
        "content": "★ テストメッセージ: 接続確認用 ★"
    })

    # エージェント本体を別スレッドで実行
    thread = threading.Thread(
        target=start_agent_thread,
        args=(agent, task, session_id),
        daemon=True
    )
    thread.start()

@app.post("/api/task", response_model=Dict[str, str])
async def start_task(request: TaskRequest, background_tasks: BackgroundTasks):
    # タスク開始エンドポイント
    session_id = request.session_id or str(uuid.uuid4())
    background_tasks.add_task(run_agent, request.task, session_id)
    return {"status": "started", "session_id": session_id}

@app.get("/api/messages/{session_id}")
async def get_messages(session_id: str):
    # RESTでのポーリング取得 (未使用想定)
    if session_id not in active_sessions:
        return {"status": "error", "message": "セッションが見つかりません"}
    try:
        msg = await asyncio.wait_for(active_sessions[session_id].get(), timeout=30)
        return {"status": "success", "message": msg}
    except asyncio.TimeoutError:
        return {"status": "timeout", "message": None}

@app.post("/api/response/{session_id}")
async def submit_response(session_id: str, data: UserResponse):
    # ユーザー応答受け取り
    if session_id not in user_response_queues:
        return {"status": "error", "message": "セッションが見つかりません"}
    await user_response_queues[session_id].put(data.response)
    return {"status": "success"}

@app.post("/api/stop/{session_id}")
async def stop_agent(session_id: str):
    # タスク停止
    agent = active_agents.get(session_id)
    if agent:
        agent.stop()
        await active_sessions[session_id].put({
            "type": "status",
            "content": "エージェントが停止されました"
        })
        return {"status": "stopped"}
    return {"status": "not_found", "message": "エージェントが見つかりません"}

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    # WebSocket エンドポイント
    await websocket.accept()
    loop = asyncio.get_running_loop()
    session_loops[session_id] = loop
    active_sessions.setdefault(session_id, asyncio.Queue())
    user_response_queues.setdefault(session_id, asyncio.Queue())

    async def recv():
        # フロントからの受信ハンドラ
        try:
            while True:
                data = await websocket.receive_json()
                t = data.get("type")
                if t == "response":
                    await user_response_queues[session_id].put(data.get("content", ""))
                elif t == "task":
                    asyncio.create_task(run_agent(data.get("content", ""), session_id))
                elif t == "stop":
                    ag = active_agents.get(session_id)
                    if ag:
                        ag.stop()
                        await active_sessions[session_id].put({
                            "type": "status",
                            "content": "エージェントが停止されました"
                        })
        except WebSocketDisconnect:
            pass

    async def send():
        # バックエンド→フロント送信ハンドラ
        try:
            while True:
                msg = await active_sessions[session_id].get()
                await websocket.send_json(msg)
        except Exception:
            pass

    # 並列実行
    await asyncio.gather(recv(), send())

@app.get("/")
async def root():
    # ヘルスチェック
    return {"status": "running", "message": "Manus-Like Agent API is running"}

if __name__ == "__main__":
    # CLI起動
    import argparse
    parser = argparse.ArgumentParser(description="Manus API Server")
    parser.add_argument("--port", type=int, default=8001, help="ポート番号")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="バインドホスト")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
