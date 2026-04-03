# maya

Malha autônoma TurboQuant com provisionamento por repositórios, segurança integrada, gestação monitorada e mapeamento automático dos ambientes de execução.

## Correção para deploy no Vercel

Este repositório agora inclui **entrypoint FastAPI** em `app.py` (variável `app`) e dependência em `requirements.txt`, corrigindo erro de build:

> "Nenhum ponto de entrada fastapi encontrado"

## Capacidades principais

- Orquestração completa por DAG (arquitetura, runtime, rede, segurança, observabilidade, QA, release).
- Supervisor autônomo por ciclos e gestação até emergência.
- Memória persistente com histórico de crescimento e ambientes.
- Assinatura de artefatos (HMAC-SHA256) e validação anti-injeção.
- Auto-mapeamento de ambiente sem terminal interativo (`EnvironmentMapper`).
- Planejamento automático de execução (`ExecutionPlanner`) para local/container/kubernetes.

## API FastAPI (deploy)

Rotas principais em `app.py`:
- `GET /`
- `GET /health`
- `GET /environments`
- `GET /plan`
- `POST /run-once`
- `POST /gestate`
- `GET /summary`

## CLI local

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
