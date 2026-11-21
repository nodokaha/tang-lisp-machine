import sys

def bitrev(b):
    return int("{:08b}".format(b)[::-1], 2)

path = sys.argv[1]
raw = open(path).read().split("\n")
stored = []
for l in raw:
    l = l.rstrip("\r")
    if not l or l.startswith("/"):
        continue
    stored.append(l)

idcode = None
crc_on = None
conf_len = None
compressed = None
hdr_checksum = None
for l in stored[:12]:
    if len(l) < 8:
        continue
    key = int(l[:8], 2) & 0x7F
    val = int(l, 2)
    if key == 0x06 and len(l) == 64:
        idcode = val & 0xFFFFFFFF
    elif key == 0x3B and len(l) == 32:
        crc_on = (val >> 23) & 1
        conf_len = val & 0xFFFF
    elif key == 0x10 and len(l) == 64:
        compressed = (val >> 13) & 1
    elif key == 0x0A:
        hdr_checksum = val & 0xFFFFFFFF

print("idcode: 0x%08x" % (idcode or 0))
print("crc_on:", crc_on, "conf_len:", conf_len, "compressed:", compressed)
print("hdr key0x0A value: 0x%08x" % (hdr_checksum or 0))

# data bytes: whole file, each byte bit-reversed (FsParser reverseByte=True for SRAM)
data = bytearray()
for l in stored:
    assert len(l) % 8 == 0, "line not byte aligned: %d" % len(l)
    for i in range(0, len(l), 8):
        data.append(bitrev(int(l[i:i + 8], 2)))
print("data bytes:", len(data), "bits:", len(data) * 8)

# FsParser-style checksum over config lines
nb = 65535
if conf_len is not None and conf_len < nb:
    nb = conf_len
cfg = stored[:nb]
drop = 48 + (16 if crc_on else 0)
parts = []
ok = True
for l in cfg:
    if len(l) < drop:
        print("short line in checksum range: len", len(l))
        ok = False
        break
    parts.append(l[:len(l) - drop])
checksum = None
if ok:
    tmp = "".join(parts)
    if len(tmp) % 16 != 0:
        print("checksum tmp not 16-aligned:", len(tmp))
    else:
        s = 0
        for i in range(0, len(tmp), 16):
            s = (s + int(tmp[i:i + 16], 2)) & 0xFFFF
        checksum = s
print("fsparser-style checksum:", None if checksum is None else "0x%04x" % checksum)

open("/home/hatch/workspace/tang/top.bin", "wb").write(bytes(data))
print("wrote top.bin")
