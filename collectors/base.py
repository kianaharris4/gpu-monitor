
from abc import ABC, abstractmethod
from schema import GPUSnapshot

class BaseCollector(ABC):
    @abstractmethod
    def collect(self) -> GPUSnapshot:
        pass

    @abstractmethod
    def detect(self) -> bool:
        pass
