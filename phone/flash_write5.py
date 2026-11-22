import ctypes, sys, os
os.environ["PYOCD_USB_BACKEND"] = "pyusb"
fd = int(sys.argv[1])
LIBUSB = "/data/data/com.termux/files/usr/lib/libusb-1.0.so"
lib = ctypes.CDLL(LIBUSB)
lib.libusb_set_option(None, 2)
ctx = ctypes.c_void_p()
assert lib.libusb_init(ctypes.byref(ctx)) == 0
lib.libusb_wrap_sys_device.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p)]
handle = ctypes.c_void_p()
assert lib.libusb_wrap_sys_device(ctx, fd, ctypes.byref(handle)) == 0
lib.libusb_get_device.argtypes = [ctypes.c_void_p]
lib.libusb_get_device.restype = ctypes.c_void_p
dev_ptr = lib.libusb_get_device(handle)
lib.libusb_set_configuration.argtypes = [ctypes.c_void_p, ctypes.c_int]
print("set_configuration rc:", lib.libusb_set_configuration(handle, 1), flush=True)
print("wrapped device ptr:", hex(dev_ptr), flush=True)

import usb.backend.libusb1 as libusb1
backend = libusb1.get_backend(find_library=lambda x: LIBUSB)
backend.ctx = ctypes.cast(ctx, type(backend.ctx))
libusb1.get_backend = lambda *a, **k: backend

import usb.core
devs = list(usb.core.find(find_all=True))
print("pyusb sees:", [(hex(d.idVendor), hex(d.idProduct)) for d in devs], flush=True)
if not devs:
    orig_enum = backend.enumerate_devices
    def enum_patch():
        try:
            lst = list(orig_enum())
            if lst:
                return lst
        except Exception as e:
            print("enum error:", e, flush=True)
        return [libusb1._Device(ctypes.c_void_p(dev_ptr))]
    backend.enumerate_devices = enum_patch
    devs = list(usb.core.find(find_all=True))
    print("pyusb sees after enum patch:", [(hex(d.idVendor), hex(d.idProduct)) for d in devs], flush=True)


lib.libusb_get_string_descriptor_ascii.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.c_char_p, ctypes.c_int]
import usb.util
_orig_gs = usb.util.get_string
def _gs(dev, index, langid=None):
    try:
        s = _orig_gs(dev, index) if langid is None else _orig_gs(dev, index, langid)
        if s:
            return s
    except Exception:
        pass
    buf = ctypes.create_string_buffer(256)
    rc = lib.libusb_get_string_descriptor_ascii(handle, index, buf, 256)
    return buf.value.decode(errors="replace") if rc >= 0 else None
usb.util.get_string = _gs


# Patch pyusb handle creation: libusb_open cannot work on Android (no direct
# /dev/bus/usb access); wrap the termux-usb fd instead.
def _patched_handle_init(self, dev):
    self.devid = dev.devid
    self.handle = libusb1._libusb_device_handle()
    rc = lib.libusb_wrap_sys_device(ctx, fd, ctypes.byref(self.handle))
    if rc != 0:
        raise Exception("wrap_sys_device failed rc=%d" % rc)
libusb1._DeviceHandle.__init__ = _patched_handle_init

import sys
import time
import usb.core
import usb.util

TERM = bytes([0xFA, 0xAA])

NOOP = 0x02
ERASE_SRAM = 0x05
XFER_DONE = 0x09
READ_IDCODE = 0x11
INIT_ADDR = 0x12
READ_USERCODE = 0x13
CONFIG_ENABLE = 0x15
XFER_WRITE = 0x17
CONFIG_DISABLE = 0x3A
STATUS_REGISTER = 0x41

BIT_CRC_ERROR = 1 << 0
BIT_BAD_COMMAND = 1 << 1
BIT_TIMEOUT = 1 << 3
BIT_AUTOBOOT2 = 1 << 4
BIT_MEMORY_ERASE = 1 << 5
BIT_EDIT_MODE = 1 << 7
BIT_DONE = 1 << 13

dev = usb.core.find(idVendor=0x0403, idProduct=0x6010)
try:
    if dev.is_kernel_driver_active(0):
        dev.detach_kernel_driver(0)
        print("detached", flush=True)
