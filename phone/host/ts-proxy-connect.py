#!/usr/bin/env python3
import os, sys, socket, select, base64, urllib.parse

def send_all(sock, data):
    view = memoryview(data)
    while len(view):
        try:
            n = sock.send(view)
            view = view[n:]
        except BlockingIOError:
            select.select([], [sock], [], 5)
        except InterruptedError:
            continue

def main():
    host, port = sys.argv[1], int(sys.argv[2])
    proxy = urllib.parse.urlparse(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or "")
    s = socket.create_connection((proxy.hostname, 3130))
    req = "CONNECT %s:%d HTTP/1.1\r\nHost: %s:%d\r\n" % (host, port, host, port)
    if proxy.username:
        creds = "%s:%s" % (urllib.parse.unquote(proxy.username), urllib.parse.unquote(proxy.password or ""))
        req += "Proxy-Authorization: Basic " + base64.b64encode(creds.encode()).decode() + "\r\n"
    req += "\r\n"
    s.sendall(req.encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            sys.exit(1)
        buf += chunk
    head, rest = buf.split(b"\r\n\r\n", 1)
    if b" 200 " not in head.split(b"\r\n")[0]:
        sys.stderr.write(head.decode(errors="replace"))
        sys.exit(1)
    s.setblocking(False)
    out = sys.stdout.buffer
    if rest:
        out.write(rest); out.flush()
    fdin = sys.stdin.buffer
    while True:
        r, _, _ = select.select([s, fdin], [], [], 60)
        if not r:
            continue
        if s in r:
            try:
                data = s.recv(65536)
            except BlockingIOError:
                data = b""
            if not data:
                break
            out.write(data); out.flush()
        if fdin in r:
            data = os.read(0, 65536)
            if not data:
                try: s.shutdown(socket.SHUT_WR)
                except OSError: pass
                break
            send_all(s, data)

main()
