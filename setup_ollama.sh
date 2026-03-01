#!/usr/bin/env bash
set -euo pipefail

MODEL="${1:-llama3.2:1b}"

if ! command -v ollama >/dev/null 2>&1; then
  echo "[OpenBot] Instalando Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
else
  echo "[OpenBot] Ollama já está instalado."
fi

if pgrep -f "ollama serve" >/dev/null 2>&1; then
  echo "[OpenBot] Ollama já está rodando."
else
  echo "[OpenBot] Iniciando 'ollama serve' em background..."
  nohup ollama serve >/tmp/ollama.log 2>&1 &
  sleep 2
fi

echo "[OpenBot] Baixando modelo ${MODEL} (se necessário)..."
ollama pull "${MODEL}"

echo "[OpenBot] Concluído."
echo "- Ollama API: http://127.0.0.1:11434"
echo "- Inicie o OpenBot: python run_openbot.py"
