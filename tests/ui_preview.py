"""本地预览插件 WebUI 的小服务器（仅测试用，不随插件加载）。"""

from __future__ import annotations

import http.server
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOCK_BRIDGE = Path(__file__).with_name("mock_bridge.js")
PORT = 8765


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] == "/api/plugin/page/bridge-sdk.js":
            body = MOCK_BRIDGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, fmt: str, *args) -> None:
        print(f"[ui-preview] {fmt % args}")


if __name__ == "__main__":
    with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler) as server:
        print(f"http://127.0.0.1:{PORT}/pages/settings/index.html")
        server.serve_forever()
