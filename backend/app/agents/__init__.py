from app.core.schemas import AgentRole
from app.agents.perception import PerceptionBot
from app.agents.world_model_agent import WorldModelBot
from app.agents.planning import PlanningBot
from app.agents.reasoning import ReasoningBot
from app.agents.critic import CriticBot
from app.agents.coordinator import MissionCoordinatorBot
from app.agents.executor import ExecutorBot
from app.agents.memory_agent import MemoryBot

AGENT_CLASS_REGISTRY = {
    AgentRole.PERCEPTION: PerceptionBot,
    AgentRole.WORLD_MODEL: WorldModelBot,
    AgentRole.PLANNING: PlanningBot,
    AgentRole.REASONING: ReasoningBot,
    AgentRole.CRITIC: CriticBot,
    AgentRole.COORDINATOR: MissionCoordinatorBot,
    AgentRole.EXECUTOR: ExecutorBot,
    AgentRole.MEMORY: MemoryBot,
}
