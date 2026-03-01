# maya

OpenBot local com interface web conectada ao **Ollama**.

## 1) Instalar Ollama e modelo

```bash
bash setup_ollama.sh
```

> Opcional: escolher modelo

```bash
bash setup_ollama.sh mistral
```

## 2) Iniciar o OpenBot

```bash
python run_openbot.py
```

Acesse no navegador:

- http://localhost:8000

## Variáveis úteis

- `OPENBOT_PORT` (padrão `8000`)
- `OLLAMA_URL` (padrão `http://127.0.0.1:11434`)
- `OPENBOT_MODEL` (padrão `llama3.2:1b`)

## Arquivos

- `openbot_interface.html`: interface web de chat.
- `run_openbot.py`: servidor HTTP + API `/api/chat` integrada com Ollama.
- `setup_ollama.sh`: instalador/configurador do Ollama para uso com OpenBot.
