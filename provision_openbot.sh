#!/usr/bin/env bash
set -euo pipefail

MODEL="${1:-llama3.2:1b}"
OPENBOT_PORT="${OPENBOT_PORT:-8000}"
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="${ROOT_DIR}/.runtime"
mkdir -p "${RUNTIME_DIR}"

log() { echo "[OpenBot-Provision] $*"; }


install_system_deps() {
  if command -v zstd >/dev/null 2>&1; then
    return
  fi

  if command -v apt-get >/dev/null 2>&1; then
    log "Instalando dependência zstd..."
    apt-get update -y
    apt-get install -y zstd
  else
    log "zstd é obrigatório para instalar Ollama. Instale zstd manualmente e rode novamente."
    exit 1
  fi
}

install_ollama_if_needed() {
  if command -v ollama >/dev/null 2>&1; then
    log "Ollama já instalado."
    return
  fi

  log "Instalando Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
}

ensure_ollama_running() {
  if curl -fsS "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
    log "Ollama já está respondendo em ${OLLAMA_URL}."
    return
  fi

  log "Iniciando ollama serve em background..."
  setsid -f ollama serve >"${RUNTIME_DIR}/ollama.log" 2>&1 < /dev/null
  sleep 1
  pgrep -f "ollama serve" | head -n1 >"${RUNTIME_DIR}/ollama.pid"

  for _ in $(seq 1 30); do
    if curl -fsS "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
      log "Ollama iniciou com sucesso."
      return
    fi
    sleep 1
  done

  log "Falha ao iniciar Ollama. Verifique ${RUNTIME_DIR}/ollama.log"
  exit 1
}

pull_model() {
  log "Garantindo modelo ${MODEL}..."
  ollama pull "${MODEL}"
}

start_openbot() {
  if curl -fsS "http://127.0.0.1:${OPENBOT_PORT}/api/health" >/dev/null 2>&1; then
    log "OpenBot já está rodando na porta ${OPENBOT_PORT}."
    return
  fi

  log "Iniciando OpenBot na porta ${OPENBOT_PORT}..."
  OPENBOT_MODEL="${MODEL}" OPENBOT_PORT="${OPENBOT_PORT}" OLLAMA_URL="${OLLAMA_URL}" \
    setsid -f python3 "${ROOT_DIR}/run_openbot.py" >"${RUNTIME_DIR}/openbot.log" 2>&1 < /dev/null
  sleep 1
  pgrep -f "run_openbot.py" | head -n1 >"${RUNTIME_DIR}/openbot.pid"

  for _ in $(seq 1 20); do
    if curl -fsS "http://127.0.0.1:${OPENBOT_PORT}/api/health" >/dev/null 2>&1; then
      log "OpenBot iniciou com sucesso."
      return
    fi
    sleep 1
  done

  log "Falha ao iniciar OpenBot. Verifique ${RUNTIME_DIR}/openbot.log"
  exit 1
}

validate_chat() {
  log "Validando endpoint de chat..."
  response="$(curl -fsS -X POST "http://127.0.0.1:${OPENBOT_PORT}/api/chat" \
    -H 'Content-Type: application/json' \
    -d "{\"message\":\"Responda apenas OK\",\"model\":\"${MODEL}\"}")"

  if [[ "${response}" == *"response"* ]]; then
    log "Chat validado com sucesso."
    return
  fi

  log "Resposta inesperada do chat: ${response}"
  exit 1
}

print_summary() {
  cat <<EOF

✅ Provisionamento concluído.
- Provedor: Ollama (${OLLAMA_URL})
- Modelo: ${MODEL}
- OpenBot: http://127.0.0.1:${OPENBOT_PORT}
- Health: http://127.0.0.1:${OPENBOT_PORT}/api/health
- Runtime logs: ${RUNTIME_DIR}

Para parar processos iniciados por este script:
  kill "$(cat "${RUNTIME_DIR}/openbot.pid")" "$(cat "${RUNTIME_DIR}/ollama.pid")"
EOF
}

install_system_deps
install_ollama_if_needed
ensure_ollama_running
pull_model
start_openbot
validate_chat
print_summary
