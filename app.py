"""FastAPI entrypoint para deploy (ex.: Vercel)."""

from __future__ import annotations

from typing import Any, Dict

from distributed_os_agent_mesh import (
    AutonomousSupervisor,
    build_distributed_os_mesh,
    gestate_until_emergence,
    map_execution_environments,
)

try:
    from fastapi import FastAPI, Query
except ModuleNotFoundError:  # fallback para ambientes sem dependências instaladas
    class _MissingFastAPIApp:
        async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
            body = b"FastAPI nao instalado. Instale com: pip install -r requirements.txt"
            await send({"type": "http.response.start", "status": 500, "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": body})

    app = _MissingFastAPIApp()
else:
    app = FastAPI(title="TurboQuant Autonomous Mesh", version="1.0.0")

    @app.get("/")
    def root() -> Dict[str, Any]:
        return {
            "service": "turboquant-autonomous-mesh",
            "status": "ok",
            "routes": ["/health", "/run-once", "/gestate", "/environments", "/plan"],
        }

    @app.get("/health")
    def health() -> Dict[str, Any]:
        env_map = map_execution_environments()
        return {
            "status": "ok",
            "execution_target": env_map["execution_plan"]["target"],
            "acceleration": env_map["execution_plan"]["acceleration"],
        }

    @app.get("/environments")
    def environments() -> Dict[str, Any]:
        return map_execution_environments()["environment"]

    @app.get("/plan")
    def plan() -> Dict[str, Any]:
        return map_execution_environments()["execution_plan"]

    @app.post("/run-once")
    def run_once(project: str = Query("turboquant"), workspace: str = Query(".")) -> Dict[str, Any]:
        supervisor = AutonomousSupervisor(project_name=project, workspace_root=workspace, interval_s=1, max_cycles=1)
        supervisor.cycle = 1
        return supervisor.run_once()

    @app.post("/gestate")
    def gestate(
        project: str = Query("turboquant"),
        workspace: str = Query("."),
        interval: int = Query(1, ge=1),
        cycles: int = Query(5, ge=1, le=50),
    ) -> Dict[str, Any]:
        return gestate_until_emergence(project_name=project, workspace_root=workspace, interval_s=interval, max_cycles=cycles)

    @app.get("/summary")
    def summary(project: str = Query("turboquant"), workspace: str = Query(".")) -> Dict[str, str]:
        return {"summary": build_distributed_os_mesh(project_name=project, workspace_root=workspace)}
