import struct

SECTOR = 512
PART_LBA = 2048
PART_SECTORS = 30720          # 15 MB partition
SPC = 4                        # 2 KiB clusters
RESERVED = 32
NFATS = 2

# solve FAT size
fatsz = 1
for _ in range(100):
    data_secs = PART_SECTORS - RESERVED - NFATS * fatsz
    clusters = data_secs // SPC
    need = ((clusters + 2) * 4 + SECTOR - 1) // SECTOR
    if need == fatsz:
        break
    fatsz = need
data_secs = PART_SECTORS - RESERVED - NFATS * fatsz
clusters = data_secs // SPC
print("fatsz", fatsz, "clusters", clusters)

img = bytearray(SECTOR * (PART_LBA + PART_SECTORS))

def put_sec(lba, data):
    img[lba*SECTOR:(lba+1)*SECTOR] = data

# ---- MBR ----
mbr = bytearray(SECTOR)
mbr[0x1BE+0] = 0x00
mbr[0x1BE+4] = 0x0C                       # FAT32 LBA
struct.pack_into("<I", mbr, 0x1BE+8, PART_LBA)
struct.pack_into("<I", mbr, 0x1BE+12, PART_SECTORS)
mbr[510], mbr[511] = 0x55, 0xAA
put_sec(0, mbr)

# ---- BPB ----
bpb = bytearray(SECTOR)
bpb[0:3] = bytes([0xEB, 0x58, 0x90])
bpb[3:11] = b"mkdosfs "
struct.pack_into("<H", bpb, 11, SECTOR)   # bytes/sector
bpb[13] = SPC
struct.pack_into("<H", bpb, 14, RESERVED)
bpb[16] = NFATS
struct.pack_into("<H", bpb, 17, 0)        # root entries (FAT32: 0)
struct.pack_into("<H", bpb, 19, 0)        # totsec16
bpb[21] = 0xF8
struct.pack_into("<H", bpb, 22, 0)        # fatsz16
struct.pack_into("<H", bpb, 24, 63)
struct.pack_into("<H", bpb, 26, 255)
struct.pack_into("<I", bpb, 28, PART_LBA) # hidden
struct.pack_into("<I", bpb, 32, PART_SECTORS)
struct.pack_into("<I", bpb, 36, fatsz)
struct.pack_into("<I", bpb, 44, 2)        # root cluster
bpb[510], bpb[511] = 0x55, 0xAA
put_sec(PART_LBA, bpb)
put_sec(PART_LBA + 6, bpb)                # backup boot sector

fat_begin = PART_LBA + RESERVED
data_begin = fat_begin + NFATS * fatsz

# ---- FAT ----
fat = bytearray(fatsz * SECTOR)
def fat_set(i, v):
    struct.pack_into("<I", fat, i*4, v)
fat_set(0, 0xFFFFFFF8)
fat_set(1, 0xFFFFFFFF)
for c in (2, 3, 4):
    fat_set(c, 0x0FFFFFFF)
for f in range(NFATS):
    for s in range(fatsz):
        put_sec(fat_begin + f*fatsz + s, fat[s*SECTOR:(s+1)*SECTOR])

def clus_lba(c):
    return data_begin + (c - 2) * SPC

# ---- AUTOEXEC.LSP (cluster 3) ----
autoexec = (b"(define (fib n) (if (< n 2) n (+ (fib (- n 1)) (fib (- n 2)))))\r\n"
            b"(print (fib 10))\r\n"
            b"(define (count n acc) (if (= n 0) acc (count (- n 1) (+ acc 1))))\r\n"
            b"(print (count 2000 0))\r\n"
            b"(+ 40 2)\r\n")
buf = bytearray(SPC * SECTOR)
buf[:len(autoexec)] = autoexec
for s in range(SPC):
    put_sec(clus_lba(3) + s, buf[s*SECTOR:(s+1)*SECTOR])

# ---- DUMMY.TXT (cluster 4) ----
buf = bytearray(SPC * SECTOR)
buf[:5] = b"HELLO"
for s in range(SPC):
    put_sec(clus_lba(4) + s, buf[s*SECTOR:(s+1)*SECTOR])

# ---- root directory (cluster 2) ----
def entry(name11, attr, cluster, size, first=None):
    e = bytearray(32)
    e[0:11] = name11
    if first is not None:
        e[0] = first
    e[11] = attr
    struct.pack_into("<H", e, 20, (cluster >> 16) & 0xFFFF)
    struct.pack_into("<H", e, 26, cluster & 0xFFFF)
    struct.pack_into("<I", e, 28, size)
    return e

root = bytearray(SPC * SECTOR)
root[0:32] = entry(b"TANGLISP   ", 0x08, 0, 0)                    # volume label
lfn = bytearray(32)
lfn[0] = 0x41
for i, ch in enumerate("autoexec.lsp"):
    struct.pack_into("<H", lfn, 1 + i*2, ord(ch))
lfn[11] = 0x0F
root[32:64] = lfn                                                 # LFN (skip)
root[64:96] = entry(b"DELETED TXT", 0x20, 5, 123, first=0xE5)     # deleted (skip)
root[96:128] = entry(b"AUTOEXECLSP", 0x20, 3, len(autoexec))
root[128:160] = entry(b"DUMMY   TXT", 0x20, 4, 5)
# rest zeros = end marker
for s in range(SPC):
    put_sec(clus_lba(2) + s, root[s*SECTOR:(s+1)*SECTOR])

open("/tmp/fat32.img", "wb").write(img)
print("image bytes", len(img), "fat_begin", fat_begin, "data_begin", data_begin)
