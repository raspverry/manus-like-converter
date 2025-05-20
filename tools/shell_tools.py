# tools/shell_tools.py
"""
Dockerサンドボックスでshellコマンドを実行するツール。
"""
from core.logging_config import logger
from typing import Optional
from tools.tool_registry import tool
from sandbox.sandbox import get_sandbox



_shell_sessions = {}

@tool(
    name="shell_exec",
    description="シェルコマンドを実行し、出力を返す",
    parameters={
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "シェルセッションID"},
            "exec_dir": {"type": "string", "description": "実行ディレクトリ"},
            "command": {"type": "string", "description": "実行するコマンド"}
        },
        "required": ["id", "exec_dir", "command"]
    }
)
def shell_exec(id: str, exec_dir: str, command: str):
    sandbox = get_sandbox()
    stdout, stderr, exit_code = sandbox.execute_command(id, command, exec_dir)
    if stderr:
        return f"[stdout]\n{stdout}\n\n[stderr]\n{stderr}\nExitCode: {exit_code}"
    else:
        return f"[stdout]\n{stdout}\nExitCode: {exit_code}"
