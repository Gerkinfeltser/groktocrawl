"""Threaded acquisition twin for exercising the real gateway topology."""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

slots = threading.BoundedSemaphore(4)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.respond({"status": "ok"})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        with slots:
            time.sleep(0.1)
            self.respond({"success": True, "backend": socket.gethostname()})

    def respond(self, body):
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8001), Handler).serve_forever()
