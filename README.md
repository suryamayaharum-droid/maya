# maya

Malha autônoma TurboQuant com provisionamento por repositórios, segurança integrada, gestação monitorada e mapeamento automático dos ambientes de execução.

## Correção robusta para deploy no Vercel

Para eliminar definitivamente o erro:

> "Nenhum ponto de entrada fastapi encontrado"

foram adicionados **múltiplos entrypoints compatíveis**:

- `app.py` (principal)
- `main.py` (alias)
- `asgi.py` (alias)
- `api/index.py` (entrypoint padrão para funções Vercel)
- `pyproject.toml` com script `app = "app:app"`
- `vercel.json` roteando tudo para `api/index.py`

## API FastAPI (deploy)

Rotas principais:
- `GET /`
- `GET /health`
- `GET /environments`
- `GET /plan`
- `POST /run-once`
- `POST /gestate`
- `GET /summary`

## CLI local

```bash
python3 distributed_os_agent_mesh.py --map-env
python3 distributed_os_agent_mesh.py --gestate --interval 1 --cycles 8
python3 distributed_os_agent_mesh.py --serve --autonomous --interval 30 --cycles 0 --stop-on-emergence
```
