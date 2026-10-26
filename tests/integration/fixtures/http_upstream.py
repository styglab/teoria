"""Echo fixture for the public routing contract; listens on API and Prefect ports."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import base64, hashlib, json


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self.respond()

    def do_POST(self):
        self.respond()

    def log_message(self, *args):
        pass

    def respond(self):
        if self.headers.get("Upgrade", "").lower() == "websocket":
            accept = base64.b64encode(
                hashlib.sha1(
                    (
                        self.headers["Sec-WebSocket-Key"]
                        + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                    ).encode()
                ).digest()
            ).decode()
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.send_header("X-Test-Upstream-Path", self.path)
            self.end_headers()
            self.close_connection = True
            return
        size = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(size).decode() if size else ""
        data = json.dumps(
            {
                "path": self.path,
                "method": self.command,
                "headers": dict(self.headers),
                "body": body,
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    for port in (8000, 8001, 4200):
        Thread(
            target=ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever,
            daemon=True,
        ).start()
    import time

    time.sleep(3600)


if __name__ == "__main__":
    main()
