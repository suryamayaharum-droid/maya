"""Servidor OpenBot com interface web e integração com Ollama."""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HOST = "0.0.0.0"
PORT = int(os.getenv("OPENBOT_PORT", "8000"))
INDEX_FILE = "openbot_interface.html"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.getenv("OPENBOT_MODEL", "llama3.2:1b")


class OpenBotHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (API da stdlib)
        if self.path in {"/", "/index.html"}:
            self.path = f"/{INDEX_FILE}"
            return super().do_GET()

        if self.path == "/api/health":
            self._send_json(HTTPStatus.OK, {"ok": True, "service": "openbot"})
            return

        if self.path == "/api/ollama/status":
            self._handle_ollama_status()
            return

        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 (API da stdlib)
        if self.path != "/api/chat":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Rota não encontrada."})
            return

        try:
            body = self._read_json_body()
        except ValueError as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return

        message = str(body.get("message", "")).strip()
        model = str(body.get("model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL

        if not message:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Mensagem vazia."})
            return

        try:
            answer = chat_with_ollama(message=message, model=model)
        except RuntimeError as error:
            self._send_json(HTTPStatus.BAD_GATEWAY, {"error": str(error)})
            return

        self._send_json(HTTPStatus.OK, {"response": answer, "model": model})

    def _read_json_body(self) -> dict:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            content_length = int(raw_length)
        except ValueError as error:
            raise ValueError("Cabeçalho Content-Length inválido.") from error

        raw_data = self.rfile.read(content_length)
        try:
            parsed = json.loads(raw_data.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError("JSON inválido no corpo da requisição.") from error

        if not isinstance(parsed, dict):
            raise ValueError("O corpo JSON precisa ser um objeto.")

        return parsed

    def _handle_ollama_status(self) -> None:
        try:
            tags = fetch_ollama_tags()
        except RuntimeError as error:
            self._send_json(
                HTTPStatus.BAD_GATEWAY,
                {"ok": False, "error": str(error), "defaultModel": DEFAULT_MODEL},
            )
            return

        available_models = [item.get("name", "") for item in tags if isinstance(item, dict)]
        self._send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "defaultModel": DEFAULT_MODEL,
                "models": [model for model in available_models if model],
            },
        )

    def _send_json(self, status: HTTPStatus, payload: dict) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _ollama_request(path: str, payload: dict | None = None) -> dict:
    data = None
    headers: dict[str, str] = {}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url=f"{OLLAMA_URL}{path}", data=data, headers=headers, method="POST" if data else "GET")

    try:
        with urlopen(request, timeout=90) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Ollama retornou erro HTTP {error.code}. {detail}".strip()) from error
    except URLError as error:
        raise RuntimeError(
            "Não foi possível conectar ao Ollama. Confirme se o serviço está ativo em "
            f"{OLLAMA_URL}."
        ) from error

    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError("Resposta inválida do Ollama (JSON malformado).") from error


def fetch_ollama_tags() -> list[dict]:
    response = _ollama_request("/api/tags")
    models = response.get("models", [])
    if not isinstance(models, list):
        raise RuntimeError("Resposta inesperada de /api/tags.")
    return models


def chat_with_ollama(message: str, model: str) -> str:
    response = _ollama_request(
        "/api/generate",
        {
            "model": model,
            "prompt": message,
            "stream": False,
        },
    )

    text = response.get("response")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("Ollama respondeu sem conteúdo de texto.")

    return text.strip()


def main() -> None:
    root = Path(__file__).resolve().parent
    handler = lambda *args, **kwargs: OpenBotHandler(*args, directory=str(root), **kwargs)
    server = ThreadingHTTPServer((HOST, PORT), handler)
    print(f"OpenBot disponível em http://localhost:{PORT}")
    print(f"Integração Ollama configurada em {OLLAMA_URL} (modelo padrão: {DEFAULT_MODEL})")
    server.serve_forever()


if __name__ == "__main__":
    main()
