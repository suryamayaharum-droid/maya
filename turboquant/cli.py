"""CLI da malha: python3 -m turboquant.cli [opções]."""

from __future__ import annotations

import argparse
import json

from turboquant.mesh import (
    build_distributed_os_mesh,
    gestate_until_emergence,
    map_execution_environments,
    serve_mesh,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Malha autonoma TurboQuant (CPU-first)")
    parser.add_argument("--project", default="turboquant", help="Nome do projeto")
    parser.add_argument("--workspace", default=".", help="Raiz para descoberta de repositorios")
    parser.add_argument("--serve", action="store_true", help="Inicia API HTTP local")
    parser.add_argument("--autonomous", action="store_true", help="Executa ciclos autonomos continuos")
    parser.add_argument("--gestate", action="store_true", help="Gestacao monitorada ate emergencia")
    parser.add_argument("--map-env", action="store_true", help="Mapeia ambientes e plano autonomo")
    parser.add_argument("--interval", type=int, default=60, help="Intervalo dos ciclos (segundos)")
    parser.add_argument("--cycles", type=int, default=0, help="Maximo de ciclos (0 = infinito)")
    parser.add_argument("--stop-on-emergence", action="store_true", help="Para ao atingir emergencia")
    parser.add_argument("--host", default="127.0.0.1", help="Host do servidor")
    parser.add_argument("--port", type=int, default=8787, help="Porta do servidor")
    return parser.parse_args()


def main() -> None:
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


if __name__ == "__main__":
    main()
