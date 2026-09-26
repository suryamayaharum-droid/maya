# maya

Malha autônoma TurboQuant com provisionamento por repositórios, segurança integrada (assinatura HMAC verificável), gestação monitorada e mapeamento automático dos ambientes de execução.

## Componentes

- `distributed_os_agent_mesh.py` — núcleo da malha: orquestrador DAG de agentes, memória persistente por projeto, guardião de segurança (blocklist + HMAC-SHA256), mapeador de ambientes e supervisor autônomo com estágios de crescimento (`concepcao → gestacao → formacao → validacao → emergencia`). Também expõe um servidor HTTP local standalone.
- `app.py` (+ aliases `main.py`, `asgi.py`, `api/index.py`) — API FastAPI para deploy (ex.: Vercel).
- `nova23compania.ipynb` — caderno de pesquisa/planejamento do app "Misa Amane Virtual Girlfriend" (histórico; não integra o runtime da malha).

## Como rodar

```bash
pip install -r requirements.txt

# CLI local
python3 distributed_os_agent_mesh.py --map-env
python3 distributed_os_agent_mesh.py --gestate --interval 1 --cycles 8
python3 distributed_os_agent_mesh.py --serve --autonomous --interval 30 --cycles 0 --stop-on-emergence

# API FastAPI local
uvicorn app:app --reload
```

## API FastAPI (deploy)

Rotas:
- `GET /` — metadados do serviço
- `GET /health` — status + alvo de execução detectado
- `GET /environments` — mapa do ambiente de execução
- `GET /plan` — plano de execução autônomo
- `GET /growth?project=...` — histórico de crescimento persistido (sem executar ciclo)
- `POST /run-once?project=...` — executa um ciclo da malha (retorna `signatures_valid`)
- `POST /gestate?project=...&interval=1&cycles=5` — gestação monitorada até emergência
- `GET /summary?project=...` — resumo textual da malha

## Deploy na Vercel

`vercel.json` roteia todas as requisições para `api/index.py`, que importa `app` de `app.py`. Múltiplos entrypoints (`app.py`, `main.py`, `asgi.py`) eliminam o erro "nenhum ponto de entrada fastapi encontrado".

## Testes

```bash
python -m unittest discover -v
```

Cobrem: conclusão da DAG (7/7 tarefas), assinatura e **verificação** HMAC de artefatos (incluindo detecção de adulteração), isolamento da memória por projeto, tolerância a memória corrompida, persistência/leitura do histórico de crescimento e todas as rotas da API. CI automatizada em `.github/workflows/ci.yml` (Python 3.10–3.12).

## Correções e melhorias recentes

- **Memória persistente**: arquivo agora é criado dentro de `workspace_root` (antes dependia do CWD do processo) e é isolado por projeto (`.turboquant_memory_<projeto>.json`) — antes projetos diferentes sobrescreviam a mesma memória.
- **Robustez**: leitura tolerante a JSON corrompido, escrita atômica (temp + `os.replace`), supervisor autônomo sobrevive a falhas em ciclos individuais.
- **Segurança**: verificação de assinatura HMAC (timing-safe) exposta via `verify_artifact_signatures` e sinalizada nas respostas `/run-once` e `/gestate`.
- **HTTP server local**: `ThreadingHTTPServer` (não bloqueia durante ciclos autônomos), 404 explícito para rotas desconhecidas e caminhos com query string normalizados.
- **Dependências**: `uvicorn` adicionado a `requirements.txt`/`pyproject.toml` para viabilizar `uvicorn app:app`.
