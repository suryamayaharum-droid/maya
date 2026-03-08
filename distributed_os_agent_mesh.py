"""Malha de agentes autônomos para construção de sistemas operacionais distribuídos.

Este módulo implementa um núcleo de coordenação orientado a metas com agentes
especializados (arquitetura, kernel, rede, segurança, observabilidade, testes e
release). A malha suporta:

- Planejamento de tarefas por grafo de dependências.
- Execução concorrente por passos.
- Compartilhamento de artefatos entre agentes.
- Ciclo de validação e síntese de blueprint final.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set


class TaskStatus(str, Enum):
    """Status de uma tarefa no plano distribuído."""

    PENDING = "pending"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    DONE = "done"


@dataclass
class Task:
    """Representa uma unidade de trabalho do roadmap do SO distribuído."""

    task_id: str
    description: str
    owner_role: str
    depends_on: Set[str] = field(default_factory=set)
    status: TaskStatus = TaskStatus.PENDING
    output: Optional[str] = None


@dataclass
class SharedMemory:
    """Memória compartilhada para publicar artefatos entre agentes."""

    artifacts: Dict[str, str] = field(default_factory=dict)
    decisions: List[str] = field(default_factory=list)

    def publish(self, key: str, value: str) -> None:
        self.artifacts[key] = value

    def record_decision(self, decision: str) -> None:
        self.decisions.append(decision)


class Agent:
    """Agente base de execução."""

    def __init__(self, role: str, mission: str) -> None:
        self.role = role
        self.mission = mission

    def execute(self, task: Task, memory: SharedMemory) -> str:
        """Executa a tarefa e retorna resultado textual."""
        context_keys = ", ".join(sorted(memory.artifacts.keys())) or "sem contexto prévio"
        result = (
            f"[{self.role}] concluiu {task.task_id}: {task.description}. "
            f"Missão: {self.mission}. Contexto usado: {context_keys}."
        )
        return result


class MeshOrchestrator:
    """Orquestrador principal da malha de agentes."""

    def __init__(self) -> None:
        self.memory = SharedMemory()
        self.agents = self._build_agents()
        self.tasks = self._build_initial_plan()

    @staticmethod
    def _build_agents() -> Dict[str, Agent]:
        return {
            "architect": Agent("architect", "Desenhar macroarquitetura do SO distribuído"),
            "kernel": Agent("kernel", "Definir microkernel modular e isolamento"),
            "network": Agent("network", "Definir plano de dados, consenso e descoberta"),
            "security": Agent("security", "Projetar identidade, políticas e hardening"),
            "observability": Agent("observability", "Projetar telemetria, tracing e SLOs"),
            "qa": Agent("qa", "Criar estratégia de testes de resiliência e caos"),
            "release": Agent("release", "Empacotar roadmap de entrega e operação"),
        }

    @staticmethod
    def _build_initial_plan() -> Dict[str, Task]:
        return {
            "T1": Task("T1", "Blueprint da arquitetura distribuída", "architect"),
            "T2": Task("T2", "Especificação do microkernel e scheduler", "kernel", {"T1"}),
            "T3": Task("T3", "Protocolo de rede e consenso", "network", {"T1"}),
            "T4": Task("T4", "Modelo de segurança zero-trust", "security", {"T1", "T3"}),
            "T5": Task("T5", "Padrão de observabilidade e auditoria", "observability", {"T2", "T3"}),
            "T6": Task("T6", "Plano de testes de carga e tolerância a falhas", "qa", {"T2", "T3", "T4", "T5"}),
            "T7": Task("T7", "Estratégia de rollout e operação multi-região", "release", {"T6"}),
        }

    def _refresh_ready_tasks(self) -> None:
        for task in self.tasks.values():
            if task.status == TaskStatus.PENDING and all(
                self.tasks[dependency].status == TaskStatus.DONE
                for dependency in task.depends_on
            ):
                task.status = TaskStatus.READY

    def _all_done(self) -> bool:
        return all(task.status == TaskStatus.DONE for task in self.tasks.values())

    def run(self) -> None:
        """Executa o plano completo em ondas de tarefas prontas."""
        while not self._all_done():
            self._refresh_ready_tasks()
            ready_batch = [task for task in self.tasks.values() if task.status == TaskStatus.READY]
            if not ready_batch:
                raise RuntimeError("Deadlock detectado no grafo de tarefas")

            for task in ready_batch:
                task.status = TaskStatus.IN_PROGRESS
                agent = self.agents[task.owner_role]
                result = agent.execute(task, self.memory)
                task.output = result
                task.status = TaskStatus.DONE
                artifact_key = f"artifact:{task.task_id}"
                self.memory.publish(artifact_key, result)
                self.memory.record_decision(
                    f"{task.task_id} finalizada por {task.owner_role}; artefato publicado em {artifact_key}."
                )

    def summarize(self) -> str:
        """Retorna um sumário executivo do estado final da malha."""
        completed = [task for task in self.tasks.values() if task.status == TaskStatus.DONE]
        lines = [
            "Malha de agentes concluída com sucesso.",
            f"Tarefas concluídas: {len(completed)}/{len(self.tasks)}",
            "Decisões registradas:",
        ]
        lines.extend(f"- {decision}" for decision in self.memory.decisions)
        return "\n".join(lines)


def build_distributed_os_mesh() -> str:
    """API principal para criação e execução da malha autônoma."""
    orchestrator = MeshOrchestrator()
    orchestrator.run()
    return orchestrator.summarize()


if __name__ == "__main__":
    print(build_distributed_os_mesh())
