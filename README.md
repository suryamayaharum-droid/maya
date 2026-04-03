# maya

Malha autônoma TurboQuant com provisionamento por repositórios, segurança integrada, gestação monitorada e **mapeamento automático dos ambientes de execução**.

## Capacidades principais

- Orquestração completa por DAG (arquitetura, runtime, rede, segurança, observabilidade, QA, release).
- Supervisor autônomo por ciclos e gestação até emergência.
- Memória persistente com histórico de crescimento e ambientes.
- Assinatura de artefatos (HMAC-SHA256) e validação anti-injeção.
- Auto-mapeamento de ambiente sem terminal interativo (`EnvironmentMapper`).
- Planejamento automático de execução (`ExecutionPlanner`) para local/container/kubernetes.

## Comandos

### 1) Execução única

```bash
python3 distributed_os_agent_mesh.py
```

### 2) Mapear ambientes e plano automático

```bash
python3 distributed_os_agent_mesh.py --map-env
```

### 3) Gestação monitorada até emergência

```bash
python3 distributed_os_agent_mesh.py --gestate --interval 1 --cycles 8
```

### 4) API local autônoma

```bash
python3 distributed_os_agent_mesh.py --serve --autonomous --interval 30 --cycles 0 --stop-on-emergence
```

## Endpoints locais

- `http://127.0.0.1:8787`
- `http://127.0.0.1:8787/health`
- `http://127.0.0.1:8787/growth`
- `http://127.0.0.1:8787/environments`
- `http://127.0.0.1:8787/plan`
