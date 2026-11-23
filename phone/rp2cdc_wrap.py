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
import time


def log(*a):
    print(*a, flush=True)


# ============ CDC console check for the freshly flashed TangLisp ============
if not devs:
    raise SystemExit("no USB device")
dev = devs[0]
log("device: %04x:%04x" % (dev.idVendor, dev.idProduct))

cfg = dev.get_active_configuration()
comm = datai = None
for intf in cfg:
    if intf.bInterfaceClass == 0x02:
        comm = intf
    elif intf.bInterfaceClass == 0x0A:
        datai = intf
if comm is None or datai is None:
    raise SystemExit("no CDC interfaces (comm=%s data=%s)" % (comm, datai))
log("comm intf", comm.bInterfaceNumber, "data intf", datai.bInterfaceNumber)
ep_out = ep_in = None
for ep in datai:
    if usb.util.endpoint_type(ep.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK:
        if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_OUT:
            ep_out = ep
        else:
            ep_in = ep
log("ep_out 0x%02x ep_in 0x%02x" % (ep_out.bEndpointAddress,
                                   ep_in.bEndpointAddress))
for intf in (comm, datai):
    n = intf.bInterfaceNumber
    try:
        if dev.is_kernel_driver_active(n):
            dev.detach_kernel_driver(n)
            log("detached kernel driver on", n)
    except Exception as e:
        log("detach check", n, e)
    usb.util.claim_interface(dev, n)
log("claimed")

dev.ctrl_transfer(0x21, 0x20, 0, comm.bInterfaceNumber,
                  bytes([0x00, 0xC2, 0x01, 0x00, 0x00, 0x00, 0x08]))
dev.ctrl_transfer(0x21, 0x22, 0x0003, comm.bInterfaceNumber, None)
log("line coding set, DTR+RTS on")


def drain(seconds):
    out = b""
    end = time.time() + seconds
    while time.time() < end:
        try:
            chunk = bytes(ep_in.read(64, 400))
            if chunk:
                out += chunk
                end = time.time() + 0.9
        except Exception:
            pass
    return out


time.sleep(0.5)
log("initial:", drain(1.5))
for expr in (b"(+ 1 2)\n", b"(fib 15)\n"):
    ep_out.write(expr, 2000)
    log("sent", expr, "-> got:", drain(3.5))
log("CDC DONE")
