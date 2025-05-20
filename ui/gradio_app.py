# ui/gradio_app.py
"""
Gradioを使用したウェブインターフェース for Manus-Like Agent
互換性を高めたバージョン
"""

import os
import sys
import time
import threading
import queue
from typing import List, Dict, Any, Optional
import gradio as gr

# プロジェクトルートを import パスに追加
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.logging_config import logger
from config import CONFIG
from core.agent import Agent
from core.planner import Planner
from tools.tool_registry import ToolRegistry
from llm.azure_openai_client import AzureOpenAIClient
from core.memory import Memory
from core.enhanced_memory import EnhancedMemory

# ------------------------------------------------------------------
# メッセージキュー（agent → UI）
# ------------------------------------------------------------------
msg_queue: queue.Queue = queue.Queue()

# ------------------------------------------------------------------
# Agent 生成
# ------------------------------------------------------------------
def create_agent() -> Agent:
    prompt_path = os.path.join(CONFIG["system"]["prompt_dir"], "system_prompt.txt")
    if os.path.exists(prompt_path):
        system_prompt = open(prompt_path, encoding="utf-8").read()
    else:
        system_prompt = "あなたはManusのようなエージェントです。"

    llm_client = AzureOpenAIClient()
    planner = Planner(llm_client)
    registry = ToolRegistry()

    for mod in [
        "tools.message_tools",
        "tools.shell_tools",
        "tools.file_tools",
        "tools.info_tools",
        "tools.deploy_tools",
        "tools.browser_tools",
        "tools.codeact_tools",
        "tools.system_tools",
    ]:
        registry.register_tools_from_module(mod)

    # UI に転送するメッセージツール
    registry.register_tool(
        "message_notify_user",
        lambda message, attachments=None: msg_queue.put(("notify", message)),
        registry.get_tool_spec("message_notify_user"),
    )
    registry.register_tool(
        "message_ask_user",
        lambda message, attachments=None, suggest_user_takeover="none": msg_queue.put(("ask", message)),
        registry.get_tool_spec("message_ask_user"),
    )

    # メモリ
    if CONFIG["memory"].get("use_vector_memory", False):
        memory = EnhancedMemory(workspace_dir=CONFIG["system"]["workspace_dir"])
    else:
        memory = Memory(workspace_dir=CONFIG["system"]["workspace_dir"])

    return Agent(llm_client, system_prompt, registry, planner, memory)

# ------------------------------------------------------------------
# メッセージタイプに応じたフォーマット関数
# ------------------------------------------------------------------
def format_message(msg_type: str, content: str) -> List:
    """メッセージタイプに応じて表示形式を変更 - gradio.Chatbot用"""
    if msg_type == "user":
        return {"role": "user", "content": content}  # ユーザーメッセージ
    elif msg_type == "notify":
        return {"role": "assistant", "content": content}  # エージェントメッセージ
    elif msg_type == "ask":
        return {"role": "assistant", "content": f"❓ **質問**: {content}"}
    elif msg_type == "error":
        return {"role": "assistant", "content": f"❌ **エラー**: {content}"}
    elif msg_type == "status":
        return {"role": "assistant", "content": f"ℹ️ **ステータス**: {content}"}
    else:
        return {"role": "assistant", "content": content}

# ------------------------------------------------------------------
# Agent 実行スレッド
# ------------------------------------------------------------------
def run_agent(agent: Agent, task_input: str, stop_event: threading.Event):
    try:
        msg_queue.put(("status", "エージェントが起動しました"))
        agent.start(task_input)
        msg_queue.put(("status", "タスクが完了しました"))
    except Exception as exc:
        error_message = f"エラー発生: {str(exc)}"
        logger.error("Agent 実行エラー", exc_info=False)
        msg_queue.put(("error", error_message))
        msg_queue.put(("status", "エラーにより停止しました"))
    finally:
        stop_event.set()

# ------------------------------------------------------------------
# Gradio インターフェース関数
# ------------------------------------------------------------------
def submit_task(task: str, history, status_html, agent_state):
    """新しいタスクを送信"""
    if not task.strip():
        return "", history, status_html, agent_state
    
    # 実行中の場合は拒否
    if agent_state.get("is_running", False):
        history = history or []
        history.append(format_message("error", "すでにタスクが実行中です。完了するまでお待ちください。"))
        return "", history, status_html, agent_state
    
    # エージェント作成
    if not agent_state.get("agent"):
        try:
            agent_state["agent"] = create_agent()
            logger.info("エージェントを作成しました")
        except Exception as e:
            logger.error(f"エージェント作成エラー: {str(e)}", exc_info=True)
            history = history or []
            history.append(format_message("error", f"エージェント作成エラー: {str(e)}"))
            return "", history, "<h3 style='color: red;'>❌ エラー発生</h3>", agent_state
    
    # 状態更新
    agent_state["is_running"] = True
    agent_state["stop_event"] = threading.Event()
    
    # ユーザーメッセージ追加
    history = history or []
    history.append(format_message("user", task))
    
    # エージェント実行スレッド開始
    thread = threading.Thread(
        target=run_agent,
        args=(agent_state["agent"], task, agent_state["stop_event"]),
        daemon=True
    )
    agent_state["thread"] = thread
    thread.start()
    
    # ステータス更新
    new_status = "<h3 style='color: blue;'>⏳ 処理中...</h3>"
    
    return "", history, new_status, agent_state