except Exception as e:
    print("detach note:", e, flush=True)
usb.util.claim_interface(dev, 0)
print("claimed", flush=True)
try:
    dev.reset()
    print("usb reset done", flush=True)
except Exception as e:
    print("usb reset note:", e, flush=True)
time.sleep(2.0)
try:
    dev.set_configuration()
except Exception:
    pass
try:
    if dev.is_kernel_driver_active(0):
        dev.detach_kernel_driver(0)
except Exception:
    pass
try:
    usb.util.claim_interface(dev, 0)
    print("claimed after reset", flush=True)
except Exception as e:
    print("claim after reset note:", e, flush=True)


def read_payload():
    pkts = []
    deadline = time.time() + 3.0
    while time.time() < deadline:
        try:
            d = bytes(dev.read(0x81, 512, timeout=300))
        except Exception:
            continue
        if len(d) > 2:
            pkts.append(d[2:])
            if b"".join(pkts).endswith(TERM):
                break
    return b"".join(pkts)


def drain_brief():
    try:
        while True:
            d = bytes(dev.read(0x81, 512, timeout=60))
            if len(d) <= 2:
                break
    except Exception:
        pass


class Jtag:
    def __init__(self, dev):
        self.dev = dev
        self.buf = bytearray()

    def cmd(self, *bs):
        self.buf += bytes(bs)

    def raw_write(self, data):
        self.dev.write(0x02, bytes(data))

    def tms_bits(self, bits):
        i = 0
        while i < len(bits):
            chunk = bits[i:i + 6]
            v = 0
            for j, b in enumerate(chunk):
                v |= (b & 1) << j
            self.cmd(0x4B, len(chunk) - 1, v)
            i += len(chunk)

    def toggle_clk(self, n):
        # RTI clocks with TMS=0 via 0x4B, 7 bits per command
        while n > 0:
            k = min(7, n)
            self.cmd(0x4B, k - 1, 0x00)
            n -= k

    def shift(self, data, nbits):
        nbytes = nbits // 8
        rem = nbits % 8
        if nbytes:
            self.cmd(0x39, (nbytes - 1) & 0xFF, ((nbytes - 1) >> 8) & 0xFF)
            for i in range(nbytes):
                self.cmd(data[i] if i < len(data) else 0)
        if rem:
            v = data[nbytes] if nbytes < len(data) else 0
            self.cmd(0x3B, rem - 1, v & ((1 << rem) - 1))

    def flush(self, expect=0):
        self.cmd(0xAA, 0x87)
        self.dev.write(0x02, bytes(self.buf))
        self.buf = bytearray()
        time.sleep(0.05)
        pl = read_payload()
        if pl.endswith(TERM):
            pl = pl[:-2]
        return pl

    def reset_tap(self):
        self.tms_bits([1, 1, 1, 1, 1])
        self.tms_bits([0])
        self.flush()

    # --- TAP state helpers: these assume we start in RTI and end in RTI ---
    def shift_ir(self, value):
        self.tms_bits([1, 1, 0, 0])
        self.shift(bytes([(value << 1) & 0xFF]), 8)
        self.tms_bits([1, 1, 0])

    def shift_dr(self, data, nbits):
        self.tms_bits([1, 0, 0])
        self.shift(data, nbits)
        self.tms_bits([1, 1, 0])

    def send_command(self, code):
        self.shift_ir(code)
        self.toggle_clk(6)
        self.flush()

    def read_reg32(self, code):
        self.send_command(code)
        self.shift_dr(b"\xff\xff\xff\xff", 32)
        data = self.flush()
        if len(data) < 4:
            print("read_reg32 0x%02x short read: %s" % (code, data.hex()), flush=True)
            return 0
        return int.from_bytes(data[:4], "little")

    def read_status(self):
        return self.read_reg32(STATUS_REGISTER)

    def poll(self, mask, value, tag, tries=300):
        for _ in range(tries):
            s = self.read_status()
            if (s & mask) == value:
                print("poll %s ok: status=0x%08x" % (tag, s), flush=True)
                return True
            time.sleep(0.02)
        print("poll %s TIMEOUT: last status=0x%08x" % (tag, s), flush=True)
        return False

    def enable_cfg(self):
        self.send_command(CONFIG_ENABLE)
        return self.poll(BIT_EDIT_MODE, BIT_EDIT_MODE, "edit-mode on")

    def disable_cfg(self):
        self.send_command(CONFIG_DISABLE)
        self.send_command(NOOP)
        return self.poll(BIT_EDIT_MODE, 0, "edit-mode off")


