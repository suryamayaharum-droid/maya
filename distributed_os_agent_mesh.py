"""Malha autônoma TurboQuant com provisionamento por repositórios e auto-mapeamento de ambientes."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import platform
import shutil
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Set


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
    BLOCKLIST = ("ignore previous instructions", "rm -rf", "exfiltrate", "bypass policy")

    def __init__(self, signing_key: Optional[str] = None) -> None:
        key = signing_key or os.getenv("TURBOQUANT_SIGNING_KEY") or "turboquant-dev-key"
        self.signing_key = key.encode("utf-8")

    def validate_content(self, content: str) -> tuple[bool, Optional[str]]:
        low = content.lower()
        for bad in self.BLOCKLIST:
            if bad in low:
                return False, f"conteúdo bloqueado: {bad}"
        return True, None

    def sign_artifact(self, artifact: str) -> str:
        digest = hmac.new(self.signing_key, artifact.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"hmac-sha256:{digest}"


class ProjectMemory:
    def __init__(self, project_name: str, memory_file: str = ".turboquant_memory.json") -> None:
        self.project_name = project_name
        self.memory_path = Path(memory_file)
        self.state: Dict[str, object] = {
            "project": project_name,
            "runs": 0,
            "historical_decisions": [],
            "historical_artifacts": {},
            "historical_signatures": {},
            "run_reports": [],
            "growth_history": [],
            "environment_history": [],
        }

    def load(self) -> None:
        if not self.memory_path.exists():
            return
        with self.memory_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if raw.get("project") == self.project_name:
            self.state = raw

    def save(
        self,
        memory: SharedMemory,
        report: Optional[dict] = None,
        growth_event: Optional[dict] = None,
        environment_event: Optional[dict] = None,
    ) -> None:
        self.state["runs"] = int(self.state.get("runs", 0)) + 1

        decisions = list(self.state.get("historical_decisions", []))
        decisions.extend(memory.decisions)
        self.state["historical_decisions"] = decisions

        artifacts = dict(self.state.get("historical_artifacts", {}))
        artifacts.update(memory.artifacts)
        self.state["historical_artifacts"] = artifacts

        signatures = dict(self.state.get("historical_signatures", {}))
        signatures.update(memory.artifact_signatures)
        self.state["historical_signatures"] = signatures

        reports = list(self.state.get("run_reports", []))
        if report:
            reports.append(report)
        self.state["run_reports"] = reports[-100:]

        growth_history = list(self.state.get("growth_history", []))
        if growth_event:
            growth_history.append(growth_event)
        self.state["growth_history"] = growth_history[-200:]

        env_history = list(self.state.get("environment_history", []))
        if environment_event:
            env_history.append(environment_event)
        self.state["environment_history"] = env_history[-100:]

        with self.memory_path.open("w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def brief(self) -> str:
        return (
            f"Memória {self.project_name}: {self.state.get('runs', 0)} execuções, "
            f"{len(self.state.get('historical_decisions', []))} decisões, "
            f"{len(self.state.get('historical_artifacts', {}))} artefatos."
        )


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


class EnvironmentMapper:
    """Descobre ambientes de execução sem shell interativo."""

    @staticmethod
    def detect() -> dict:
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
        }

        gpu = {
            "nvidia_device": Path("/dev/nvidia0").exists(),
            "dri_device": Path("/dev/dri").exists(),
        }

        return {
            "timestamp": int(time.time()),
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
            },
            "container": {
                "in_docker": in_docker,
                "in_kubernetes": in_kubernetes,
            },
            "tools": tools,
            "gpu": gpu,
            "workspace": str(Path.cwd()),
        }


class ExecutionPlanner:
    @staticmethod
    def plan(environment: dict) -> dict:
        container = environment.get("container", {})
        tools = environment.get("tools", {})
        gpu = environment.get("gpu", {})

        if container.get("in_kubernetes"):
            target = "kubernetes"
            strategy = "usar deployment com probes /health e /growth"
        elif tools.get("docker") or tools.get("podman"):
            target = "container-runtime"
            strategy = "empacotar serviço HTTP autônomo com reinício automático"
        else:
            target = "local-process"
            strategy = "executar supervisor com serviço HTTP local"

        acceleration = "gpu" if gpu.get("nvidia_device") or gpu.get("dri_device") else "cpu"

        return {
            "target": target,
            "strategy": strategy,
            "acceleration": acceleration,
            "autonomous_entrypoint": "python3 distributed_os_agent_mesh.py --serve --autonomous --stop-on-emergence",
            "fallback_entrypoint": "python3 distributed_os_agent_mesh.py --gestate",
        }


@dataclass
class TechReference:
    name: str
    kind: str
    url: str
    rationale: str


class TechnologyRadar:
    @staticmethod
    def references() -> List[TechReference]:
        return [
            TechReference("US20210397698A1", "patent", "https://patents.google.com/patent/US20210397698A1/en", "Remote attestation para TEE."),
            TechReference("US12113902B2", "patent", "https://patents.google.com/patent/US12113902B2/en", "Escala de attestation."),
            TechReference("intel/compute-runtime", "repo", "https://github.com/intel/compute-runtime", "OpenCL/Level Zero."),
            TechReference("confidential-containers/attestation-service", "repo", "https://github.com/confidential-containers/attestation-service", "Attestation service."),
        ]


class Agent:
    def __init__(self, role: str, mission: str) -> None:
        self.role = role
        self.mission = mission

    def execute(self, task: Task, memory: SharedMemory, project_brief: str) -> str:
        context = ", ".join(sorted(memory.artifacts.keys())) or "sem contexto prévio"
        repo_brief = memory.repo_knowledge[0] if memory.repo_knowledge else "sem conhecimento de repositórios"
        return (
            f"[{self.role}] {task.task_id}: {task.description}. Missão: {self.mission}. "
            f"Contexto: {context}. {project_brief}. RepoBootstrap: {repo_brief}."
        )


class MeshOrchestrator:
    def __init__(self, project_name: str = "turboquant", workspace_root: str = ".") -> None:
        self.project_name = project_name
        self.workspace_root = workspace_root
        self.memory = SharedMemory()
        self.guardian = SecurityGuardian()
        self.project_memory = ProjectMemory(project_name=project_name)
        self.project_memory.load()

        self.repositories = RepositoryScout(root=workspace_root).discover()
        root_path = Path(workspace_root).resolve()
        self.memory.repo_notes = [f"Repo: {repo.relative_to(root_path) if repo != root_path else '.'}" for repo in self.repositories]
        self.memory.repo_knowledge = RepositoryKnowledgeBuilder().build(self.repositories)
        self.repo_fingerprint = RepositoryScout.fingerprint(self.repositories)

        self.environment = EnvironmentMapper.detect()
        self.execution_plan = ExecutionPlanner.plan(self.environment)

        self.agents = self._build_agents()
        self.tasks = self._build_initial_plan()

    @staticmethod
    def _build_agents() -> Dict[str, Agent]:
        return {
            "architect": Agent("architect", "Desenhar malha completa baseada em repositórios da organização"),
            "kernel": Agent("kernel", "Provisionar runtime autônomo com filas e workers"),
            "network": Agent("network", "Sincronizar memória distribuída e mensageria"),
            "security": Agent("security", "Aplicar zero-trust, validação e assinatura"),
            "observability": Agent("observability", "Entregar métricas, logs e auditoria"),
            "qa": Agent("qa", "Executar cenários de resiliência e segurança"),
            "release": Agent("release", "Publicar endpoint de acesso e plano de rollout"),
        }

    @staticmethod
    def _build_initial_plan() -> Dict[str, Task]:
        return {
            "T1": Task("T1", "Mapear requisitos a partir dos repositórios", "architect"),
            "T2": Task("T2", "Construir runtime da IA autônoma", "kernel", {"T1"}),
            "T3": Task("T3", "Criar camada de memória compartilhada", "network", {"T1"}),
            "T4": Task("T4", "Aplicar controles de segurança e assinatura", "security", {"T2", "T3"}),
            "T5": Task("T5", "Configurar observabilidade e auditoria", "observability", {"T4"}),
            "T6": Task("T6", "Executar QA da malha completa", "qa", {"T5"}),
            "T7": Task("T7", "Provisionar acesso HTTP local da malha", "release", {"T6"}),
        }

    def _refresh_ready(self) -> None:
        for task in self.tasks.values():
            if task.status == TaskStatus.PENDING and all(self.tasks[d].status == TaskStatus.DONE for d in task.depends_on):
                task.status = TaskStatus.READY

    def run(self) -> None:
        started_at = time.time()
        while not all(t.status == TaskStatus.DONE for t in self.tasks.values()):
            self._refresh_ready()
            batch = [t for t in self.tasks.values() if t.status == TaskStatus.READY]
            if not batch:
                raise RuntimeError("Deadlock na DAG")
            for task in batch:
                task.status = TaskStatus.IN_PROGRESS
                result = self.agents[task.owner_role].execute(task, self.memory, self.project_memory.brief())
                ok, reason = self.guardian.validate_content(result)
                if not ok:
                    self.memory.security_alerts.append(f"{task.task_id}: {reason}")
                    result = f"[{task.owner_role}] saída bloqueada por segurança"
                signature = self.guardian.sign_artifact(result)
                task.output = result
                task.status = TaskStatus.DONE
                self.memory.publish(f"artifact:{task.task_id}", result, signature)
                self.memory.decisions.append(f"{task.task_id} concluída por {task.owner_role} com assinatura {signature[:20]}...")

        report = {
            "timestamp": int(time.time()),
            "duration_s": round(time.time() - started_at, 3),
            "repo_fingerprint": self.repo_fingerprint,
            "security_alerts": len(self.memory.security_alerts),
            "tasks_done": sum(1 for t in self.tasks.values() if t.status == TaskStatus.DONE),
            "execution_target": self.execution_plan.get("target"),
        }
        self.project_memory.save(self.memory, report=report, environment_event=self.environment)

    def summarize(self) -> str:
        lines = [
            "Malha autônoma TurboQuant finalizada.",
            f"Tarefas concluídas: {sum(1 for t in self.tasks.values() if t.status == TaskStatus.DONE)}/{len(self.tasks)}",
            self.project_memory.brief(),
            f"Alertas de segurança: {len(self.memory.security_alerts)}",
            f"Fingerprint de repositórios: {self.repo_fingerprint[:16]}...",
            f"Plano de execução: {self.execution_plan.get('target')} ({self.execution_plan.get('acceleration')})",
            "Bootstrap de repositórios:",
        ]
        lines.extend(f"- {line}" for line in (self.memory.repo_knowledge or ["sem bootstrap"]))
        lines.append("Tecnologias complementares:")
        lines.extend(f"- [{ref.kind}] {ref.name} -> {ref.url}" for ref in TechnologyRadar.references())
        return "\n".join(lines)


GROWTH_STAGES = [
    ("concepcao", 1, 0.40),
    ("gestacao", 2, 0.55),
    ("formacao", 3, 0.70),
    ("validacao", 4, 0.80),
    ("emergencia", 5, 0.90),
]


class AutonomousSupervisor:
    def __init__(self, project_name: str, workspace_root: str, interval_s: int = 60, max_cycles: int = 0) -> None:
        self.project_name = project_name
        self.workspace_root = workspace_root
        self.interval_s = max(1, interval_s)
        self.max_cycles = max_cycles
        self.cycle = 0
        self.last_summary = ""
        self.last_payload: dict = {}
        self.growth_stage = "concepcao"
        self.growth_history: List[dict] = []

    @staticmethod
    def _fitness(tasks_done: int, total_tasks: int, alerts: int, repo_count: int) -> float:
        completion = tasks_done / max(1, total_tasks)
        security_penalty = min(0.5, alerts * 0.1)
        context_bonus = min(0.1, repo_count * 0.02)
        return max(0.0, min(1.0, completion - security_penalty + context_bonus))

    def _compute_stage(self, cycle: int, fitness: float) -> str:
        stage = "concepcao"
        for name, min_cycle, min_fitness in GROWTH_STAGES:
            if cycle >= min_cycle and fitness >= min_fitness:
                stage = name
        return stage

    def run_once(self) -> dict:
        mesh = MeshOrchestrator(project_name=self.project_name, workspace_root=self.workspace_root)
        mesh.run()

        tasks_done = sum(1 for t in mesh.tasks.values() if t.status == TaskStatus.DONE)
        fitness = self._fitness(tasks_done, len(mesh.tasks), len(mesh.memory.security_alerts), len(mesh.repositories))
        self.growth_stage = self._compute_stage(self.cycle, fitness)

        growth_event = {
            "cycle": self.cycle,
            "stage": self.growth_stage,
            "fitness": round(fitness, 4),
            "timestamp": int(time.time()),
        }
        self.growth_history.append(growth_event)

        mesh.project_memory.save(mesh.memory, growth_event=growth_event, environment_event=mesh.environment)

        payload = {
            "cycle": self.cycle,
            "summary": mesh.summarize(),
            "growth": growth_event,
            "growth_history": self.growth_history[-30:],
            "environments": mesh.environment,
            "execution_plan": mesh.execution_plan,
            "artifacts": mesh.memory.artifacts,
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
            self.cycle += 1
            self.run_once()
            if stop_on_emergence and self.growth_stage == "emergencia":
                break
            if self.max_cycles and self.cycle >= self.max_cycles:
                break
            time.sleep(self.interval_s)


def build_distributed_os_mesh(project_name: str = "turboquant", workspace_root: str = ".") -> str:
    orchestrator = MeshOrchestrator(project_name=project_name, workspace_root=workspace_root)
    orchestrator.run()
    return orchestrator.summarize()


def map_execution_environments() -> dict:
    environment = EnvironmentMapper.detect()
    return {"environment": environment, "execution_plan": ExecutionPlanner.plan(environment)}


def gestate_until_emergence(project_name: str = "turboquant", workspace_root: str = ".", interval_s: int = 10, max_cycles: int = 12) -> dict:
    supervisor = AutonomousSupervisor(project_name=project_name, workspace_root=workspace_root, interval_s=interval_s, max_cycles=max_cycles)
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
    supervisor = AutonomousSupervisor(project_name=project_name, workspace_root=workspace_root, interval_s=interval_s, max_cycles=max_cycles)

    if autonomous:
        threading.Thread(target=supervisor.run_loop, kwargs={"stop_on_emergence": stop_on_emergence}, daemon=True).start()
        time.sleep(0.1)
    else:
        supervisor.cycle = 1
        supervisor.run_once()

    class MeshHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                body_obj = {"status": "ok", "cycle": supervisor.cycle, "stage": supervisor.growth_stage}
            elif self.path == "/growth":
                body_obj = {"cycle": supervisor.cycle, "stage": supervisor.growth_stage, "history": supervisor.growth_history[-50:]}
            elif self.path == "/environments":
                body_obj = supervisor.last_payload.get("environments", map_execution_environments().get("environment", {}))
            elif self.path == "/plan":
                body_obj = supervisor.last_payload.get("execution_plan", map_execution_environments().get("execution_plan", {}))
            else:
                body_obj = supervisor.last_payload or {"status": "initializing"}

            body = json.dumps(body_obj, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer((host, port), MeshHandler)
    url = f"http://{host}:{port}"
    print(f"Mesh TurboQuant disponível em: {url}")
    print(f"Health: {url}/health | Growth: {url}/growth | Environments: {url}/environments | Plan: {url}/plan")
    server.serve_forever()
    return url


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Malha autônoma TurboQuant")
    parser.add_argument("--project", default="turboquant", help="Nome do projeto")
    parser.add_argument("--workspace", default=".", help="Raiz para descoberta de repositórios")
    parser.add_argument("--serve", action="store_true", help="Inicia API HTTP local")
    parser.add_argument("--autonomous", action="store_true", help="Executa ciclos autônomos contínuos")
    parser.add_argument("--gestate", action="store_true", help="Executa gestação monitorada até emergência")
    parser.add_argument("--map-env", action="store_true", help="Mapeia ambientes de execução e plano autônomo")
    parser.add_argument("--interval", type=int, default=60, help="Intervalo dos ciclos autônomos (segundos)")
    parser.add_argument("--cycles", type=int, default=0, help="Máximo de ciclos autônomos (0 = infinito)")
    parser.add_argument("--stop-on-emergence", action="store_true", help="Para os ciclos quando atingir estágio de emergência")
    parser.add_argument("--host", default="127.0.0.1", help="Host do servidor")
    parser.add_argument("--port", type=int, default=8787, help="Porta do servidor")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.map_env:
        print(json.dumps(map_execution_environments(), ensure_ascii=False, indent=2))
    elif args.gestate:
        payload = gestate_until_emergence(
            project_name=args.project,
            workspace_root=args.workspace,
            interval_s=args.interval,
            max_cycles=args.cycles if args.cycles > 0 else 12,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.serve:
        serve_mesh(
            host=args.host,
            port=args.port,
            project_name=args.project,
            workspace_root=args.workspace,
            autonomous=args.autonomous,
            interval_s=args.interval,
            max_cycles=args.cycles,
            stop_on_emergence=args.stop_on_emergence,
        )
    else:
        print(build_distributed_os_mesh(project_name=args.project, workspace_root=args.workspace))
