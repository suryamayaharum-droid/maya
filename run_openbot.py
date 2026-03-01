"""Servidor local simples para abrir a interface do OpenBot."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "0.0.0.0"
PORT = 8000
INDEX_FILE = "openbot_interface.html"


class OpenBotHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in {"/", "/index.html"}:
            self.path = f"/{INDEX_FILE}"
        return super().do_GET()


def main() -> None:
    root = Path(__file__).resolve().parent
    handler = lambda *args, **kwargs: OpenBotHandler(*args, directory=str(root), **kwargs)
    server = ThreadingHTTPServer((HOST, PORT), handler)
    print(f"OpenBot interface disponível em http://localhost:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