def stop_task(history, status_html, agent_state):
    """実行中のタスクを停止"""
    # 履歴が非初期化の場合は初期化
    history = history or []
    
    if not agent_state.get("is_running", False):
        history.append(format_message("status", "現在実行中のタスクはありません"))
        return history, status_html, agent_state
    
    # エージェント停止
    if "agent" in agent_state and agent_state["agent"]:
        try:
            agent_state["agent"].stop()
        except Exception as e:
            logger.error(f"エージェント停止エラー: {str(e)}")
    
    if "stop_event" in agent_state and agent_state["stop_event"]:
        agent_state["stop_event"].set()
    
    agent_state["is_running"] = False
    history.append(format_message("status", "ユーザーによる停止"))
    
    # ステータス更新
    new_status = "<h3 style='color: green;'>✅ アイドル状態</h3>"
    
    return history, new_status, agent_state

def clear_history(agent_state):
    """履歴をクリア"""
    new_status = "<h3 style='color: green;'>✅ アイドル状態</h3>"
    return [], new_status, agent_state

def check_queue(history, status_html, agent_state):
    """キューをチェックして新しいメッセージを取得"""
    messages_processed = 0
    status_updated = False
    
    # 履歴が非初期化の場合は初期化
    history = history or []
    
    # キューからメッセージを処理
    while not msg_queue.empty() and messages_processed < 10:
        try:
            msg_type, content = msg_queue.get_nowait()
            history.append(format_message(msg_type, content))
            messages_processed += 1
            
            # ステータス更新
            if msg_type == "status":
                if "完了" in content or "エラー" in content or "停止" in content:
                    agent_state["is_running"] = False
                    status_html = "<h3 style='color: green;'>✅ アイドル状態</h3>"
                    status_updated = True
                elif "起動" in content:
                    status_html = "<h3 style='color: blue;'>⏳ 処理中...</h3>"
                    status_updated = True
            
            # エラー時のステータス更新
            if msg_type == "error":
                agent_state["is_running"] = False
                status_html = "<h3 style='color: red;'>❌ エラー発生</h3>"
                status_updated = True
        except queue.Empty:
            break
    
    # スレッドチェック - 実行中フラグが立っているのにスレッドが死んでいる場合
    if agent_state.get("is_running", False) and "thread" in agent_state and agent_state["thread"]:
        if not agent_state["thread"].is_alive():
            agent_state["is_running"] = False
            if not status_updated:
                status_html = "<h3 style='color: green;'>✅ アイドル状態</h3>"
                history.append(format_message("status", "スレッドが終了しました"))
    
    # 実行中でなければアイドル状態
    if not agent_state.get("is_running", False) and not status_updated:
        status_html = "<h3 style='color: green;'>✅ アイドル状態</h3>"
    
    return history, status_html, agent_state

# ------------------------------------------------------------------
# 定期的キューチェックのワーカー関数
# ------------------------------------------------------------------
def setup_queue_checker(demo):
    # Check the queue every half second
    def queue_checker():
        while True:
            time.sleep(0.5)
            try:
                new_messages = []
                status_updated = False
                new_status = None
                
                # Process up to 10 messages from the queue
                for _ in range(10):
                    if msg_queue.empty():
                        break
                    
                    msg_type, content = msg_queue.get_nowait()
                    new_messages.append((msg_type, content))
                    
                    # Track status changes
                    if msg_type == "status":
                        if any(keyword in content for keyword in ["完了", "エラー", "停止"]):
                            status_updated = True
                            new_status = "<h3 style='color: green;'>✅ アイドル状態</h3>"
                        elif "起動" in content:
                            status_updated = True
                            new_status = "<h3 style='color: blue;'>⏳ 処理中...</h3>"
                    
                    # Track error status
                    if msg_type == "error":
                        status_updated = True
                        new_status = "<h3 style='color: red;'>❌ エラー発生</h3>"
                
                # Only trigger an update if we have new messages
                if new_messages:
                    # Use Gradio's function-calling API to update the UI
                    # This needs to be handled carefully as we need to update multiple elements
                    pass  # In actual implementation, this would call a method to update the UI
                
            except Exception as e:
                logger.error(f"キュー処理エラー: {str(e)}")
    
    # Start the queue checker in a background thread
    threading.Thread(target=queue_checker, daemon=True).start()
    
    return demo

