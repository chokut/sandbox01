#!/usr/bin/env python3
"""
コンテナ内 HTTP CONNECT プロキシ (ドメインソケット経由)

コンテナ内クライアントからの HTTP CONNECT リクエストを受け付け、
ドメインソケット経由でホスト側リレーへ転送し、クライアントと
リレー間を双方向に中継する（HTTPS トンネリング用）。

HTTP CONNECT メソッド専用のプロキシ。通常の順方向プロキシ
(http:// スキーム) は http_proxy_to_uds.py が担当する。

UDS 上のプロトコル (プロキシ -> リレー):
  [2バイト: host:port のバイト長 (ビッグエンディアン)]
  [Nバイト: host:port 文字列, 例 "example.com:443"]
  [以後: クライアントからの生バイトをそのまま中継]

環境変数:
  TUNNEL_SOCK : ドメインソケットのパス (デフォルト: /tmp/apptainer-tunnel.sock)
  LISTEN_HOST : 待ち受けホスト (デフォルト: 127.0.0.1)
  LISTEN_PORT : 待ち受けポート (デフォルト: 3129)
"""

import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UNIX_SOCK = os.environ.get("TUNNEL_SOCK", "/tmp/apptainer-tunnel.sock")
LISTEN_HOST = os.environ.get("LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "3128"))


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


class ConnectProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # アクセスログ抑制
        return

    def _send_error_raw(self, code, message):
        body = f"{code} {message}\r\n".encode("utf-8")
        try:
            self.wfile.write(f"HTTP/1.1 {code} {message}\r\n".encode("latin-1"))
            self.wfile.write(b"Content-Type: text/plain\r\n")
            self.wfile.write(b"Connection: close\r\n")
            self.wfile.write(f"Content-Length: {len(body)}\r\n".encode("latin-1"))
            self.wfile.write(b"\r\n")
            self.wfile.write(body)
        except (OSError, ConnectionError):
            pass

    def do_CONNECT(self):
        """CONNECT メソッド: ホスト:ポートへのトンネルを確立する"""
        # リクエストターゲットは "host:port"
        target = self.path.strip()
        if not target:
            self._send_error_raw(400, "Bad Request")
            return

        # IPv6 [::1]:443 形式を許容。host:port に分解して検証
        if target.startswith("["):
            try:
                rbracket = target.index("]")
                host = target[1:rbracket]
                port_str = target[rbracket + 2:]  # "]:" をスキップ
                port = int(port_str)
            except (ValueError, IndexError):
                self._send_error_raw(400, "Bad Request")
                return
        else:
            parts = target.rsplit(":", 1)
            if len(parts) != 2:
                self._send_error_raw(400, "Bad Request")
                return
            host, port_str = parts
            try:
                port = int(port_str)
            except ValueError:
                self._send_error_raw(400, "Bad Request")
                return

        try:
            up = upstream_conn(target)
        except (OSError, ConnectionError) as exc:
            self._send_error_raw(502, f"Bad Gateway: {exc}")
            return

        # リレー接続成功: 200 Connection Established を返す
        try:
            self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n")
            self.wfile.write(b"Connection: close\r\n")
            self.wfile.write(b"\r\n")
        except (OSError, ConnectionError):
            try:
                up.close()
            except OSError:
                pass
            return

        # クライアント <-> リレー を双方向中継 (HTTPS トンネル)
        stop = threading.Event()
        t1 = threading.Thread(target=pipe, args=(self.connection, up, stop), daemon=True)
        t2 = threading.Thread(target=pipe, args=(up, self.connection, stop), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        self.close_connection = True


def main():
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), ConnectProxyHandler)
    print(f"[connect proxy] listening on {LISTEN_HOST}:{LISTEN_PORT} -> {UNIX_SOCK}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
