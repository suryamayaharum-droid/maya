"""Compatibilidade retroativa: o núcleo migrou para o pacote ``turboquant``.

Este módulo re-exporta a API pública v1 para não quebrar imports antigos
(``from distributed_os_agent_mesh import ...``). Novo código deve importar
``turboquant`` diretamente. CLI: ``python3 -m turboquant.cli``.
"""

from turboquant.mesh import (  # noqa: F401
    Agent,
    AutonomousSupervisor,
    EnvironmentMapper,
    ExecutionPlanner,
    GROWTH_STAGES,
    MeshOrchestrator,
    ProjectMemory,
    RepositoryKnowledgeBuilder,
    RepositoryScout,
    SecurityGuardian,
    SharedMemory,
    Task,
    TaskStatus,
    TechReference,
    TechnologyRadar,
    build_distributed_os_mesh,
    gestate_until_emergence,
    map_execution_environments,
    read_growth_history,
    serve_mesh,
    verify_artifact_signatures,
)
