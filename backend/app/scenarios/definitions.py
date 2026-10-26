"""Data-driven scenario definitions.

A scenario is just data: a map, a set of initial entities, and a timeline
of scripted events. New scenarios can be added here (or submitted through
the API) without touching any frontend code or agent logic — the whole
point of the framework being general-purpose rather than hardcoded around
any one example.
"""
from __future__ import annotations

from app.core.schemas import ScenarioDefinition

SCENARIOS: dict[str, ScenarioDefinition] = {}


def _register(s: ScenarioDefinition) -> None:
    SCENARIOS[s.key] = s


_register(ScenarioDefinition(
    key="collaborative_exploration",
    name="Collaborative Exploration",
    description="Multiple bots divide an unknown map into regions, explore, and share discovered information.",
    map_width=12, map_height=12,
    zones=[{"zone_id": "north", "label": "North Wing"}, {"zone_id": "south", "label": "South Wing"}],
    initial_entities=[
        {"entity_id": "bot-1", "kind": "bot", "label": "Explorer-1", "x": 1, "y": 1, "zone_id": "north"},
        {"entity_id": "bot-2", "kind": "bot", "label": "Explorer-2", "x": 10, "y": 10, "zone_id": "south"},
    ],
    scripted_events=[
        {"at_tick": 2, "kind": "agent_sighting", "description": "Unmapped resource cache spotted in North Wing",
         "entity_id": "cache-1", "apply": {"entity_id": "cache-1", "kind": "resource", "label": "Resource Cache",
                                            "x": 3, "y": 2, "zone_id": "north", "attributes": {"available": 3}}},
        {"at_tick": 5, "kind": "zone_change", "description": "South Wing reveals a new unexplored corridor",
         "entity_id": "south", "apply": {"entity_id": "corridor-s1", "kind": "zone", "label": "South Corridor",
                                          "x": 11, "y": 6, "zone_id": "south", "attributes": {}}},
    ],
    mission_goal="Fully map North and South wings and report discovered resources",
    tags=["exploration", "multi-bot"],
))

_register(ScenarioDefinition(
    key="dynamic_obstacle_response",
    name="Dynamic Obstacle Response",
    description="A route becomes blocked mid-mission; agents exchange information and find a viable alternative.",
    map_width=10, map_height=10,
    zones=[{"zone_id": "corridor-c", "label": "Corridor C"}],
    initial_entities=[
        {"entity_id": "bot-1", "kind": "bot", "label": "Patrol-1", "x": 0, "y": 0},
        {"entity_id": "waypoint-d", "kind": "zone", "label": "Waypoint D", "x": 8, "y": 8,
         "zone_id": "corridor-c", "attributes": {"blocked": False}},
    ],
    scripted_events=[
        {"at_tick": 2, "kind": "obstacle", "description": "Corridor C is now blocked by fallen debris",
         "entity_id": "waypoint-d", "apply": {"entity_id": "waypoint-d", "attributes": {"blocked": True}}},
    ],
    mission_goal="Reach Waypoint D despite the Corridor C blockage",
    tags=["obstacle", "replanning"],
))

_register(ScenarioDefinition(
    key="resource_coordination",
    name="Resource Coordination",
    description="Multiple bots need a limited shared resource and must negotiate allocation.",
    map_width=10, map_height=10,
    zones=[],
    initial_entities=[
        {"entity_id": "bot-1", "kind": "bot", "label": "Worker-1", "x": 1, "y": 1},
        {"entity_id": "bot-2", "kind": "bot", "label": "Worker-2", "x": 9, "y": 1},
        {"entity_id": "charger-1", "kind": "resource", "label": "Charging Station", "x": 5, "y": 5,
         "attributes": {"available": 1}},
    ],
    scripted_events=[
        {"at_tick": 1, "kind": "resource", "description": "Worker-1 requests the charging station",
         "entity_id": "charger-1"},
        {"at_tick": 2, "kind": "resource", "description": "Worker-2 also requests the charging station",
         "entity_id": "charger-1"},
    ],
    mission_goal="Allocate the single charging station fairly between both workers",
    tags=["negotiation", "resource"],
))

