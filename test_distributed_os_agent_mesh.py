import unittest

from distributed_os_agent_mesh import (
    AutonomousSupervisor,
    MeshOrchestrator,
    build_distributed_os_mesh,
    gestate_until_emergence,
    map_execution_environments,
)


VALID_STAGES = {"concepcao", "gestacao", "formacao", "validacao", "emergencia"}


class MeshTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
