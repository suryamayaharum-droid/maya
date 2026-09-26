"""Compatibilidade retroativa: o núcleo migrou para o pacote ``turboquant``.

Este módulo re-exporta a API pública v1 para não quebrar imports antigos
(``from distributed_os_agent_mesh import ...``). Novo código deve importar
``turboquant`` diretamente. CLI: ``python3 -m turboquant.cli``.
"""

from turboquant.cpu_compute import (  # noqa: F401
    LSHIndex,
    MinHasher,
    all_but_the_top,
    average_pairwise_cosine,
    deduplicate,
    detect_acceleration,
)
from turboquant.inference import (  # noqa: F401
    InferenceEngine,
    OllamaClient,
    cosine,
    embed,
)
from turboquant.mesh import (  # noqa: F401
    GROWTH_STAGES,
    Agent,
    AutonomousSupervisor,
    EnvironmentMapper,
    ExecutionPlanner,
    MeshOrchestrator,
    RepositoryKnowledgeBuilder,
    RepositoryScout,
    SecurityGuardian,
    SharedMemory,
    Task,
    TaskStatus,
    build_distributed_os_mesh,
    gestate_until_emergence,
    map_execution_environments,
    read_growth_history,
    serve_mesh,
    verify_artifact_signatures,
)
from turboquant.store import MeshStore  # noqa: F401


class ProjectMemory:
    """Wrapper v1 sobre o store SQLite v2 (API de leitura compatível)."""

    def __init__(self, project_name: str, memory_file=None, workspace_root: str = ".") -> None:
        self.project_name = project_name
        self.store = MeshStore(project_name=project_name, workspace_root=workspace_root)

    def load(self) -> None:  # v2 carrega sob demanda; mantido por compatibilidade
        return None

    def save(self, memory, report=None, growth_event=None, environment_event=None) -> None:
        cycle = self.store.bump_runs()
        for key, value in memory.artifacts.items():
            self.store.publish_artifact(key, value, memory.artifact_signatures[key], cycle=cycle)
        self.store.add_decisions(memory.decisions, cycle=cycle)
        if growth_event:
            self.store.add_growth(int(growth_event.get("cycle", 0)), str(growth_event.get("stage", "concepcao")), float(growth_event.get("fitness", 0.0)))
        if environment_event:
            self.store.add_environment(environment_event)

    def brief(self) -> str:
        return self.store.brief()


if __name__ == "__main__":
    from turboquant.cli import main

    main()
