# maya

Malha de agentes de IA autônomos para construir um **sistema operacional distribuído**.

## O que este projeto entrega

O arquivo `distributed_os_agent_mesh.py` cria uma malha com agentes especializados em:

- Arquitetura
- Kernel
- Rede/Consenso
- Segurança
- Observabilidade
- QA/Resiliência
- Release/Operação

A orquestração usa um grafo de dependências entre tarefas, memória compartilhada para artefatos e síntese final do plano de construção.

## Como executar

```bash
python3 distributed_os_agent_mesh.py
```

## Exemplo de uso via API

```python
from distributed_os_agent_mesh import build_distributed_os_mesh

resumo = build_distributed_os_mesh()
print(resumo)
```
