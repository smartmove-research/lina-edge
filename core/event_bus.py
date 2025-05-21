# core/event_bus.py
from collections import defaultdict
from typing import Type, Callable, Dict, List, Any
import asyncio

class Event:
    """Base class for all events."""
    pass

class EventBus:
    def __init__(self):
        self._subs: Dict[Type[Event], List[Callable[[Event], Any]]] = defaultdict(list)

    def subscribe(self, event_type: Type[Event], handler: Callable[[Event], Any]):
        """Register a handler for a specific event type."""
        self._subs[event_type].append(handler)

    def emit(self, event: Event):
        """Publish an event to all subscribers (sync or async)."""
        for handler in self._subs[type(event)]:
            result = handler(event)
            # If handler returns a coroutine, schedule it
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
