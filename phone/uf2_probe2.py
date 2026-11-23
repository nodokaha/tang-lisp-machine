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

# ================= UF2 flasher for RP2040 BOOTSEL (RPI-RP2) =================
# Speaks USB Mass Storage BOT directly and streams the UF2 blocks as
# WRITE10s starting at the volume's first data sector -- the same sector
# stream an OS file copy produces, which is what the bootrom's UF2
# sniffer expects. No filesystem is mounted, so Android's "format this
# drive?" complaint about the virtual FAT is bypassed entirely.
import time
sys.path.insert(0, os.path.expanduser("~"))
from uf2_bot import (build_cbw, parse_csw, parse_capacity,
                     parse_bpb_data_start, check_uf2, cdb_inquiry,
                     cdb_test_unit_ready, cdb_request_sense,
                     cdb_read_capacity10, cdb_read10, cdb_write10,
                     RP2040_FAMILY)


def log(*a):
    print(*a, flush=True)


# Target file: first token of ~/uf2-args.txt, else ~/tanglisp.uf2.
uf2_path = "tanglisp.uf2"
try:
    with open(os.path.expanduser("~/uf2-args.txt")) as f:
        toks = f.read().split()
        if toks:
            uf2_path = toks[0]
except OSError:
    pass
if not os.path.isabs(uf2_path):
    uf2_path = os.path.expanduser("~/" + uf2_path)
with open(uf2_path, "rb") as f:
    uf2 = f.read()
nblocks, family = check_uf2(uf2)
log("UF2:", uf2_path, len(uf2), "bytes,", nblocks,
    "blocks, family 0x%08x" % family)
if family != RP2040_FAMILY:
    log("WARNING: family id is not RP2040 (0x%08x)" % RP2040_FAMILY)

if not devs:
    raise SystemExit("no USB device (termux-usb permission missing?)")
dev = devs[0]
log("device: %04x:%04x" % (dev.idVendor, dev.idProduct))
if (dev.idVendor, dev.idProduct) != (0x2E8A, 0x0003):
    # Safety gate (added after the 2026-11-22 CircuitPython incident):
    # never write UF2 sectors into anything but the RP2040 bootrom device.
    log("ABORT: not the RP2040 BOOTSEL device (2e8a:0003); refusing to write")
    raise SystemExit(2)

cfg = dev.get_active_configuration()
ms_intf = None
for intf in cfg:
    if intf.bInterfaceClass == 0x08:
        ms_intf = intf
        break
if ms_intf is None:
    raise SystemExit("no mass-storage interface on this device")
ep_out = ep_in = None
for ep in ms_intf:
    if usb.util.endpoint_type(ep.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK:
        if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_OUT:
            ep_out = ep
        else:
            ep_in = ep
inum = ms_intf.bInterfaceNumber
log("interface", inum, "ep_out 0x%02x ep_in 0x%02x"
    % (ep_out.bEndpointAddress, ep_in.bEndpointAddress))
try:
    if dev.is_kernel_driver_active(inum):
        dev.detach_kernel_driver(inum)
        log("detached kernel driver")
except Exception as e:
    log("detach check:", e)
usb.util.claim_interface(dev, inum)
log("claimed interface")

_tag = [0]


def bot(cdb, data_out=None, read_len=0, timeout=5000):
    """One BOT transaction; returns (status, data_in)."""
    _tag[0] += 1
    tag = _tag[0]
    dlen = len(data_out) if data_out is not None else read_len
    ep_out.write(build_cbw(tag, dlen, read_len > 0, cdb), timeout)
    data_in = None
    if data_out is not None:
        ep_out.write(data_out, timeout)
    if read_len:
        data_in = bytes(ep_in.read(read_len, timeout))
    csw = bytes(ep_in.read(13, timeout))
    _t, _r, status = parse_csw(csw)
    return status, data_in

st, din = bot(cdb_inquiry(), read_len=36)
log("INQUIRY status", st, "product", din[16:32])
st, _ = bot(cdb_test_unit_ready())
log("TUR status", st)

def rd(lba):
    st, d = bot(cdb_read10(lba, 1), read_len=512)
    return d

d0 = rd(0)
nz = [(i, b) for i, b in enumerate(d0) if b]
log("LBA0 nonzero:", nz)
log("LBA0 tail:", d0[496:512].hex())

hits = []
for lba in list(range(0, 41)) + [64, 96, 128, 129, 130, 160, 192, 193, 224, 256]:
    d = rd(lba)
    tags = []
    for s in (b"INFO_UF2", b"INDEX", b"RPI-RP2", b"UF2", b"html", b"HTM"):
        if s in d:
            tags.append(s.decode())
    n = sum(1 for b in d if b)
    if tags or n > 40:
        hits.append((lba, n, tags))
for h in hits:
    log("LBA hit:", h)
log("PROBE2 DONE")