dev.ctrl_transfer(0x40, 0x0B, 0x0000, 1)
dev.ctrl_transfer(0x40, 0x0B, 0x0200, 1)
dev.ctrl_transfer(0x40, 0x09, 2, 1)
read_payload()

j = Jtag(dev)
# 1 MHz clock (divisor 5 on 12 MHz base)
j.cmd(0x86, 0x05, 0x00, 0x80, 0x08, 0x0B)
j.flush()
j.reset_tap()

# ================= GW5A SPI bridge (flash probe, read-only) =================
RELOAD = 0x3C

def rev8(b):
    return int("{:08b}".format(b)[::-1], 2)

def tms_tdi(bits, tdi):
    i = 0
    while i < len(bits):
        chunk = bits[i:i + 7]
        v = 0
        for k, b in enumerate(chunk):
            v |= (b & 1) << k
        if tdi:
            v |= 0x80
        j.cmd(0x4B, len(chunk) - 1, v)
        i += len(chunk)

def spi_put(cmd, tx, rx_total):
    tx = bytes(tx) if tx else b""
    rc = rev8(cmd)
    if rx_total is None:
        total_bits = len(tx) * 8
    else:
        total_bits = rx_total * 8 + 3
    tms_tdi([0], rc & 1)              # CS falls, first cmd bit on TDI
    j.shift(bytes([rc >> 1]), 7)      # remaining 7 cmd bits
    stream = bytearray(rev8(b) for b in tx)
    last_bit = (tx[-1] & 1) if tx else (cmd & 1)
    nbytes = total_bits // 8
    rembits = total_bits % 8
    while len(stream) < nbytes + (1 if rembits else 0):
        stream += bytes([0xFF if last_bit else 0x00])
    if nbytes:
        j.shift(bytes(stream[:nbytes]), nbytes * 8)
    if rembits:
        j.shift(bytes([stream[nbytes]]), rembits)
    tms_tdi([1] * 8, last_bit)        # CS rises
    cap = j.flush()
    if rx_total is None:
        return None
    body = cap[1:]
    if len(body) < rx_total + 1:
        print("spi_put 0x%02x short capture: cap=%d" % (cmd, len(cap)), flush=True)
        return None
    out = bytearray()
    for i in range(rx_total):
        out.append(rev8(((body[i] >> 3) | ((body[i + 1] & 0x07) << 5)) & 0xFF))
    return bytes(out)

def gw5a_disable_spi_dance():
    j.tms_bits([1] * 8)
    bits = [1, 0, 1, 0, 1] + [0, 1, 0, 1] * 6 + [0, 1, 0] + [1] * 8
    j.tms_bits(bits)
    j.flush()

def gw5a_enable_spi():
    if not j.enable_cfg():
        return False
    j.send_command(0x3F)
    if not j.disable_cfg():
        return False
    j.send_command(NOOP)
    j.toggle_clk(1008)
    j.flush()
    j.send_command(0x16)
    j.send_command(0x00)
    j.toggle_clk(5000)
    j.tms_bits([1, 1, 1, 1, 1])
    j.flush()
    return True

idc = j.read_reg32(READ_IDCODE)
import hashlib

# override with the recovery-proven dance (head goes via RTI, generous TLR forcing)
def gw5a_disable_spi_dance():
    j.tms_bits([1] * 16)
    bits = [0, 1, 0, 1, 0, 1] + [0, 1, 0, 1] * 6 + [0, 1, 0]
    j.tms_bits(bits)
    j.tms_bits([1] * 16)
    j.toggle_clk(5)
    j.flush()


IMG = "/data/data/com.termux/files/home/top.bin"
BAK = "/data/data/com.termux/files/home/flash_backup.bin"
EXPECTED_JEDEC = bytes([0x0B, 0x40, 0x17, 0x08])

