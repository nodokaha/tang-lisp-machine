"""Pure helpers for the UF2-over-BOT flasher (uf2_wrap.py).

USB Mass Storage Bulk-Only Transport framing, the handful of SCSI
commands the RP2040 BOOTSEL drive needs, FAT BPB parsing (to find the
first data sector, mirroring what an OS file copy writes), and UF2
block validation. No USB or Termux dependencies: unit-testable anywhere.
"""
import struct

CBW_SIG = 0x43425355  # 'USBC'
CSW_SIG = 0x53425355  # 'USBS'

UF2_MAGIC_START0 = 0x0A324655  # 'UF2\n'
UF2_MAGIC_START1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30
RP2040_FAMILY = 0xE48BFF56


def build_cbw(tag, data_len, is_in, cdb, lun=0):
    flags = 0x80 if is_in else 0x00
    head = struct.pack("<IIIBBB", CBW_SIG, tag, data_len, flags, lun, len(cdb))
    return head + bytes(cdb).ljust(16, b"\x00")


def parse_csw(data):
    if len(data) != 13:
        raise ValueError("CSW length %d != 13" % len(data))
    sig, tag, residue, status = struct.unpack("<IIIB", data)
    if sig != CSW_SIG:
        raise ValueError("bad CSW signature 0x%08x" % sig)
    return tag, residue, status


def cdb_inquiry():
    return bytes([0x12, 0, 0, 0, 36, 0])


def cdb_test_unit_ready():
    return bytes([0x00, 0, 0, 0, 0, 0])


def cdb_request_sense():
    return bytes([0x03, 0, 0, 0, 18, 0])


def cdb_read_capacity10():
    return bytes([0x25] + [0] * 9)


def cdb_read10(lba, blocks):
    return bytes([0x28, 0,
                  (lba >> 24) & 0xFF, (lba >> 16) & 0xFF,
                  (lba >> 8) & 0xFF, lba & 0xFF,
                  0, (blocks >> 8) & 0xFF, blocks & 0xFF, 0])


def cdb_write10(lba, blocks):
    return bytes([0x2A, 0,
                  (lba >> 24) & 0xFF, (lba >> 16) & 0xFF,
                  (lba >> 8) & 0xFF, lba & 0xFF,
                  0, (blocks >> 8) & 0xFF, blocks & 0xFF, 0])


def parse_capacity(data):
    last_lba, block_size = struct.unpack(">II", data[:8])
    return last_lba, block_size


def parse_bpb_data_start(sector):
    """First data-area LBA of a FAT12/16/32 volume from its boot sector."""
    if len(sector) < 512:
        raise ValueError("boot sector too short")
    bps = struct.unpack_from("<H", sector, 11)[0]
    spc = sector[13]
    reserved = struct.unpack_from("<H", sector, 14)[0]
    nfats = sector[16]
    root_entries = struct.unpack_from("<H", sector, 17)[0]
    fat_size = struct.unpack_from("<H", sector, 22)[0]
    if fat_size == 0:
        fat_size = struct.unpack_from("<I", sector, 36)[0]
    if bps == 0 or spc == 0 or fat_size == 0:
        raise ValueError("implausible BPB (bps=%d spc=%d fat=%d)"
                         % (bps, spc, fat_size))
    root_secs = ((root_entries * 32) + bps - 1) // bps
    return reserved + nfats * fat_size + root_secs


def check_uf2(data):
    """Validate a UF2 image; return (num_blocks, family_id)."""
    if len(data) < 512 or len(data) % 512 != 0:
        raise ValueError("UF2 size %d is not a multiple of 512" % len(data))
    n = len(data) // 512
    family = None
    total = None
    for i in range(n):
        blk = data[i * 512:(i + 1) * 512]
        m0, m1 = struct.unpack_from("<II", blk, 0)
        if m0 != UF2_MAGIC_START0 or m1 != UF2_MAGIC_START1:
            raise ValueError("block %d: bad start magic" % i)
        mend, = struct.unpack_from("<I", blk, 508)
        if mend != UF2_MAGIC_END:
            raise ValueError("block %d: bad end magic" % i)
        _addr, _plen, bno, nblocks, fam = struct.unpack_from(
            "<IIIII", blk, 12)
        if bno != i:
            raise ValueError("block %d: blockNo field says %d" % (i, bno))
        if total is None:
            total = nblocks
            family = fam
        elif nblocks != total or fam != family:
            raise ValueError("block %d: inconsistent header" % i)
    if total != n:
        raise ValueError("header promises %d blocks, file has %d" % (total, n))
    return n, family
