import sys

# Gowin .fs -> config-flash image: pack the .fs bit lines MSB-first with NO
# per-byte bit reversal. (fs2bin.py's bit reversal is for the JTAG/SRAM path
# only -- FsParser reverseByte=True. The FPGA's MSPI boot reads flash bytes
# as-is, so the flash image is the raw packing. Verified 2026-11-22: the
# reversed image failed autoboot (sync word tail 0x60 instead of 0x06),
# the raw image boots, DONE=1.)
src = sys.argv[1]
dst = sys.argv[2]
lines = []
for l in open(src).read().split("\n"):
    l = l.rstrip("\r")
    if not l or l.startswith("/"):
        continue
    lines.append(l)
data = bytearray()
for l in lines:
    assert len(l) % 8 == 0, "line not byte aligned: %d" % len(l)
    for i in range(0, len(l), 8):
        data.append(int(l[i:i + 8], 2))
open(dst, "wb").write(bytes(data))
import hashlib
print("wrote %s: %d bytes md5 %s" % (dst, len(data), hashlib.md5(bytes(data)).hexdigest()))