if idc != 0x0001281B:
    print("IDCODE not readable (leftover SPI mode?) -> exit-spi dance", flush=True)
    gw5a_disable_spi_dance()
    idc = j.read_reg32(READ_IDCODE)
    print("IDCODE after dance = 0x%08x" % idc, flush=True)
print("IDCODE = 0x%08x" % idc, flush=True)
if idc != 0x0001281B:
    print("GATE FAIL: idcode mismatch", flush=True)
    sys.exit(2)
status = j.read_status()
print("STATUS start = 0x%08x DONE=%d" % (status, 1 if status & BIT_DONE else 0), flush=True)

# ---- prepare: RELOAD, idle clocks, erase SRAM (openFPGALoader prepare_flash_access) ----
j.send_command(RELOAD)
j.send_command(NOOP)
j.tms_bits([0])
for _ in range(100):
    j.toggle_clk(10000)
    j.flush()
print("reload + 1M clocks done", flush=True)

status = j.read_status()
if status & (BIT_TIMEOUT | BIT_AUTOBOOT2 | BIT_BAD_COMMAND):
    print("bad-state cleanup (0x3F)", flush=True)
    j.send_command(CONFIG_ENABLE)
    j.send_command(0x3F)
    j.send_command(CONFIG_DISABLE)
    j.send_command(NOOP)
    j.send_command(READ_IDCODE)
    j.send_command(NOOP)
    j.toggle_clk(1000)
    j.flush()

loop = 0
while True:
    if not j.enable_cfg():
        print("ERASE FAIL: enable_cfg", flush=True); sys.exit(1)
    j.send_command(ERASE_SRAM)
    j.send_command(NOOP)
    if not j.poll(BIT_MEMORY_ERASE, BIT_MEMORY_ERASE, "memory-erase"):
        print("ERASE FAIL: poll", flush=True); sys.exit(1)
    j.send_command(XFER_DONE)
    j.send_command(NOOP)
    if not j.disable_cfg():
        print("ERASE FAIL: disable_cfg", flush=True); sys.exit(1)
    if loop >= 1:
        s = j.read_status()
        print("erase loop %d status=0x%08x DONE=%d" % (loop, s, 1 if s & BIT_DONE else 0), flush=True)
        if not (s & BIT_DONE):
            break
    loop += 1
    if loop > 6:
        print("ERASE FAIL: loop", flush=True); sys.exit(1)
print("SRAM ERASED", flush=True)

# ---- enable SPI bridge (probe2-proven path) ----
if not j.enable_cfg():
    print("FAIL enable_cfg (spi)", flush=True); sys.exit(1)
j.send_command(0x3F)
if not j.disable_cfg():
    print("FAIL disable_cfg (spi)", flush=True); sys.exit(1)
j.send_command(NOOP)
j.toggle_clk(1008)
j.flush()
j.send_command(0x16)
j.send_command(0x00)
j.toggle_clk(5000)
j.tms_bits([1, 1, 1, 1, 1])
j.flush()
print("SPI MODE ON", flush=True)

# ---- flash helpers ----
def f_sr():
    r = spi_put(0x05, b"", 1)
    return r[0] if r else None

def f_wait_wip(tag, maxpoll=300):
    for _ in range(maxpoll):
        sr = f_sr()
        if sr is not None and not (sr & 1):
            return True
        time.sleep(0.01)
    print("WIP TIMEOUT:", tag, flush=True)
    return False

def f_wren():
    for _a in range(3):
        drain_brief()
        spi_put(0x06, b"", None)
        sr = f_sr()
        if sr is not None and (sr & 2):
            return True
        print("wren retry (sr=%s)" % (("0x%02x" % sr) if sr is not None else None), flush=True)
    return False

def fail(msg):
    print("FAIL:", msg, flush=True)
    gw5a_disable_spi_dance()
    sys.exit(1)

def f_read(addr, n):
    out = bytearray()
    while n > 0:
        k = min(n, 256)
        r = None
        for _try in range(3):
            r = spi_put(0x03, addr.to_bytes(3, "big") + bytes(k), 3 + k)
            if r is not None and len(r) >= 3 + k:
                break
            print("read retry @0x%x" % addr, flush=True)
        if r is None or len(r) < 3 + k:
            return None
        out += r[3:]
        addr += k
        n -= k
    return bytes(out)