# ------------------------------------------------------------------
# Gradio UI 定義
# ------------------------------------------------------------------
def create_ui():
    # スタイル定義
    css = """
    .message-box {
        padding: 10px;
        margin: 5px 0;
        border-radius: 8px;
    }
    .message-user {
        background-color: #e7f5ff;
        border-left: 4px solid #2878ff;
    }
    .message-agent {
        background-color: #f1f3f5;
        border-left: 4px solid #868e96;
    }
    .message-error {
        background-color: #fff5f5;
        border-left: 4px solid #ff6b6b;
    }
    .message-status {
        background-color: #f8f9fa;
        border-left: 4px solid #20c997;
        font-style: italic;
    }
    """

    js_code = """
        function() {
            function autoRefresh() {
                // Find the refresh button by its text content
                const buttons = document.querySelectorAll('button');
                let refreshBtn = null;
                
                for (const btn of buttons) {
                    if (btn.textContent.includes('更新')) {
                        refreshBtn = btn;
                        break;
                    }
                }
                
                // Find status element by its content
                const elements = document.querySelectorAll('h3');
                let isProcessing = false;
                
                for (const el of elements) {
                    if (el.textContent.includes('処理中')) {
                        isProcessing = true;
                        break;
                    }
                }
                
                // Click refresh if processing
                if (refreshBtn && isProcessing) {
                    refreshBtn.click();
                    console.log('Auto-refreshed');
                }
                
                // Continue checking
                setTimeout(autoRefresh, 500);
            }
            
            // Start the auto-refresh loop
            setTimeout(autoRefresh, 1000);
        }
    """
    
    with gr.Blocks(css=css, js=js_code) as demo:
        # 状態管理
        agent_state = gr.State({})
        
        gr.Markdown("# Manus-Like Agent 🤖")
        
        with gr.Row():
            with gr.Column(scale=2):
                # チャット履歴表示エリア
                chat_history = gr.Chatbot(
                    label="エージェントとの対話",
                    height=500,
                    show_copy_button=True,
                    type="messages"  # 明示的にmessages形式を指定
                )
                
                # ユーザー入力エリア
                with gr.Row():
                    with gr.Column(scale=4):
                        task_input = gr.Textbox(
                            label="タスクを指示してください",
                            placeholder="ここにタスクを入力...",
                            lines=2
                        )
                    with gr.Column(scale=1):
                        submit_btn = gr.Button("送信", variant="primary")
                
                # 操作ボタン
                with gr.Row():
                    stop_btn = gr.Button("処理を停止", variant="stop")
                    clear_btn = gr.Button("履歴をクリア")
                    # 更新ボタンを追加
                    refresh_btn = gr.Button("更新", variant="secondary", elem_id="refresh_btn")
            
            with gr.Column(scale=1):
                # ステータス表示
                status_display = gr.HTML("<h3 style='color: green;'>✅ アイドル状態</h3>", label="エージェントステータス", elem_id="status_display")
                
                # システム情報
                gr.Markdown("## システム情報")
                gr.Markdown(f"**ワークスペース**: {CONFIG['system']['workspace_dir']}")
                gr.Markdown(f"**使用モデル**: {CONFIG['llm']['model']}")
                
                # プロジェクト設定
                with gr.Accordion("詳細設定", open=False):
                    gr.Markdown("### 環境設定")
                    gr.Markdown("- 最大イテレーション: " + str(CONFIG["agent_loop"]["max_iterations"]))
                    gr.Markdown("- 実行タイムアウト: " + str(CONFIG["agent_loop"]["max_time_seconds"]) + "秒")
                    gr.Markdown("- 自動要約しきい値: " + str(CONFIG["agent_loop"]["auto_summarize_threshold"]))
        
        # イベントの設定
        submit_btn.click(
            submit_task,
            inputs=[task_input, chat_history, status_display, agent_state],
            outputs=[task_input, chat_history, status_display, agent_state],
        )
        task_input.submit(
            submit_task,
            inputs=[task_input, chat_history, status_display, agent_state],
            outputs=[task_input, chat_history, status_display, agent_state]
        )
        stop_btn.click(
            stop_task,
            inputs=[chat_history, status_display, agent_state],
            outputs=[chat_history, status_display, agent_state]
        )
        clear_btn.click(
            clear_history,
            inputs=[agent_state],
            outputs=[chat_history, status_display, agent_state]
        )
        refresh_btn.click(
            check_queue,
            inputs=[chat_history, status_display, agent_state],
            outputs=[chat_history, status_display, agent_state]
        )
        
    return demo
