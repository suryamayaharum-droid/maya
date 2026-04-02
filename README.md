# maya

Malha completa de agentes autônomos para o **TurboQuant**, com provisionamento por repositórios, segurança integrada, operação contínua e **gestação monitorada até emergência**.

## O que foi concluído

- Orquestração completa por DAG (arquitetura, runtime, rede, segurança, observabilidade, QA, release).
- Provisionamento da IA a partir dos repositórios locais (bootstrap de conhecimento).
- Memória persistente de projeto (`.turboquant_memory.json`) com relatórios por execução.
- Assinatura de artefatos com HMAC-SHA256 e validação anti-injeção.
- Endpoint HTTP local para acesso direto ao estado da malha.
- Supervisor autônomo por ciclos com intervalo configurável.
- **Gestação monitorada** com estágios (`concepcao`, `gestacao`, `formacao`, `validacao`, `emergencia`).

## Como rodar (execução única)

```bash
python3 distributed_os_agent_mesh.py
```

## Iniciar gestação monitorada até emergência

```bash
python3 distributed_os_agent_mesh.py --gestate --interval 1 --cycles 8
```

## Como rodar com link de acesso (API local)

```bash
python3 distributed_os_agent_mesh.py --serve --host 127.0.0.1 --port 8787
```

## Como rodar em modo autônomo contínuo

```bash
python3 distributed_os_agent_mesh.py --serve --autonomous --interval 30 --cycles 0 --stop-on-emergence
```

## Links locais

- `http://127.0.0.1:8787`
- `http://127.0.0.1:8787/health`
- `http://127.0.0.1:8787/growth`

## Exemplo de resposta do endpoint `/growth`

```json
{
  "cycle": 4,
  "stage": "validacao",
  "history": [
    {"cycle": 1, "stage": "concepcao", "fitness": 0.82},
    {"cycle": 2, "stage": "gestacao", "fitness": 0.86}
  ]
}
```
