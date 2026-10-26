"""Core typed schemas shared across the entire runtime.

These are the structural backbone of the system: every message, decision,
task, mission, and world-state update that crosses a component boundary is
one of these Pydantic models. Nothing is passed around as a bare dict.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Agents
# --------------------------------------------------------------------------

class AgentRole(str, Enum):
    PERCEPTION = "perception"
    WORLD_MODEL = "world_model"
    PLANNING = "planning"
    REASONING = "reasoning"
    CRITIC = "critic"
    COORDINATOR = "coordinator"
    EXECUTOR = "executor"
    MEMORY = "memory"
    CUSTOM = "custom"


class AgentState(str, Enum):
    IDLE = "idle"
    OBSERVING = "observing"
    REASONING = "reasoning"
    PLANNING = "planning"
    NEGOTIATING = "negotiating"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    WAITING_FOR_AGENT = "waiting_for_agent"
    BLOCKED = "blocked"
    FAILED = "failed"
    RECOVERING = "recovering"
    STOPPED = "stopped"


class AgentConfig(BaseModel):
    agent_id: str = Field(default_factory=lambda: new_id("agent"))
    name: str
    role: AgentRole
    capabilities: list[str] = Field(default_factory=list)
    objective: str = ""
    enabled: bool = True
    max_retries: int = 3
    timeout_seconds: float = 8.0


class AgentStatus(BaseModel):
    agent_id: str
    name: str
    role: AgentRole
    state: AgentState = AgentState.IDLE
    objective: str = ""
    current_task_id: Optional[str] = None
    last_updated: datetime = Field(default_factory=utcnow)
    health: str = "healthy"  # healthy | degraded | unresponsive
    error: Optional[str] = None
    messages_sent: int = 0
    messages_received: int = 0
    decisions_made: int = 0


# --------------------------------------------------------------------------
# Messages (the message bus schema)
# --------------------------------------------------------------------------

class MessageType(str, Enum):
    OBSERVATION = "observation"
    STATE_UPDATE = "state_update"
    PROPOSAL = "proposal"
    COUNTERPROPOSAL = "counterproposal"
    CRITIQUE = "critique"
    REJECTION = "rejection"
    APPROVAL = "approval"
    TASK_ASSIGNMENT = "task_assignment"
    TASK_COMPLETION = "task_completion"
    INFO_REQUEST = "info_request"
    INFO_RESPONSE = "info_response"
    EVENT_NOTICE = "event_notice"
    ACK = "ack"
    ALERT = "alert"
    EXECUTION_RESULT = "execution_result"
    VERIFICATION_RESULT = "verification_result"
    REPLAN_REQUEST = "replan_request"
    BROADCAST = "broadcast"


class MessagePriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


_PRIORITY_ORDER = {MessagePriority.CRITICAL: 0, MessagePriority.HIGH: 1,
                    MessagePriority.NORMAL: 2, MessagePriority.LOW: 3}


class MessageStatus(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


class Message(BaseModel):
    message_id: str = Field(default_factory=lambda: new_id("msg"))
    correlation_id: str = Field(default_factory=lambda: new_id("corr"))
    sender_id: str
    receiver_id: Optional[str] = None  # None == broadcast
    message_type: MessageType
    timestamp: datetime = Field(default_factory=utcnow)
    priority: MessagePriority = MessagePriority.NORMAL
    payload: dict[str, Any] = Field(default_factory=dict)
    status: MessageStatus = MessageStatus.PENDING
    requires_ack: bool = False
    ttl_seconds: float = 15.0
    mission_id: Optional[str] = None
    task_id: Optional[str] = None

    @field_validator("payload")
    @classmethod
    def payload_must_be_dict(cls, v: Any) -> dict:
        if not isinstance(v, dict):
            raise ValueError("payload must be a JSON object")
        return v


# --------------------------------------------------------------------------
# Decisions (structured decision record per the cognitive cycle)
# --------------------------------------------------------------------------

class DecisionRecord(BaseModel):
    decision_id: str = Field(default_factory=lambda: new_id("dec"))
    agent_id: str
    mission_id: Optional[str] = None
    task_id: Optional[str] = None
    objective: str
    observations: list[str] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)
    candidate_actions: list[str] = Field(default_factory=list)
    selected_action: Optional[str] = None
    rationale: str = ""
    confidence: float = 0.5
    constraints: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    approved_by: Optional[str] = None
    execution_result: Optional[dict[str, Any]] = None
    verification_result: Optional[dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------
# Tasks & Missions
# --------------------------------------------------------------------------

class TaskStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task(BaseModel):
    task_id: str = Field(default_factory=lambda: new_id("task"))
    mission_id: str
    title: str
    description: str = ""
    priority: float = 0.5  # 0..1, higher = more urgent
    status: TaskStatus = TaskStatus.PENDING
    assigned_agent_id: Optional[str] = None
    target_entity_id: Optional[str] = None
    depends_on: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    retries: int = 0
    max_retries: int = 2
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class MissionStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Mission(BaseModel):
    mission_id: str = Field(default_factory=lambda: new_id("mission"))
    name: str
    goal: str
    scenario_key: str
    status: MissionStatus = MissionStatus.DRAFT
    priority: float = 0.5
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    task_ids: list[str] = Field(default_factory=list)
    deadline: Optional[datetime] = None
    outcome: Optional[str] = None


# --------------------------------------------------------------------------
# World model
# --------------------------------------------------------------------------

class WorldEntity(BaseModel):
    entity_id: str
    kind: str  # "bot" | "object" | "zone" | "resource" | "hazard"
    label: str
    x: float = 0.0
    y: float = 0.0
    zone_id: Optional[str] = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    last_updated: datetime = Field(default_factory=utcnow)


class WorldEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("evt"))
    kind: str
    description: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utcnow)
    source: str = "simulator"


# --------------------------------------------------------------------------
# Scenario definition (data-driven, not hardcoded into the frontend)
# --------------------------------------------------------------------------

class ScenarioDefinition(BaseModel):
    key: str
    name: str
    description: str
    map_width: int = 10
    map_height: int = 10
    zones: list[dict[str, Any]] = Field(default_factory=list)
    initial_entities: list[dict[str, Any]] = Field(default_factory=list)
    scripted_events: list[dict[str, Any]] = Field(default_factory=list)
    mission_goal: str = ""
    tags: list[str] = Field(default_factory=list)
