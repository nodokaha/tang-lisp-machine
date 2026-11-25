#!/usr/bin/env python3
"""Synthesize a TangLisp world file (.BIN) in the firmware v8 layout.

Mirrors heap_save_to() in lisp-sd/lisp_sd.c:
  block 0   header: "TLHP", version, used, nsyms, genv, cksum, payload
  payload   cells (NCELLS x 8B: car, cdr as u32 LE)
            symtab (NSYMS x 16B: name, NUL-padded)
            usedbits (NCELLS/8 bytes)
  cksum     plain byte sum of the payload (u32)

val encoding: int = (n<<1)|1, symbol = symtab_addr|2,
prim = (index<<3)|6, bytes = addr|4, cons = cell_addr, NIL = 0.

The world contains a small but real environment: two closures
(fib, count), x = 42, a list y = (1 2 3), and the prim bindings,
so the visualizer has something worth looking at.
"""
import struct
import sys

# Layout of the current firmware (PROG41, IMG_VERSION 12). For a v7
# world (PROG39): NCELLS 320, bases 0x6C60 / 0x5560, VERSION 7.
# v8 (PROG40): NCELLS 288, NSYMS 80, bases 0x6D20 / 0x5620.
NCELLS, NSYMS = 2560, 192
CELLS_BASE, SYMTAB_BASE = 0x8450, 0x6850
VERSION = 12

symbols = []
sym_index = {}


def intern(name):
    if name in sym_index:
        return sym_index[name]
    sym_index[name] = len(symbols)
    symbols.append(name)
    return len(symbols) - 1


def S(name):
    return (SYMTAB_BASE + intern(name) * 16) | 2


def I(n):
    return ((n << 1) | 1) & 0xFFFFFFFF


def PRIM(i):
    return (i << 3) | 6


cells = []          # list of [car, cdr]
used = set()


def cons(car, cdr):
    idx = len(cells)
    cells.append([car, cdr])
    used.add(idx)
    return CELLS_BASE + idx * 8


def lst(*items, tail=0):
    out = tail
    for it in reversed(items):
        out = cons(it, out)
    return out


# --- parse-tree builders (quote the source shapes the REPL would build) ---
def fib_body():
    # (if (< n 2) n (+ (fib (- n 1)) (fib (- n 2))))
    n = S("n")
    rec1 = lst(S("fib"), lst(S("-"), n, I(1)))
    rec2 = lst(S("fib"), lst(S("-"), n, I(2)))
    return lst(S("if"), lst(S("<"), n, I(2)), n,
               lst(S("+"), rec1, rec2))


def count_body():
    # (if (= n 0) acc (count (- n 1) (+ acc 1)))
    n, acc = S("n"), S("acc")
    return lst(S("if"), lst(S("="), n, I(0)), acc,
               lst(S("count"), lst(S("-"), n, I(1)),
                   lst(S("+"), acc, I(1))))


def main():
    # prim bindings first, like the real genv (order is cosmetic here)
    prim_names = ["+", "-", "*", "=", "<", ">", "cons", "car", "cdr",
                  "null?", "pair?", "eq?", "not", "list", "print",
                  "save", "load", "dir", "delete-file", "dump"]
    prim_idx = {"+" : 0, "-": 1, "*": 2, "=": 3, "<": 4, ">": 5,
                "cons": 6, "car": 7, "cdr": 8, "null?": 9, "pair?": 10,
                "eq?": 11, "not": 12, "list": 13, "print": 14,
                "save": 15, "load": 16, "dir": 33, "delete-file": 34,
                "dump": 35}

    genv = 0
    # user world content (ends up on top of genv, like the real thing)
    fib_clo = cons(S("*closure*"),
                   lst(lst(S("n")), lst(fib_body()), 0))  # env patched below
    count_clo = cons(S("*closure*"),
                     lst(lst(S("n"), S("acc")), lst(count_body()), 0))
    y_val = lst(I(1), I(2), I(3))
    bindings = [
        ("x", I(42)),
        ("y", y_val),
        ("fib", fib_clo),
        ("count", count_clo),
    ]
    for name in prim_names:
        bindings.append((name, PRIM(prim_idx[name])))
    for name, val in bindings:
        genv = cons(cons(S(name), val), genv)
    # closures capture genv (self-reference, as in the firmware)
    for clo in (fib_clo, count_clo):
        ci = (clo - CELLS_BASE) // 8
        # closure layout: (*closure* params body env) as nested conses:
        # car=sym, cdr=(params . (body . (env . NIL))) -> env is the
        # cdr of the third cons; walk: clo -> cdr cell -> cdr cell -> set car
        c1 = (cells[ci][1] - CELLS_BASE) // 8   # (params body env)
        c2 = (cells[c1][1] - CELLS_BASE) // 8   # (body env)
        c3 = (cells[c2][1] - CELLS_BASE) // 8   # (env)
        cells[c3][0] = genv

    assert len(cells) <= NCELLS, len(cells)
    assert len(symbols) <= NSYMS, len(symbols)

    payload = bytearray()
    for i in range(NCELLS):
        car, cdr = cells[i] if i < len(cells) else (0, 0)
        payload += struct.pack("<II", car, cdr)
    for i in range(NSYMS):
        name = symbols[i].encode() if i < len(symbols) else b""
        payload += name.ljust(16, b"\0")[:16]
    bits = bytearray(NCELLS // 8)
    for i in used:
        bits[i // 8] |= 1 << (i % 8)
    payload += bits

    header = bytearray(512)
    header[0:4] = b"TLHP"
    struct.pack_into("<I", header, 4, VERSION)
    struct.pack_into("<I", header, 8, len(used))
    struct.pack_into("<I", header, 12, len(symbols))
    struct.pack_into("<I", header, 16, genv)
    struct.pack_into("<I", header, 20, sum(payload) & 0xFFFFFFFF)
    struct.pack_into("<I", header, 24, len(payload))

    out = bytes(header) + bytes(payload)
    out = out.ljust(((len(out) + 511) // 512) * 512, b"\0")
    path = sys.argv[1] if len(sys.argv) > 1 else "testworld.bin"
    open(path, "wb").write(out)
    print(f"{path}: {len(out)} bytes, {len(cells)} cells, "
          f"{len(used)} used, {len(symbols)} symbols, genv=0x{genv:04x}")


if __name__ == "__main__":
    main()
