# tools/system_tools.py
from tools.tool_registry import tool

@tool(
    name="idle",
    description="タスクが完了したことを示し、エージェントをアイドル状態にします",
    parameters={
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "アイドル状態に入る理由"}
        },
        "required": []
    }
)
def idle(reason: str = "タスク完了"):
    """
    エージェントをアイドル状態にします。タスクが完了したときに呼び出されます。
    """
    return f"アイドル状態に入ります: {reason}"