_register(ScenarioDefinition(
    key="emergency_response",
    name="Emergency Response",
    description="Competing tasks arrive at once; the coordinator must prioritize by urgency and safety policy.",
    map_width=10, map_height=10,
    zones=[],
    initial_entities=[
        {"entity_id": "bot-1", "kind": "bot", "label": "Responder-1", "x": 4, "y": 4},
    ],
    scripted_events=[
        {"at_tick": 1, "kind": "hazard", "description": "Smoke detected near Server Room",
         "entity_id": "hazard-1", "apply": {"entity_id": "hazard-1", "kind": "hazard", "label": "Smoke Hazard",
                                             "x": 7, "y": 2, "attributes": {}}},
        {"at_tick": 1, "kind": "obstacle", "description": "Minor obstacle reported in Hallway B",
         "entity_id": "obstacle-1", "apply": {"entity_id": "obstacle-1", "kind": "object", "label": "Fallen Chair",
                                               "x": 2, "y": 6, "attributes": {}}},
    ],
    mission_goal="Respond to the highest-urgency event first while tracking the rest",
    tags=["priority", "emergency"],
))

_register(ScenarioDefinition(
    key="unattended_object_monitoring",
    name="Unattended Object Monitoring",
    description="A perception bot detects an object, tracks it over time, and escalates only if conditions "
                "configured by the scenario are met. One example among several, not a special case in the code.",
    map_width=10, map_height=10,
    zones=[],
    initial_entities=[
        {"entity_id": "bot-1", "kind": "bot", "label": "Patrol-1", "x": 0, "y": 0},
    ],
    scripted_events=[
        {"at_tick": 1, "kind": "object_appeared", "description": "Unattended bag detected near Entrance",
         "entity_id": "object-1", "apply": {"entity_id": "object-1", "kind": "object", "label": "Unattended Bag",
                                             "x": 3, "y": 3, "attributes": {"owner_present": False}}},
        {"at_tick": 4, "kind": "anomaly", "description": "Object still unattended after monitoring window",
         "entity_id": "object-1"},
    ],
    mission_goal="Monitor the unattended object and escalate only if it remains unattended past the threshold",
    tags=["monitoring", "security"],
))

_register(ScenarioDefinition(
    key="collaborative_investigation",
    name="Collaborative Investigation",
    description="Different bots investigate competing hypotheses, share evidence, critique conclusions, and "
                "produce a joint assessment.",
    map_width=10, map_height=10,
    zones=[],
    initial_entities=[
        {"entity_id": "bot-1", "kind": "bot", "label": "Investigator-1", "x": 1, "y": 8},
    ],
    scripted_events=[
        {"at_tick": 1, "kind": "anomaly", "description": "Unexplained power fluctuation reported in Lab 3",
         "entity_id": "anomaly-1", "apply": {"entity_id": "anomaly-1", "kind": "object", "label": "Power Anomaly",
                                              "x": 6, "y": 6, "attributes": {}}},
        {"at_tick": 3, "kind": "anomaly", "description": "A second, correlated fluctuation reported in Lab 4",
         "entity_id": "anomaly-2", "apply": {"entity_id": "anomaly-2", "kind": "object", "label": "Power Anomaly 2",
                                              "x": 7, "y": 6, "attributes": {}}},
    ],
    mission_goal="Determine whether the two anomalies share a root cause",
    tags=["investigation", "evidence"],
))


def list_scenarios() -> list[ScenarioDefinition]:
    return list(SCENARIOS.values())


def get_scenario(key: str) -> ScenarioDefinition | None:
    return SCENARIOS.get(key)


def register_scenario(scenario: ScenarioDefinition) -> None:
    """Allows new scenarios to be created via the API at runtime."""
    SCENARIOS[scenario.key] = scenario
