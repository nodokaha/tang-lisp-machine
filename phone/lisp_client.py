import os, select, socket, termios, time, tty

HOST, PORT = "127.0.0.1", 18777

s = socket.create_connection((HOST, PORT))
os.write(1, b"[TangLisp] connected. Ctrl-C or Ctrl-D to leave (board keeps its state)\n")
old = None
if os.isatty(0):
    old = termios.tcgetattr(0)
    tty.setraw(0)
eof = False
quiet_deadline = None
try:
    while True:
        fds = [s] if eof else [0, s]
        r, _, _ = select.select(fds, [], [], 0.05)
        if 0 in r:
            b = os.read(0, 256)
            if not b:
                eof = True
                quiet_deadline = time.time() + 5.0
            elif old is not None and b in (b"\x03", b"\x04"):
                break
            else:
                s.sendall(b)
        if s in r:
            data = s.recv(4096)
            if not data:
                os.write(1, b"\r\n[server closed]\r\n")
                break
            if old is not None:
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            os.write(1, data)
            if eof:
                quiet_deadline = time.time() + 4.0
        if eof and quiet_deadline is not None and time.time() > quiet_deadline:
            break
finally:
    if old is not None:
        termios.tcsetattr(0, termios.TCSADRAIN, old)
    try:
        s.close()
    except Exception:
        pass
    os.write(1, b"\n[disconnected]\n")