spi_put(0xFF, b"\xff" * 8, None)
spi_put(0x66, b"", None)
spi_put(0x99, b"", None)
time.sleep(0.05)
jedec = spi_put(0x9F, b"", 4)
print("JEDEC:", jedec.hex() if jedec else None, flush=True)
if jedec != EXPECTED_JEDEC:
    print("GATE FAIL: unexpected JEDEC, aborting before erase", flush=True)
    gw5a_disable_spi_dance()
    sys.exit(2)
sr = f_sr()
print("SR = 0x%02x" % sr, flush=True)
if sr & 0x1C:
    print("BP bits set -> unprotect via WRSR 0x00", flush=True)
    if not f_wren():
        print("FAIL wren for WRSR", flush=True); sys.exit(1)
    spi_put(0x01, bytes([0x00]), None)
    f_wait_wip("wrsr")
    print("SR now = 0x%02x" % f_sr(), flush=True)

data = open(IMG, "rb").read()
img_md5 = hashlib.md5(data).hexdigest()
span = ((len(data) + 0xFFFF) // 0x10000) * 0x10000
print("image bytes: %d md5: %s erase span: %d" % (len(data), img_md5, span), flush=True)

# ---- backup current flash content over the erase span ----
BAK_MD5 = "229f426fd5d408187265a4b025d53d5b"
bak_ok = False
if os.path.exists(BAK):
    prev = open(BAK, "rb").read()
    if len(prev) == span and hashlib.md5(prev).hexdigest() == BAK_MD5:
        bak_ok = True
        print("backup already saved and verified, skipping re-read", flush=True)
if not bak_ok:
    bak = f_read(0, span)
    if bak is None:
        print("FAIL backup read", flush=True); sys.exit(1)
    open(BAK, "wb").write(bak)
    print("backup saved: %d bytes md5: %s" % (len(bak), hashlib.md5(bak).hexdigest()), flush=True)

# ---- erase blocks ----
for addr in range(0, span, 0x10000):
    if not f_wren():
        fail("wren erase @0x%x" % addr)
    spi_put(0xD8, addr.to_bytes(3, "big"), None)
    if not f_wait_wip("erase @0x%x" % addr, 600):
        fail("wait erase @0x%x" % addr)
    print("erased block @0x%05x" % addr, flush=True)

# ---- program pages ----
npages = (len(data) + 255) // 256
for p in range(npages):
    addr = p * 256
    chunk = data[addr:addr + 256]
    if len(chunk) < 256:
        chunk = chunk + b"\xff" * (256 - len(chunk))
    if not f_wren():
        fail("wren prog @0x%x" % addr)
    spi_put(0x02, addr.to_bytes(3, "big") + chunk, None)
    if not f_wait_wip("prog @0x%x" % addr, 100):
        fail("wait prog @0x%x" % addr)
    if p % 256 == 0:
        print("programmed page %d/%d" % (p, npages), flush=True)
print("PROGRAM DONE", flush=True)

# ---- verify ----
back = f_read(0, len(data))
if back is None:
    print("VERIFY FAIL: read error", flush=True); sys.exit(1)
back_md5 = hashlib.md5(back).hexdigest()
print("verify md5: %s (expect %s)" % (back_md5, img_md5), flush=True)
if back != data:
    # find first mismatch for diagnostics
    for i in range(len(data)):
        if back[i] != data[i]:
            print("first mismatch @%d: flash=0x%02x want=0x%02x" % (i, back[i], data[i]), flush=True)
            break
    print("VERIFY MISMATCH", flush=True)
    gw5a_disable_spi_dance()
    sys.exit(1)
print("VERIFY OK", flush=True)

# ---- exit SPI mode, reload from new flash ----
gw5a_disable_spi_dance()
j.send_command(RELOAD)
j.send_command(NOOP)
time.sleep(2.0)
s = j.read_status()
print("STATUS after RELOAD = 0x%08x DONE=%d" % (s, 1 if s & BIT_DONE else 0), flush=True)
print("FLASH_WRITE_DONE", flush=True)
