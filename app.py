"""FastAPI entrypoint para deploy (ex.: Vercel) — TurboQuant Mesh v2.

Novidades desta versão:
- Núcleo agora é o pacote ``turboquant`` (SQLite + embeddings + DAG paralela).
- Rotas de memória: ``GET /memory`` (brief), ``GET /search?q=`` (busca semântica),
  ``GET /whiteness`` (diagnóstico anisotrópico), ``GET /cpu-plan`` (playbook CPU).
- Rotas POST protegidas por token quando ``TURBOQUANT_API_TOKEN`` estiver definido
  (header ``X-TurboQuant-Token`` ou query ``?token=``). Sem a variável, modo aberto
  (dev local). Chave HMAC continua com fail-fast via TURBOQUANT_REQUIRE_REAL_KEY.
"""

from __future__ import annotations

import hmac
import os
from typing import Any, Dict, Optional

try:
    from fastapi import FastAPI, HTTPException, Query, Request
except ModuleNotFoundError:  # fallback para ambientes sem dependências instaladas
    class _MissingFastAPIApp:
        async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
            body = b"FastAPI nao instalado. Instale com: pip install -r requirements.txt"
            await send({"type": "http.response.start", "status": 500, "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": body})

    app = _MissingFastAPIApp()
else:
    from turboquant.cpu_compute import cpu_optimization_plan
    from turboquant.mesh import (
        AutonomousSupervisor,
        build_distributed_os_mesh,
        gestate_until_emergence,
        map_execution_environments,
        read_growth_history,
        verify_artifact_signatures,
    )
    from turboquant.store import MeshStore

    app = FastAPI(title="TurboQuant Autonomous Mesh", version="2.0.0")

    def _require_token(request: Optional[Request], token: Optional[str]) -> None:
        expected = os.getenv("TURBOQUANT_API_TOKEN")
        if not expected:
            return  # modo dev aberto
        provided = (request.headers.get("x-turboquant-token") if request else None) or token
        if not provided or not hmac.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="token invalido ou ausente (X-TurboQuant-Token)")

    @app.get("/")
    def root() -> Dict[str, Any]:
        return {
            "service": "turboquant-autonomous-mesh",
            "version": "2.0.0",
            "status": "ok",
            "routes": [
                "/health", "/environments", "/plan", "/growth", "/run-once",
                "/gestate", "/summary", "/memory", "/search", "/whiteness", "/cpu-plan",
            ],
        }

    @app.get("/health")
    def health() -> Dict[str, Any]:
        env_map = map_execution_environments()
        return {
            "status": "ok",
            "execution_target": env_map["execution_plan"]["target"],
            "acceleration": env_map["execution_plan"]["acceleration"],
            "workers": env_map["execution_plan"]["parallel_workers"],
        }

    @app.get("/environments")
    def environments() -> Dict[str, Any]:
        return map_execution_environments()["environment"]

    @app.get("/plan")
    def plan() -> Dict[str, Any]:
        return map_execution_environments()["execution_plan"]

    @app.get("/cpu-plan")
    def cpu_plan() -> Dict[str, Any]:
        """Playbook honesto de otimização sem GPU (aplicado no núcleo)."""
        return cpu_optimization_plan()

    @app.get("/growth")
    def growth(project: str = Query("turboquant"), workspace: str = Query(".")) -> Dict[str, Any]:
        """Histórico de crescimento persistido pela malha (sem executar um novo ciclo)."""
        return read_growth_history(project_name=project, workspace_root=workspace)

    @app.get("/memory")
    def memory_brief(project: str = Query("turboquant"), workspace: str = Query(".")) -> Dict[str, Any]:
        store = MeshStore(project_name=project, workspace_root=workspace)
        return {"brief": store.brief(), "decisions_recentes": store.recent_decisions(10)}

    @app.get("/search")
    def search(
        q: str = Query(..., min_length=1),
        project: str = Query("turboquant"),
        workspace: str = Query("."),
        top_k: int = Query(5, ge=1, le=50),
    ) -> Dict[str, Any]:
        """Busca semântica na memória episódica (embeddings INT8 + cosseno em CPU)."""
        store = MeshStore(project_name=project, workspace_root=workspace)
        hits = store.semantic_search(q, top_k=top_k)
        return {"query": q, "results": [{"ref": r, "score": round(s, 4)} for r, s in hits]}

    @app.get("/whiteness")
    def whiteness(project: str = Query("turboquant"), workspace: str = Query(".")) -> Dict[str, Any]:
        store = MeshStore(project_name=project, workspace_root=workspace)
        return store.whiteness_report()

    @app.post("/run-once")
    def run_once(
        request: Request,
        project: str = Query("turboquant"),
        workspace: str = Query("."),
        token: Optional[str] = Query(None),
    ) -> Dict[str, Any]:
        _require_token(request, token)
        supervisor = AutonomousSupervisor(project_name=project, workspace_root=workspace, interval_s=1, max_cycles=1)
        payload = supervisor.run_once()
        payload["signatures_valid"] = verify_artifact_signatures(payload["artifacts"], payload["artifact_signatures"])
        return payload

    @app.post("/gestate")
    def gestate(
        request: Request,
        project: str = Query("turboquant"),
        workspace: str = Query("."),
        interval: int = Query(1, ge=1),
        cycles: int = Query(5, ge=1, le=50),
        token: Optional[str] = Query(None),
    ) -> Dict[str, Any]:
        _require_token(request, token)
        payload = gestate_until_emergence(project_name=project, workspace_root=workspace, interval_s=interval, max_cycles=cycles)
        payload["signatures_valid"] = verify_artifact_signatures(payload["artifacts"], payload["artifact_signatures"])
        return payload

    @app.get("/summary")
    def summary(project: str = Query("turboquant"), workspace: str = Query(".")) -> Dict[str, str]:
        return {"summary": build_distributed_os_mesh(project_name=project, workspace_root=workspace)}
