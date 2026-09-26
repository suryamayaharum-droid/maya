"""Núcleo da malha autônoma TurboQuant v2 — DAG paralela, memória SQLite,
inferência plugável (LLM local ou determinístico), segurança verificável.

Evolução sobre v1 (distributed_os_agent_mesh.py):
- DAG executada em **lotes topológicos paralelos** (ThreadPoolExecutor dimensionado
  ao host; sem GPU, o ganho vem de I/O e numpy que liberam a GIL).
- Memória persistente migrada de JSON reescrito-por-completo para **SQLite WAL**
  (:mod:`turboquant.store`) com busca semântica + deduplicação MinHash/LSH.
- Agentes usam :class:`turboquant.inference.InferenceEngine`: se houver Ollama
  local, raciocínio real em CPU; senão, gerador determinístico reprodutível.
- Whitening anisotrópico aplicado aos embeddings indexados (cones of dominance).
- Supervisor mantém estágios de crescimento e agora publica eventos no store.
- Compatibilidade retroativa: mesmas funções públicas exportadas.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import platform
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from turboquant.cpu_compute import (
    MinHasher,
    cpu_optimization_plan,
    deduplicate,
    detect_acceleration,
)
from turboquant.inference import InferenceEngine
from turboquant.store import MeshStore


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    DONE = "done"


@dataclass
class Task:
    task_id: str
    description: str
    owner_role: str
    depends_on: Set[str] = field(default_factory=set)
    status: TaskStatus = TaskStatus.PENDING
    output: Optional[str] = None


@dataclass
class SharedMemory:
    artifacts: Dict[str, str] = field(default_factory=dict)
    artifact_signatures: Dict[str, str] = field(default_factory=dict)
    decisions: List[str] = field(default_factory=list)
    repo_notes: List[str] = field(default_factory=list)
    repo_knowledge: List[str] = field(default_factory=list)
    security_alerts: List[str] = field(default_factory=list)

    def publish(self, key: str, value: str, signature: str) -> None:
        self.artifacts[key] = value
        self.artifact_signatures[key] = signature


class SecurityGuardian:
    BLOCKLIST = (
        "ignore previous instructions",
        "ignore all previous",
        "rm -rf",
        "exfiltrate",
        "bypass policy",
        "system prompt reveal",
    )

    def __init__(self, signing_key: Optional[str] = None) -> None:
        key = signing_key or os.getenv("TURBOQUANT_SIGNING_KEY") or "turboquant-dev-key"
        if key == "turboquant-dev-key" and os.getenv("TURBOQUANT_REQUIRE_REAL_KEY"):
            raise RuntimeError(
                "TURBOQUANT_REQUIRE_REAL_KEY definido mas TURBOQUANT_SIGNING_KEY ausente — "
                "recuse chave de desenvolvimento em produção."
            )
        self.using_dev_key = key == "turboquant-dev-key"
        self.signing_key = key.encode("utf-8")

    def validate_content(self, content: str) -> Tuple[bool, Optional[str]]:
        low = content.lower()
        for bad in self.BLOCKLIST:
            if bad in low:
                return False, f"conteudo bloqueado: {bad}"
        return True, None

    def sign_artifact(self, artifact: str) -> str:
        digest = hmac.new(self.signing_key, artifact.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"hmac-sha256:{digest}"

    def verify_signature(self, artifact: str, signature: str) -> bool:
        return hmac.compare_digest(self.sign_artifact(artifact), signature or "")


# --------------------------------------------------------------------------
# Descoberta / conhecimento de repositórios
# --------------------------------------------------------------------------

class RepositoryScout:
    def __init__(self, root: str = ".") -> None:
        self.root = Path(root).resolve()

    def discover(self, limit: int = 20) -> List[Path]:
        repos: List[Path] = []
        for git_dir in self.root.glob("**/.git"):
            repos.append(git_dir.parent)
            if len(repos) >= limit:
                break
        return repos

    @staticmethod
    def fingerprint(repositories: List[Path]) -> str:
        data = "|".join(sorted(str(p.resolve()) for p in repositories))
        return hashlib.sha256(data.encode("utf-8")).hexdigest()


class RepositoryKnowledgeBuilder:
    def build(self, repositories: List[Path], max_files_per_repo: int = 6) -> List[str]:
        knowledge: List[str] = []
        for repo in repositories:
            selected_files: List[Path] = []
            for pattern in ("README*", "*.py", "*.md", "*.yaml", "*.yml"):
                selected_files.extend(sorted(repo.glob(pattern)))
            selected_files = [f for f in selected_files if f.is_file()][:max_files_per_repo]
            if not selected_files:
                knowledge.append(f"{repo.name}: sem arquivos relevantes para bootstrap.")
                continue
            snippets = []
            for file_path in selected_files:
                try:
                    text = file_path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                head = " ".join(text.strip().splitlines()[:3])[:220]
                snippets.append(f"{file_path.name}: {head or 'arquivo vazio'}")
            knowledge.append(f"{repo.name}: " + " | ".join(snippets[:3]))
        return knowledge


# --------------------------------------------------------------------------
# Ambiente / plano de execução (honesto sobre CPU)
# --------------------------------------------------------------------------

class EnvironmentMapper:
    @staticmethod
    def detect() -> dict:
        accel = detect_acceleration()
        try:
            root_cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="ignore")
        except OSError:
            root_cgroup = ""
        in_docker = Path("/.dockerenv").exists() or "docker" in root_cgroup or "containerd" in root_cgroup
        in_kubernetes = bool(os.getenv("KUBERNETES_SERVICE_HOST"))
        tools = {
            "python3": bool(shutil.which("python3")),
            "docker": bool(shutil.which("docker")),
            "podman": bool(shutil.which("podman")),
            "kubectl": bool(shutil.which("kubectl")),
            "git": bool(shutil.which("git")),
            "ollama": bool(shutil.which("ollama")),
        }
        return {
            "timestamp": int(time.time()),
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
            },
            "container": {"in_docker": in_docker, "in_kubernetes": in_kubernetes},
            "tools": tools,
            "gpu": {
                "nvidia_device": accel["gpu_nvidia"],
                "amd_device": accel["gpu_amd"],
                "intel_dri": accel["gpu_intel_dri"],
            },
            "cpu": accel["cpu"],
            "memory_mb": accel["memory"],
            "workspace": str(Path.cwd()),
        }


class ExecutionPlanner:
    @staticmethod
    def plan(environment: dict) -> dict:
        container = environment.get("container", {})
        tools = environment.get("tools", {})
        gpu = environment.get("gpu", {})
        cores = environment.get("cpu", {}).get("cores_usaveis", 1)

        if container.get("in_kubernetes"):
            target = "kubernetes"
            strategy = "usar deployment com probes /health e /growth"
        elif tools.get("docker") or tools.get("podman"):
            target = "container-runtime"
            strategy = "empacotar servico HTTP autonomo com reinicio automatico"
        else:
            target = "local-process"
            strategy = "executar supervisor com servico HTTP local"

        acceleration = "gpu" if (gpu.get("nvidia_device") or gpu.get("amd_device")) else "cpu"
        workers = max(1, min(4, int(cores)))

        return {
            "target": target,
            "strategy": strategy,
            "acceleration": acceleration,
            "parallel_workers": workers,
            "cpu_playbook": cpu_optimization_plan()["modes"] if acceleration == "cpu" else [],
            "autonomous_entrypoint": "python3 -m turboquant.cli --serve --autonomous --stop-on-emergence",
            "fallback_entrypoint": "python3 -m turboquant.cli --gestate",
        }


# --------------------------------------------------------------------------
# Agentes + orquestrador DAG paralelo
# --------------------------------------------------------------------------

class Agent:
    def __init__(self, role: str, mission: str, engine: InferenceEngine) -> None:
        self.role = role
        self.mission = mission
        self.engine = engine

    def execute(self, task: Task, memory: SharedMemory, project_brief: str, context: dict) -> str:
        ctx_keys = ", ".join(sorted(memory.artifacts.keys())) or "sem contexto previo"
        repo_brief = memory.repo_knowledge[0] if memory.repo_knowledge else "sem conhecimento de repositorios"
        base = self.engine.complete(
            self.role,
            task.description,
            {**context, "memory_brief": project_brief},
        )
        return (
            f"[{self.role}] {task.task_id}: {task.description}. Missao: {self.mission}. "
            f"{base} Contexto: {ctx_keys}. {project_brief}. RepoBootstrap: {repo_brief}."
        )


GROWTH_STAGES = [
    ("concepcao", 1, 0.40),
    ("gestacao", 2, 0.55),
    ("formacao", 3, 0.70),
    ("validacao", 4, 0.80),
    ("emergencia", 5, 0.90),
]


class MeshOrchestrator:
    def __init__(
        self,
        project_name: str = "turboquant",
        workspace_root: str = ".",
        engine: Optional[InferenceEngine] = None,
    ) -> None:
        self.project_name = project_name
        self.workspace_root = workspace_root
        self.memory = SharedMemory()
        self.guardian = SecurityGuardian()
        self.store = MeshStore(project_name=project_name, workspace_root=workspace_root)
        self.engine = engine or InferenceEngine(prefer_llm=True)

        self.repositories = RepositoryScout(root=workspace_root).discover()
        root_path = Path(workspace_root).resolve()
        self.memory.repo_notes = [
            f"Repo: {repo.relative_to(root_path) if repo != root_path else '.'}"
            for repo in self.repositories
        ]
        self.memory.repo_knowledge = RepositoryKnowledgeBuilder().build(self.repositories)
        self.repo_fingerprint = RepositoryScout.fingerprint(self.repositories)

        self.environment = EnvironmentMapper.detect()
        self.execution_plan = ExecutionPlanner.plan(self.environment)

        self.agents = self._build_agents()
        self.tasks = self._build_initial_plan()
        self._lock = threading.Lock()

    @staticmethod
    def _build_agents_static(engine: InferenceEngine) -> Dict[str, Agent]:
        return {
            "architect": Agent("architect", "Desenhar malha completa baseada em repositorios da organizacao", engine),
            "kernel": Agent("kernel", "Provisionar runtime autonomo com filas e workers", engine),
            "network": Agent("network", "Sincronizar memoria distribuida e mensageria", engine),
            "security": Agent("security", "Aplicar zero-trust, validacao e assinatura", engine),
            "observability": Agent("observability", "Entregar metricas, logs e auditoria", engine),
            "qa": Agent("qa", "Executar cenarios de resiliencia e seguranca", engine),
            "release": Agent("release", "Publicar endpoint de acesso e plano de rollout", engine),
        }

    def _build_agents(self) -> Dict[str, Agent]:
        return self._build_agents_static(self.engine)

    @staticmethod
    def _build_initial_plan() -> Dict[str, Task]:
        return {
            "T1": Task("T1", "Mapear requisitos a partir dos repositorios", "architect"),
            "T2": Task("T2", "Construir runtime da IA autonoma", "kernel", {"T1"}),
            "T3": Task("T3", "Criar camada de memoria compartilhada", "network", {"T1"}),
            "T4": Task("T4", "Aplicar controles de seguranca e assinatura", "security", {"T2", "T3"}),
            "T5": Task("T5", "Configurar observabilidade e auditoria", "observability", {"T4"}),
            "T6": Task("T6", "Executar QA da malha completa", "qa", {"T5"}),
            "T7": Task("T7", "Provisionar acesso HTTP local da malha", "release", {"T6"}),
        }

    def _refresh_ready(self) -> List[Task]:
        ready: List[Task] = []
        for task in self.tasks.values():
            if task.status == TaskStatus.PENDING and all(
                self.tasks[d].status == TaskStatus.DONE for d in task.depends_on
            ):
                task.status = TaskStatus.READY
                ready.append(task)
        return ready

    def _run_task(self, task: Task, context: dict) -> None:
        agent = self.agents[task.owner_role]
        result = agent.execute(task, self.memory, self.store.brief(), context)
        ok, reason = self.guardian.validate_content(result)
        with self._lock:
            if not ok:
                self.memory.security_alerts.append(f"{task.task_id}: {reason}")
                result = f"[{task.owner_role}] saida bloqueada por seguranca"
            signature = self.guardian.sign_artifact(result)
            task.output = result
            task.status = TaskStatus.DONE
            self.memory.publish(f"artifact:{task.task_id}", result, signature)
            self.memory.decisions.append(
                f"{task.task_id} concluida por {task.owner_role} com assinatura {signature[:20]}..."
            )

    def run(self) -> None:
        started_at = time.time()
        context = {
            "cores_usaveis": self.environment.get("cpu", {}).get("cores_usaveis", 1),
            "modo_calculo": self.execution_plan.get("acceleration", "cpu"),
            "repo_fingerprint": self.repo_fingerprint,
        }
        workers = int(self.execution_plan.get("parallel_workers", 1))
        while not all(t.status == TaskStatus.DONE for t in self.tasks.values()):
            batch = self._refresh_ready()
            if not batch:
                raise RuntimeError("Deadlock na DAG")
            if len(batch) == 1 or workers <= 1:
                for task in batch:
                    task.status = TaskStatus.IN_PROGRESS
                    self._run_task(task, context)
            else:
                # lote topológico independente → executa em paralelo (CPU-first:
                # threads bastam pois agentes fazem I/O e aritmética que libera GIL)
                for task in batch:
                    task.status = TaskStatus.IN_PROGRESS
                with ThreadPoolExecutor(max_workers=min(workers, len(batch))) as pool:
                    list(pool.map(lambda t: self._run_task(t, context), batch))

        # pós-processamento inteligente: dedup semanticamente redundante via LSH
        dupes = deduplicate(self.memory.artifacts, threshold=0.9)
        report = {
            "timestamp": int(time.time()),
            "duration_s": round(time.time() - started_at, 3),
            "repo_fingerprint": self.repo_fingerprint,
            "security_alerts": len(self.memory.security_alerts),
            "tasks_done": sum(1 for t in self.tasks.values() if t.status == TaskStatus.DONE),
            "execution_target": self.execution_plan.get("target"),
            "backend_inferencia": self.engine.backend,
            "duplicatas_lsh": len(dupes),
        }
        self.persist(report)

    def persist(self, report: dict) -> None:
        cycle = self.store.bump_runs()
        for key, value in self.memory.artifacts.items():
            self.store.publish_artifact(key, value, self.memory.artifact_signatures[key], cycle=cycle)
        self.store.add_decisions(self.memory.decisions, cycle=cycle)
        self.store.add_environment(self.environment)
        for key, value in self.memory.artifacts.items():
            if self.store.nearest_neighbor_exists(value) is None:
                self.store.index_text("artifact", key, value)
        for note in self.memory.repo_knowledge:
            self.store.index_text("repo", note[:40], note)

    def summarize(self) -> str:
        lines = [
            "Malha autonoma TurboQuant finalizada.",
            f"Tarefas concluidas: {sum(1 for t in self.tasks.values() if t.status == TaskStatus.DONE)}/{len(self.tasks)}",
            self.store.brief(),
            f"Backend de inferencia: {self.engine.backend}",
            f"Alertas de seguranca: {len(self.memory.security_alerts)}",
            f"Fingerprint de repositorios: {self.repo_fingerprint[:16]}...",
            f"Plano de execucao: {self.execution_plan.get('target')} ({self.execution_plan.get('acceleration')}, {self.execution_plan.get('parallel_workers')} workers)",
            "Bootstrap de repositorios:",
        ]
        lines.extend(f"- {line}" for line in (self.memory.repo_knowledge or ["sem bootstrap"]))
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Supervisor autônomo com estágios de crescimento
# --------------------------------------------------------------------------

class AutonomousSupervisor:
    def __init__(
        self,
        project_name: str,
        workspace_root: str,
        interval_s: int = 60,
        max_cycles: int = 0,
        engine: Optional[InferenceEngine] = None,
    ) -> None:
        self.project_name = project_name
        self.workspace_root = workspace_root
        self.interval_s = max(1, interval_s)
        self.max_cycles = max_cycles
        self.cycle = 0
        self.last_summary = ""
        self.last_payload: dict = {}
        self.growth_stage = "concepcao"
        self.growth_history: List[dict] = []
        self.engine = engine or InferenceEngine(prefer_llm=True)

    @staticmethod
    def _fitness(tasks_done: int, total_tasks: int, alerts: int, repo_count: int) -> float:
        completion = tasks_done / max(1, total_tasks)
        security_penalty = min(0.5, alerts * 0.1)
        context_bonus = min(0.1, repo_count * 0.02)
        return max(0.0, min(1.0, completion - security_penalty + context_bonus))

    @staticmethod
    def _compute_stage(cycle: int, fitness: float) -> str:
        stage = "concepcao"
        for name, min_cycle, min_fitness in GROWTH_STAGES:
            if cycle >= min_cycle and fitness >= min_fitness:
                stage = name
        return stage

    def run_once(self) -> dict:
        mesh = MeshOrchestrator(
            project_name=self.project_name,
            workspace_root=self.workspace_root,
            engine=self.engine,
        )
        mesh.run()

        tasks_done = sum(1 for t in mesh.tasks.values() if t.status == TaskStatus.DONE)
        fitness = self._fitness(tasks_done, len(mesh.tasks), len(mesh.memory.security_alerts), len(mesh.repositories))
        self.cycle += 1
        self.growth_stage = self._compute_stage(self.cycle, fitness)

        growth_event = {
            "cycle": self.cycle,
            "stage": self.growth_stage,
            "fitness": round(fitness, 4),
            "timestamp": int(time.time()),
        }
        self.growth_history.append(growth_event)
        mesh.store.add_growth(self.cycle, self.growth_stage, fitness)

        payload = {
            "cycle": self.cycle,
            "summary": mesh.summarize(),
            "growth": growth_event,
            "growth_history": self.growth_history[-30:],
            "whiteness": mesh.store.whiteness_report(),
            "environments": mesh.environment,
            "execution_plan": mesh.execution_plan,
            "artifacts": mesh.memory.artifacts,
            "artifact_signatures": mesh.memory.artifact_signatures,
            "decisions": mesh.memory.decisions,
            "security_alerts": mesh.memory.security_alerts,
            "repo_fingerprint": mesh.repo_fingerprint,
            "timestamp": int(time.time()),
        }
        self.last_summary = payload["summary"]
        self.last_payload = payload
        return payload

    def run_loop(self, stop_on_emergence: bool = True) -> None:
        while True:
            attempted = self.cycle + 1
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 — supervisor nunca morre por um ciclo falho
                self.cycle = attempted  # garante avanço mesmo em falha (evita loop infinito de retry no mesmo ciclo)
                time.sleep(min(self.interval_s, 5))
                if self.max_cycles and self.cycle >= self.max_cycles:
                    break
                continue
            if stop_on_emergence and self.growth_stage == "emergencia":
                break
            if self.max_cycles and self.cycle >= self.max_cycles:
                break
            time.sleep(self.interval_s)


# --------------------------------------------------------------------------
# API pública compatível com v1
# --------------------------------------------------------------------------

def build_distributed_os_mesh(project_name: str = "turboquant", workspace_root: str = ".") -> str:
    orchestrator = MeshOrchestrator(project_name=project_name, workspace_root=workspace_root)
    orchestrator.run()
    return orchestrator.summarize()


def verify_artifact_signatures(artifacts: Dict[str, str], signatures: Dict[str, str]) -> bool:
    guardian = SecurityGuardian()
    if not artifacts or set(artifacts) != set(signatures):
        return False
    return all(guardian.verify_signature(artifacts[key], signatures[key]) for key in artifacts)


def read_growth_history(project_name: str = "turboquant", workspace_root: str = ".") -> dict:
    store = MeshStore(project_name=project_name, workspace_root=workspace_root)
    history = store.growth_history(limit=200)
    latest = history[-1] if history else None
    return {
        "project": project_name,
        "runs": store.runs,
        "stage": (latest or {}).get("stage", "concepcao"),
        "cycle": (latest or {}).get("cycle", 0),
        "history": history[-50:],
    }


def map_execution_environments() -> dict:
    environment = EnvironmentMapper.detect()
    return {"environment": environment, "execution_plan": ExecutionPlanner.plan(environment)}


def gestate_until_emergence(
    project_name: str = "turboquant",
    workspace_root: str = ".",
    interval_s: int = 10,
    max_cycles: int = 12,
) -> dict:
    supervisor = AutonomousSupervisor(
        project_name=project_name,
        workspace_root=workspace_root,
        interval_s=interval_s,
        max_cycles=max_cycles,
    )
    supervisor.run_loop(stop_on_emergence=True)
    return supervisor.last_payload


def serve_mesh(
    host: str = "127.0.0.1",
    port: int = 8787,
    project_name: str = "turboquant",
    workspace_root: str = ".",
    autonomous: bool = False,
    interval_s: int = 60,
    max_cycles: int = 0,
    stop_on_emergence: bool = True,
) -> str:
    supervisor = AutonomousSupervisor(
        project_name=project_name,
        workspace_root=workspace_root,
        interval_s=interval_s,
        max_cycles=max_cycles,
    )

    if autonomous:
        threading.Thread(target=supervisor.run_loop, kwargs={"stop_on_emergence": stop_on_emergence}, daemon=True).start()
        time.sleep(0.1)
    else:
        supervisor.run_once()

    class MeshHandler(BaseHTTPRequestHandler):
        def _send_json(self, body_obj: object, status: int = 200) -> None:
            body = json.dumps(body_obj, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            if path == "/health":
                self._send_json({"status": "ok", "cycle": supervisor.cycle, "stage": supervisor.growth_stage})
            elif path == "/growth":
                self._send_json({"cycle": supervisor.cycle, "stage": supervisor.growth_stage, "history": supervisor.growth_history[-50:]})
            elif path == "/environments":
                self._send_json(supervisor.last_payload.get("environments", map_execution_environments()["environment"]))
            elif path == "/plan":
                self._send_json(supervisor.last_payload.get("execution_plan", map_execution_environments()["execution_plan"]))
            elif path == "/":
                self._send_json(supervisor.last_payload or {"status": "initializing"})
            else:
                self._send_json({"error": "rota nao encontrada", "routes": ["/", "/health", "/growth", "/environments", "/plan"]}, status=404)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), MeshHandler)
    url = f"http://{host}:{port}"
    print(f"Mesh TurboQuant disponivel em: {url}")
    server.serve_forever()
    return url


if __name__ == "__main__":
    from turboquant.cli import main

    main()
