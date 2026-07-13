from abc import ABC, abstractmethod
from core.model_router import ModelRouter
from core.memory import Memory

class Skill(ABC):
    def __init__(self, config: dict, router: ModelRouter, memory: Memory):
        self.config = config
        self.router = router
        self.memory = memory

    @abstractmethod
    async def execute(self, task: dict) -> str:
        pass