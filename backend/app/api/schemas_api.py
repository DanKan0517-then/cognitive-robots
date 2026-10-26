"""Request/response models for the REST API layer.

Kept separate from app.core.schemas (the runtime's internal data model) so
the wire format can evolve independently of internal structures.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from app.core.schemas import AgentRole


class CreateAgentRequest(BaseModel):
    name: str
    role: AgentRole
    capabilities: list[str] = []
    objective: str = ""


class UpdateAgentRequest(BaseModel):
    objective: Optional[str] = None
    capabilities: Optional[list[str]] = None
    enabled: Optional[bool] = None


class CreateMissionRequest(BaseModel):
    name: str
    goal: str
    scenario_key: str
    priority: float = 0.5


class StartScenarioRequest(BaseModel):
    key: str


class InjectEventRequest(BaseModel):
    kind: str
    description: str
    entity_id: Optional[str] = None
    payload: dict[str, Any] = {}


class SetSpeedRequest(BaseModel):
    speed: float


class ApprovalDecisionRequest(BaseModel):
    approve: bool


class CreateScenarioRequest(BaseModel):
    key: str
    name: str
    description: str
    map_width: int = 10
    map_height: int = 10
    zones: list[dict[str, Any]] = []
    initial_entities: list[dict[str, Any]] = []
    scripted_events: list[dict[str, Any]] = []
    mission_goal: str = ""
    tags: list[str] = []
