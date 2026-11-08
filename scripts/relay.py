#!/usr/bin/env python3
"""
ホスト側リレー: ドメインソケット → 直接 TCP ターゲット

コンテナ内プロキシから UDS 経由で受け取った接続について、
2 バイト長 + host:port のプレフィックスを読み取り、
そのターゲットに直接 TCP 接続する（HTTP_PROXY などの上位プロキシは経由しない）。

プロトコル (UDS 上, プロキシ → リレー):
  [2バイト: host:port のバイト長 (ビッグエンディアン)]
  [Nバイト: host:port 文字列, 例 "example.com:443"]
  [以後: クライアントからの生バイトをそのまま中継]

使い方:
  python3 relay.py /tmp/apptainer-tunnel-12345.sock
"""

import os
import socket
import sys
import threading


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


def read_exact(conn, n):
    """conn からちょうど n バイト読む"""
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def handle_client(conn):
    """1つの UDS 接続を処理: プレフィックス読み → 直接TCP接続 → パイプ"""
    try:
        # 2 バイト長プレフィックスを読む
        len_buf = read_exact(conn, 2)
        if len_buf is None:
            return
        target_len = int.from_bytes(len_buf, "big")

        # host:port を読む
        target_buf = read_exact(conn, target_len)
        if target_buf is None:
            return
        target = target_buf.decode("ascii")

        # host:port を分解 (IPv6 アドレス [::1]:443 にも対応)
        if target.startswith("["):
            # [IPv6]:port
            rbracket = target.index("]")
            host = target[1:rbracket]
            port_str = target[rbracket + 2:]  # "]:" をスキップ
        else:
            host, port_str = target.rsplit(":", 1)
        port = int(port_str)

        # 直接 TCP ターゲットに接続 (上位プロキシを経由しない)
        upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        upstream.connect((host, port))

        stop = threading.Event()
        t1 = threading.Thread(target=pipe, args=(conn, upstream, stop), daemon=True)
        t2 = threading.Thread(target=pipe, args=(upstream, conn, stop), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    except Exception as exc:  # noqa: BLE001
        print(f"[relay] error handling client: {exc}", file=sys.stderr)
    finally:
        try:
            conn.close()
        except OSError:
            pass


def main():
    sock_file = sys.argv[1] if len(sys.argv) > 1 else "/tmp/apptainer-tunnel.sock"

    if os.path.exists(sock_file):
        os.unlink(sock_file)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_file)
    server.listen(16)
    print(f"[relay] listening on {sock_file} (direct TCP, no upstream proxy)", flush=True)

    try:
        while True:
            conn, _ = server.accept()
            threading.Thread(target=handle_client, args=(conn,), daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        try:
            os.unlink(sock_file)
        except OSError:
            pass


if __name__ == "__main__":
    main()
