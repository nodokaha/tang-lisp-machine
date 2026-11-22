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

idc = j.read_reg32(READ_IDCODE)
print("IDCODE via IR = 0x%08x" % idc, flush=True)
if idc != 0x0001281B:
    print("GATE FAIL: idcode mismatch, aborting before erase", flush=True)
    sys.exit(2)
status = j.read_status()
print("STATUS before = 0x%08x (DONE=%d)" % (status, 1 if status & BIT_DONE else 0), flush=True)

# ---- erase SRAM (openFPGALoader eraseSRAM, GW5A path) ----
if status & (BIT_TIMEOUT | BIT_AUTOBOOT2 | BIT_BAD_COMMAND):
    print("status has timeout/autoboot/badcmd -> 0x3F cleanup", flush=True)
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
        print("ERASE FAIL: enable_cfg", flush=True)
        sys.exit(1)
    j.send_command(ERASE_SRAM)
    j.send_command(NOOP)
    if not j.poll(BIT_MEMORY_ERASE, BIT_MEMORY_ERASE, "memory-erase"):
        print("ERASE FAIL: poll", flush=True)
        sys.exit(1)
    j.send_command(XFER_DONE)
    j.send_command(NOOP)
    if not j.disable_cfg():
        print("ERASE FAIL: disable_cfg", flush=True)
        sys.exit(1)
    if loop >= 1:
        s = j.read_status()
        print("erase loop %d status=0x%08x DONE=%d" % (loop, s, 1 if s & BIT_DONE else 0), flush=True)
        if not (s & BIT_DONE):
            break
    loop += 1
    if loop > 6:
        print("ERASE FAIL: loop", flush=True)
        sys.exit(1)
print("ERASE DONE", flush=True)

# ---- write SRAM (openFPGALoader writeSRAM) ----
data = open("/data/data/com.termux/files/home/top.bin", "rb").read()
checksum = 0x9B9C
print("bitstream bytes:", len(data), flush=True)

j.send_command(CONFIG_ENABLE)
j.send_command(INIT_ADDR)
j.send_command(XFER_WRITE)

# enter Shift-DR and stream the whole bitstream with write-only byte commands
j.tms_bits([1, 0, 0])
j.flush()
stream = bytearray()
pos = 0
CH = 4096
while pos < len(data):
    chunk = data[pos:pos + CH]
    stream += bytes([0x19, (len(chunk) - 1) & 0xFF, ((len(chunk) - 1) >> 8) & 0xFF])
    stream += chunk
    pos += len(chunk)
    if len(stream) >= 65536:
        j.raw_write(stream)
        stream = bytearray()
        drain_brief()
if stream:
    j.raw_write(stream)
# exit Shift-DR -> RTI
j.tms_bits([1, 1, 0])
j.flush()
print("STREAM DONE", flush=True)

j.send_command(0x0A)
j.shift_dr(checksum.to_bytes(4, "little"), 32)
j.flush()
j.send_command(0x08)
j.send_command(CONFIG_DISABLE)
j.send_command(NOOP)

status = j.read_status()
print("STATUS after = 0x%08x (DONE=%d CRC_ERR=%d BAD_CMD=%d)" % (
    status,
    1 if status & BIT_DONE else 0,
    1 if status & BIT_CRC_ERROR else 0,
    1 if status & BIT_BAD_COMMAND else 0), flush=True)
ucode = j.read_reg32(READ_USERCODE)
print("USERCODE = 0x%08x" % ucode, flush=True)
print("PROG35_DONE" if status & BIT_DONE else "PROG35_NOT_DONE", flush=True)
