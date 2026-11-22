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

dev = usb.core.find(idVendor=0x0403, idProduct=0x6010)
try:
    if dev.is_kernel_driver_active(1):
        dev.detach_kernel_driver(1)
except Exception:
    pass
usb.util.claim_interface(dev, 1)
for req, val in [(0x00, 0x0000), (0x03, 0x001A), (0x04, 0x0008),
                 (0x02, 0x0000), (0x01, 0x0101), (0x01, 0x0202)]:
    try:
        dev.ctrl_transfer(0x40, req, val, 2)
    except Exception:
        pass


def drain(seconds):
    data = bytearray()
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            d = bytes(dev.read(0x83, 512, timeout=250))
        except Exception:
            continue
        if len(d) > 2:
            data += d[2:]
    return bytes(data)


TESTS = [
    ("fib-restored", "(fib 10)\n", "\r\n55\n", 6),
    ("count-restored", "(count 2000 0)\n", "\r\n2000\n", 10),
]

boot = drain(3)
print("BOOT[%d]: %r" % (len(boot), boot), flush=True)
print("RESTORED" if b"HEAPIMG restored" in boot else "NOT_RESTORED", flush=True)
npass = 0
for name, send, expect, wait in TESTS:
    dev.write(0x04, send.encode())
    got = drain(wait)
    ok = expect.encode() in got
    npass += 1 if ok else 0
    print("%s %s: %r" % ("PASS" if ok else "FAIL", name, got), flush=True)
print("RESULT: %d/%d passed" % (npass, len(TESTS)), flush=True)
print("LISP_TEST35B_DONE", flush=True)
