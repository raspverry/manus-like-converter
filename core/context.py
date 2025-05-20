# core/context.py
"""
エージェントのイベントストリームとコンテキスト管理。
"""
from core.logging_config import logger
from typing import List, Dict, Any, Optional
from collections import deque



class Context:
    def __init__(self, max_events: int = 50):
        self.events = deque(maxlen=max_events)
        self.max_events = max_events
    
    def add_event(self, event: Dict[str, Any]) -> None:
        if 'type' not in event:
            logger.warning("eventに'type'がありません")
            return
        self.events.append(event)
    
    def get_events(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        if limit is None or limit >= len(self.events):
            return list(self.events)
        else:
            return list(self.events)[-limit:]
    
    def clear(self):
        self.events.clear()
