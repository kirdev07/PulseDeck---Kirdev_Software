"""A local stand-in for GitHub Releases to test the PC auto-update end to end.

    .venv\\Scripts\\python tools\\dev\\fake_release.py <folder with Setup.exe> <port> [version]

Serves /latest (GitHub API shape) and the installer. Start PulseDeck with
PULSEDECK_UPDATE_URL=http://127.0.0.1:<port>/latest. See CLAUDE.md → «Проверка автообновления».
"""
import http.server
import json
import os
import sys
from functools import partial

folder, port = sys.argv[1], int(sys.argv[2])
version = sys.argv[3] if len(sys.argv) > 3 else "1.0.1"
setup = f"PulseDeck-{version}-Setup.exe"
size = os.path.getsize(os.path.join(folder, setup))
latest = json.dumps({
    "tag_name": f"v{version}", "draft": False, "prerelease": False,
    "body": "## Что нового\n- **Тест автообновления** с локального сервера",
    "assets": [{"name": setup, "size": size, "browser_download_url": f"http://127.0.0.1:{port}/{setup}"}],
}).encode()


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/latest":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(latest)))
            self.end_headers()
            self.wfile.write(latest)
            return
        super().do_GET()


http.server.ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=folder)).serve_forever()
