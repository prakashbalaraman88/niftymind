import asyncio
import json
import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict, field
from datetime import datetime, time, timezone, timedelta
from typing import Any, TypedDict, Annotated

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import REDIS_CHANNELS

from langgraph.graph import StateGraph, END

IST = timezone(timedelta(hours=5, minutes=30))

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
PRE_MARKET_OPEN = time(9, 0)
POST_MARKET_CLOSE = time(15, 45)


@dataclass
class Signal:
    agent_id: str
    timestamp: str
    underlying: str
    direction: str
    confidence: float
    timeframe: str
    reasoning: str
    supporting_data: dict = field(default_factory=dict)


class AgentState(TypedDict):
    channel: str
    data: dict
    should_process: bool
    signal: Signal | None
    error: str | None


class BaseAgent(ABC):
    def __init__(self, agent_id: str, agent_name: str, redis_publisher):
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.publisher = redis_publisher
        self.logger = logging.getLogger(f"niftymind.agent.{agent_id}")
        self._last_signal: Signal | None = None
        self._signal_count = 0
        self._active = False
        self._graph = self._build_graph()

    def _build_graph(self) -> Any:
        graph = StateGraph(AgentState)

        graph.add_node("gate_check", self._node_gate_check)
        graph.add_node("process", self._node_process)
        graph.add_node("emit", self._node_emit)

        graph.set_entry_point("gate_check")
        graph.add_conditional_edges(
            "gate_check",
            self._route_after_gate,
            {"process": "process", "skip": END},
        )
        graph.add_conditional_edges(
            "process",
            self._route_after_process,
            {"emit": "emit", "done": END},
        )
        graph.add_edge("emit", END)

        return graph.compile()

    async def _node_gate_check(self, state: AgentState) -> dict:
        return {"should_process": self.should_run()}

    def _route_after_gate(self, state: AgentState) -> str:
        return "process" if state["should_process"] else "skip"

    async def _node_process(self, state: AgentState) -> dict:
        try:
            signal = await self.process_message(state["channel"], state["data"])
            return {"signal": signal, "error": None}
        except Exception as e:
            self.logger.error(f"Error in process_message: {e}", exc_info=True)
            return {"signal": None, "error": str(e)}

    def _route_after_process(self, state: AgentState) -> str:
        return "emit" if state.get("signal") is not None else "done"

    async def _node_emit(self, state: AgentState) -> dict:
        signal = state["signal"]
        if signal:
            await self.emit_signal(signal)
        return {}

    async def _invoke_graph(self, channel: str, data: dict):
        initial_state: AgentState = {
            "channel": channel,
            "data": data,
            "should_process": False,
            "signal": None,
            "error": None,
        }
        await self._graph.ainvoke(initial_state)

    @property
    @abstractmethod
    def subscribed_channels(self) -> list[str]:
        ...

    @abstractmethod
    async def process_message(self, channel: str, data: dict) -> Signal | None:
        ...

    def is_market_hours(self) -> bool:
        now = datetime.now(IST).time()
        return MARKET_OPEN <= now <= MARKET_CLOSE

    def is_pre_market(self) -> bool:
        now = datetime.now(IST).time()
        return PRE_MARKET_OPEN <= now < MARKET_OPEN

    def is_post_market(self) -> bool:
        now = datetime.now(IST).time()
        return MARKET_CLOSE < now <= POST_MARKET_CLOSE

    def is_expiry_day(self) -> bool:
        today = datetime.now(IST).date()
        return today.weekday() == 3

    def should_run(self) -> bool:
        return self.is_market_hours()

    async def emit_signal(self, signal: Signal):
        self._last_signal = signal
        self._signal_count += 1

        signal_dict = asdict(signal)
        await self.publisher.publish_signal(signal_dict)

        self.logger.info(
            f"Signal emitted: {signal.underlying} {signal.direction} "
            f"confidence={signal.confidence:.2f} timeframe={signal.timeframe}"
        )

    async def emit_status(self, state: str, details: dict | None = None):
        status = {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "state": state,
            "is_market_hours": self.is_market_hours(),
            "is_expiry_day": self.is_expiry_day(),
            "signal_count": self._signal_count,
            "last_signal_direction": self._last_signal.direction if self._last_signal else None,
            "last_signal_confidence": self._last_signal.confidence if self._last_signal else None,
            "timestamp": datetime.now(IST).isoformat(),
        }
        if details:
            status["details"] = details
        await self.publisher.publish_agent_status(status)

    async def start(self, shutdown_event: asyncio.Event):
        self._active = True
        self.logger.info(f"Agent {self.agent_name} starting (LangGraph pipeline)")
        await self.emit_status("STARTING")

        pubsub = await self.publisher.subscribe(*self.subscribed_channels)

        try:
            await self.emit_status("RUNNING")
            while not shutdown_event.is_set():
                if not self.should_run():
                    await self.emit_status("WAITING_FOR_MARKET")
                    try:
                        # Jitter prevents all 12 agents firing simultaneously
                        jitter = random.uniform(0, 8)
                        await asyncio.wait_for(shutdown_event.wait(), timeout=30.0 + jitter)
                        break
                    except asyncio.TimeoutError:
                        continue

                try:
                    message = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    continue

                if message is None:
                    continue

                if message["type"] != "message":
                    continue

                try:
                    data = json.loads(message["data"])
                    channel = message["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode()

                    await self._invoke_graph(channel, data)
                except json.JSONDecodeError:
                    self.logger.warning(f"Non-JSON message received")
                except Exception as e:
                    self.logger.error(f"Error in graph execution: {e}", exc_info=True)

        except asyncio.CancelledError:
            self.logger.info(f"Agent {self.agent_name} cancelled")
        finally:
            self._active = False
            await pubsub.unsubscribe()
            await pubsub.aclose()
            await self.emit_status("STOPPED")
            self.logger.info(f"Agent {self.agent_name} stopped")

    def create_signal(
        self,
        underlying: str,
        direction: str,
        confidence: float,
        timeframe: str,
        reasoning: str,
        supporting_data: dict | None = None,
    ) -> Signal:
        return Signal(
            agent_id=self.agent_id,
            timestamp=datetime.now(IST).isoformat(),
            underlying=underlying,
            direction=direction,
            confidence=max(0.0, min(1.0, confidence)),
            timeframe=timeframe,
            reasoning=reasoning,
            supporting_data=supporting_data or {},
        )
