#!/usr/bin/env python3
"""
コンテナ内 HTTP プロキシ (ドメインソケット経由)

コンテナ内クライアントからの通常の HTTP リクエストを受け付け、
ドメインソケット経由でホスト側リレーへ転送し、リレーからのレスポンスを
クライアントへ中継する。

HTTP CONNECT メソッドは使わない。通常の順方向プロキシとして動作し、
http:// スキームのリクエストをターゲットへ転送する。

UDS 上のプロトコル (プロキシ -> リレー):
  [2バイト: host:port のバイト長 (ビッグエンディアン)]
  [Nバイト: host:port 文字列, 例 "example.com:80"]
  [以後: クライアントからの生 HTTP リクエストをそのまま中継]

環境変数:
  TUNNEL_SOCK : ドメインソケットのパス (デフォルト: /tmp/apptainer-tunnel.sock)
"""

import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

UNIX_SOCK = os.environ.get("TUNNEL_SOCK", "/tmp/apptainer-tunnel.sock")
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 3128


def upstream_conn(target):
    """ドメインソケットへ接続し、ターゲット(prefixed)をリレーに通知する"""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(UNIX_SOCK)
    # ターゲットをプレフィックス付きで送信: [2バイト長][host:port]
    target_bytes = target.encode("ascii")
    prefix = len(target_bytes).to_bytes(2, "big") + target_bytes
    s.sendall(prefix)
    return s


def pipe(src, dst, stop):
    """src -> dst へ単方向中継"""
    try:
        while not stop.is_set():
            try:
                data = src.recv(65536)
            except (OSError, ConnectionError):
                break
            if not data:
                break
            try:
                dst.sendall(data)
            except (OSError, ConnectionError):
                break
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, format, *args):
        # アクセスログ抑制
        return

    def _target_from_uri(self):
        """リクエストURIからターゲット host:port と転送用パスを解決する"""
        parsed = urlparse(self.path)
        scheme = (parsed.scheme or "http").lower()
        host = parsed.hostname
        if not host:
            return None, None
        port = parsed.port or (443 if scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        return f"{host}:{port}", path

    def _send_error_raw(self, code, message):
        body = f"{code} {message}\r\n".encode("utf-8")
        try:
            self.wfile.write(f"HTTP/1.0 {code} {message}\r\n".encode("latin-1"))
            self.wfile.write(b"Content-Type: text/plain\r\n")
            self.wfile.write(b"Connection: close\r\n")
            self.wfile.write(f"Content-Length: {len(body)}\r\n".encode("latin-1"))
            self.wfile.write(b"\r\n")
            self.wfile.write(body)
        except (OSError, ConnectionError):
            pass

    def handle_proxy(self):
        """順方向プロキシ: リクエストをリレー経由でターゲットへ転送しレスポンスを中継"""
        # 常に 1 リクエストごとに接続を閉じる (Connection: close を返すため)
        self.close_connection = True
        target, path = self._target_from_uri()
        if not target:
            self._send_error_raw(400, "Bad Request")
            return

        try:
            up = upstream_conn(target)
        except (OSError, ConnectionError) as exc:
            self._send_error_raw(502, f"Bad Gateway: {exc}")
            return

        # クライアントからの HTTP リクエストを転送用に再構築 (絶対URI -> 原始URI)
        request_line = f"{self.command} {path} {self.request_version}\r\n"
        headers = []
        for key, value in self.headers.items():
            kl = key.lower()
            if kl == "host":
                headers.append(f"Host: {target}\r\n")
            elif kl in ("connection", "proxy-connection", "keep-alive"):
                headers.append(f"{key}: close\r\n")
            elif kl == "transfer-encoding":
                # ボディは Content-Length ベースで転送するため除外
                continue
            else:
                headers.append(f"{key}: {value}\r\n")
        headers.append("Connection: close\r\n")
        headers.append("\r\n")

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b""

        request_bytes = request_line.encode("latin-1")
        request_bytes += "".join(headers).encode("latin-1")
        request_bytes += body

        try:
            up.sendall(request_bytes)
        except (OSError, ConnectionError) as exc:
            try:
                up.close()
            except OSError:
                pass
            self._send_error_raw(502, f"Bad Gateway: {exc}")
            return

        # リレー(ターゲット)からのレスポンスをそのままクライアントへ中継
        try:
            pipe(up, self.connection, threading.Event())
        except (OSError, ConnectionError):
            pass

    def do_GET(self):
        self.handle_proxy()

    def do_POST(self):
        self.handle_proxy()

    def do_PUT(self):
        self.handle_proxy()

    def do_DELETE(self):
        self.handle_proxy()

    def do_HEAD(self):
        self.handle_proxy()

    def do_OPTIONS(self):
        self.handle_proxy()

    def do_PATCH(self):
        self.handle_proxy()


def main():
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), ProxyHandler)
    print(f"[proxy] listening on {LISTEN_HOST}:{LISTEN_PORT} -> {UNIX_SOCK}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
