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

import time
import usb.core
import usb.util
from collections import Counter

dev = usb.core.find(idVendor=0x0403, idProduct=0x6010)
try:
    if dev.is_kernel_driver_active(1):
        dev.detach_kernel_driver(1)
        print("detached if1", flush=True)
except Exception as e:
    print("detach if1 note:", e, flush=True)
usb.util.claim_interface(dev, 1)
print("claimed interface 1 (channel B)", flush=True)

# Full FTDI UART setup sequence on channel B (wIndex=2)
for req, val, note in [
    (0x00, 0x0000, "SIO_RESET"),
    (0x03, 0x001A, "SET_BAUD 115200"),
    (0x04, 0x0008, "SET_DATA 8N1"),
    (0x02, 0x0000, "SET_FLOW_CTRL off"),
    (0x01, 0x0101, "MODEM_CTRL DTR on"),
    (0x01, 0x0202, "MODEM_CTRL RTS on"),
]:
    try:
        dev.ctrl_transfer(0x40, req, val, 2)
        print("ctrl ok:", note, flush=True)
    except Exception as e:
        print("ctrl note:", note, e, flush=True)

data = bytearray()
deadline = time.time() + 8
while time.time() < deadline:
    try:
        d = bytes(dev.read(0x83, 512, timeout=300))
    except Exception:
        continue
    if len(d) > 2:
        data += d[2:]
c = Counter(data)
print("full-setup: %d bytes, top: %s" % (len(data), c.most_common(5)), flush=True)
print("first 24:", bytes(data[:24]).hex(), flush=True)
print("UART_LISTEN2_DONE", flush=True)
