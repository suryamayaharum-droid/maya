import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
import asgi as asgi_module
import main as main_module
from distributed_os_agent_mesh import (
    AutonomousSupervisor,
    MeshOrchestrator,
    build_distributed_os_mesh,
    gestate_until_emergence,
    map_execution_environments,
    read_growth_history,
    verify_artifact_signatures,
)


VALID_STAGES = {"concepcao", "gestacao", "formacao", "validacao", "emergencia"}


class MeshTests(unittest.TestCase):
    def test_fastapi_entrypoints_exposed(self):
        self.assertTrue(hasattr(app_module, "app"))
        self.assertTrue(hasattr(main_module, "app"))
        self.assertTrue(hasattr(asgi_module, "app"))

    def test_mesh_runs_and_completes_tasks(self):
        summary = build_distributed_os_mesh(project_name="turboquant-test", workspace_root=".")
        self.assertIn("Tarefas concluídas: 7/7", summary)

    def test_artifacts_are_signed(self):
        orchestrator = MeshOrchestrator(project_name="turboquant-test-2", workspace_root=".")
        orchestrator.run()
        self.assertEqual(len(orchestrator.memory.artifacts), 7)
        self.assertEqual(len(orchestrator.memory.artifact_signatures), 7)
        for sig in orchestrator.memory.artifact_signatures.values():
            self.assertTrue(sig.startswith("hmac-sha256:"))

    def test_environment_mapping_and_plan(self):
        mapped = map_execution_environments()
        self.assertIn("environment", mapped)
        self.assertIn("execution_plan", mapped)
        self.assertIn("platform", mapped["environment"])
        self.assertIn("target", mapped["execution_plan"])

    def test_autonomous_supervisor_single_cycle(self):
        supervisor = AutonomousSupervisor(
            project_name="turboquant-test-3",
            workspace_root=".",
            interval_s=1,
            max_cycles=1,
        )
        supervisor.cycle = 1
        payload = supervisor.run_once()
        self.assertEqual(payload["cycle"], 1)
        self.assertIn("environments", payload)
        self.assertIn("execution_plan", payload)
        self.assertIn(payload["growth"]["stage"], VALID_STAGES)

    def test_gestation_monitoring_payload(self):
        payload = gestate_until_emergence(
            project_name="turboquant-test-4",
            workspace_root=".",
            interval_s=1,
            max_cycles=3,
        )
        self.assertIn("growth", payload)
        self.assertIn("growth_history", payload)
        self.assertGreaterEqual(len(payload["growth_history"]), 1)
        self.assertIn(payload["growth"]["stage"], VALID_STAGES)

    def test_artifact_signature_verification(self):
        orchestrator = MeshOrchestrator(project_name="turboquant-test-5", workspace_root=".")
        orchestrator.run()
        self.assertTrue(
            verify_artifact_signatures(orchestrator.memory.artifacts, orchestrator.memory.artifact_signatures)
        )
        tampered = dict(orchestrator.memory.artifacts)
        first_key = next(iter(tampered))
        tampered[first_key] += " (adulterado)"
        self.assertFalse(verify_artifact_signatures(tampered, orchestrator.memory.artifact_signatures))

    def test_memory_isolated_per_project_and_resilient(self):
        with tempfile.TemporaryDirectory() as tmp:
            s_a = build_distributed_os_mesh(project_name="projA", workspace_root=tmp)
            s_b = build_distributed_os_mesh(project_name="projB", workspace_root=tmp)
            file_a = Path(tmp) / ".turboquant_memory_projA.json"
            file_b = Path(tmp) / ".turboquant_memory_projB.json"
            self.assertTrue(file_a.exists() and file_b.exists())
            state_a = json.loads(file_a.read_text(encoding="utf-8"))
            self.assertEqual(state_a["project"], "projA")
            self.assertEqual(state_a["runs"], 1)
            # memória corrompida não derruba a malha
            file_a.write_text("{corrompido", encoding="utf-8")
            s_a2 = build_distributed_os_mesh(project_name="projA", workspace_root=tmp)
            self.assertIn("Tarefas concluídas: 7/7", s_a2)

    def test_growth_history_persisted_and_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            gestate_until_emergence(project_name="projG", workspace_root=tmp, interval_s=1, max_cycles=3)
            history = read_growth_history(project_name="projG", workspace_root=tmp)
            self.assertGreaterEqual(len(history["history"]), 3)
            self.assertEqual(history["stage"], history["history"][-1]["stage"])

    def test_fastapi_routes(self):
        client = TestClient(app_module.app)
        self.assertEqual(client.get("/health").status_code, 200)
        self.assertEqual(client.get("/").json()["status"], "ok")
        plan = client.get("/plan").json()
        self.assertIn("target", plan)
        run = client.post("/run-once", params={"project": "turboquant-test-api"}).json()
        self.assertEqual(run["cycle"], 1)
        self.assertTrue(run["signatures_valid"])
        growth = client.get("/growth", params={"project": "turboquant-test-api"}).json()
        self.assertIn(growth["stage"], VALID_STAGES)


if __name__ == "__main__":
    unittest.main()
