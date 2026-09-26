"""TurboQuant — malha autônoma 100% CPU, zero serviços pagos.

Pacotes:
- ``cpu_compute``: estudo/primitivas de computação sem GPU (whitening anisotrópico,
  hashing MinHash+LSH, quantização INT8, telemetria de recursos).
- ``store``: memória persistente em SQLite (WAL) com busca vetorial + semântica.
- ``inference``: backend de inferência plugável — LLM local via Ollama (se houver)
  ou gerador determinístico heurístico (fallback offline garantido).
- ``mesh``: o núcleo da malha (DAG de agentes, guardião de segurança, supervisor).
"""

from turboquant.mesh import (
    AutonomousSupervisor,
    MeshOrchestrator,
    SecurityGuardian,
    build_distributed_os_mesh,
    gestate_until_emergence,
    map_execution_environments,
    read_growth_history,
    verify_artifact_signatures,
)

__all__ = [
    "AutonomousSupervisor",
    "MeshOrchestrator",
    "SecurityGuardian",
    "build_distributed_os_mesh",
    "gestate_until_emergence",
    "map_execution_environments",
    "read_growth_history",
    "verify_artifact_signatures",
]
