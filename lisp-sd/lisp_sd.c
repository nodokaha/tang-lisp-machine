// TangLisp v2+SD -- TangLisp v2 with an SD/FAT32 boot stage (Stage 3b).
// At boot, after the environment is built, the firmware mounts a FAT32
// card over the SoC SPI master, lists the root directory, and evaluates
// AUTOEXEC.LSP if present. Without a card it falls through to the REPL.
// v2 adds set! and proper tail calls: eval is a trampoline loop, so a
// call in tail position (if branches, last body form, let/begin tail)
// reuses the same C frame instead of growing the stack.
// No libc, no division/modulo operators (RV32I has no div; libgcc avoided).
#define UART_DATA (*(volatile unsigned int *)0x02000000u)
#define UART_STAT (*(volatile unsigned int *)0x02000004u)
#define SPI_DATA  (*(volatile unsigned int *)0x03000000u)
#define SPI_STAT  (*(volatile unsigned int *)0x03000004u)
#define SPI_CTRL  (*(volatile unsigned int *)0x03000008u)

// ---------- minimal runtime helpers (in case gcc emits calls) ----------
// volatile pointers: without them (and without -fno-builtin) gcc's
// loop-idiom recognizer turns the loop in memset into a call to
// memset itself -> infinite recursion. That bug cost two builds.
void *memset(void *d, int c, unsigned n)
{
    volatile unsigned char *p = (volatile unsigned char *)d;
    while (n--) *p++ = (unsigned char)c;
    return d;
}
void *memcpy(void *d, const void *s, unsigned n)
{
    volatile unsigned char *p = (volatile unsigned char *)d;
    const unsigned char *q = (const unsigned char *)s;
    while (n--) *p++ = *q++;
    return d;
}

// PicoRV32 is built without the M extension, so gcc's * needs this.
int __mulsi3(int a, int b)
{
    int r = 0;
    unsigned ua = (unsigned)a, ub = (unsigned)b;
    while (ub) {
        if (ub & 1u) r += (int)ua;
        ua <<= 1;
        ub >>= 1;
    }
    return r;
}

// ---------- UART ----------
static void putc_(char c)
{
    while (UART_STAT & 2u) { }
    UART_DATA = (unsigned int)(unsigned char)c;
}
static void puts_(const char *s) { while (*s) putc_(*s++); }
static int getc_(void)
{
    while (!(UART_STAT & 1u)) { }
    return (int)(UART_DATA & 0xFFu);
}

// divide by 10 without the / operator (binary long division)
static unsigned udiv10(unsigned n)
{
    unsigned q = 0, r = 0;
    int i;
    for (i = 31; i >= 0; i--) {
        r = (r << 1) | ((n >> i) & 1u);
        if (r >= 10u) { r -= 10u; q |= (1u << i); }
    }
    return q;
}
static void putnum(int n)
{
    char buf[12];
    int i = 0;
    unsigned u;
    if (n < 0) { putc_('-'); u = (unsigned)(-n); }
    else u = (unsigned)n;
    if (u == 0) { putc_('0'); return; }
    while (u) {
        unsigned q = udiv10(u);
        buf[i++] = (char)('0' + (int)(u - q * 10u));
        u = q;
    }
    while (i) putc_(buf[--i]);
}


// ---------- SD card (SPI mode, read-only) + FAT32 reader ----------
// The low-level part between SDLOW_BEGIN/SDLOW_END is the only piece
// that touches the SPI hardware; the host test build swaps it for a
// disk-image-backed version. Everything FAT uses just sd_init() and
// sd_read_block().
static void puthex8(unsigned v)
{
    static const char hexd[] = "0123456789ABCDEF";
    putc_(hexd[(v >> 4) & 0xFu]);
    putc_(hexd[v & 0xFu]);
}
static void puthex32(unsigned v)
{
    int i;
    for (i = 7; i >= 0; i--) {
        static const char hexd[] = "0123456789ABCDEF";
        putc_(hexd[(v >> (i * 4)) & 0xFu]);
    }
}
static void sd_delay(unsigned n)
{
    volatile unsigned i;
    for (i = 0; i < n; i++) { }
}

/*SDLOW_BEGIN*/
static unsigned spi_ctrl_shadow = 0;
static void sd_cs(int assert_)
{
    if (assert_) spi_ctrl_shadow |= 1u;
    else         spi_ctrl_shadow &= ~1u;
    SPI_CTRL = spi_ctrl_shadow;
}
static void spi_set_fast(int fast)
{
    if (fast) spi_ctrl_shadow |= 2u;
    else      spi_ctrl_shadow &= ~2u;
    SPI_CTRL = spi_ctrl_shadow;
}
static unsigned char spi_xfer(unsigned char b)
{
    while (SPI_STAT & 1u) { }
    SPI_DATA = (unsigned int)b;
    while (SPI_STAT & 1u) { }
    return (unsigned char)(SPI_DATA & 0xFFu);
}
static unsigned char sd_send_cmd(unsigned idx, unsigned arg, unsigned crc)
{
    unsigned char r = 0xFF;
    unsigned n = 0;
    spi_xfer(0xFF);
    spi_xfer((unsigned char)(0x40u | idx));
    spi_xfer((unsigned char)(arg >> 24));
    spi_xfer((unsigned char)(arg >> 16));
    spi_xfer((unsigned char)(arg >> 8));
    spi_xfer((unsigned char)arg);
    spi_xfer((unsigned char)crc);
    do {
        r = spi_xfer(0xFF);
        n++;
    } while ((r & 0x80u) && n < 200u);
    return r;
}
static int sd_ccs = 0;
// 0 = ok. Prints progress like the standalone SD test firmware.
static int sd_init(void)
{
    unsigned char r = 0xFF;
    unsigned char r7[4];
    unsigned char ocr[4];
    int v2 = 0;
    int i;
    sd_delay(200000);
    sd_cs(0);
    spi_set_fast(0);
    for (i = 0; i < 10; i++) spi_xfer(0xFF);
    for (i = 0; i < 100 && r != 0x01; i++) {
        sd_cs(1);
        r = sd_send_cmd(0, 0, 0x95);
        sd_cs(0);
        spi_xfer(0xFF);
        sd_delay(10000);
    }
    if (r != 0x01) { puts_("SD: CMD0 fail R1=0x"); puthex8(r); putc_('\n'); return -1; }
    puts_("SD: CMD0 ok\n");
    sd_cs(1);
    r = sd_send_cmd(8, 0x000001AAu, 0x87);
    if (r == 0x01) {
        for (i = 0; i < 4; i++) r7[i] = spi_xfer(0xFF);
        sd_cs(0);
        if (r7[3] != 0xAA || r7[2] != 0x01) { puts_("SD: CMD8 bad R7\n"); return -1; }
        v2 = 1;
        puts_("SD: SDv2\n");
    } else if (r == 0x05) {
        sd_cs(0);
        v2 = 0;
        puts_("SD: SDv1 (no HCS)\n");
    } else {
        sd_cs(0);
        puts_("SD: CMD8 fail R1=0x"); puthex8(r); putc_('\n');
        return -1;
    }
    r = 0xFF;
    for (i = 0; i < 1000; i++) {
        sd_cs(1);
        r = sd_send_cmd(55, 0, 0xFF);
        sd_cs(0);
        if (r != 0x00 && r != 0x01) break;
        sd_cs(1);
        r = sd_send_cmd(41, v2 ? 0x40000000u : 0u, 0xFF);
        sd_cs(0);
        if (r == 0x00) break;
        if (r != 0x01) break;
        sd_delay(50000);
    }
    if (r != 0x00) { puts_("SD: ACMD41 fail R1=0x"); puthex8(r); putc_('\n'); return -1; }
    puts_("SD: ready\n");
    spi_set_fast(1);
    sd_cs(1);
    r = sd_send_cmd(58, 0, 0xFF);
    if (r != 0x00) { sd_cs(0); puts_("SD: CMD58 fail\n"); return -1; }
    for (i = 0; i < 4; i++) ocr[i] = spi_xfer(0xFF);
    sd_cs(0);
    sd_ccs = (ocr[0] & 0x40u) != 0;
    puts_("SD: OCR 0x"); puthex32(((unsigned)ocr[0] << 24) | ((unsigned)ocr[1] << 16) |
                                  ((unsigned)ocr[2] << 8) | (unsigned)ocr[3]);
    puts_(sd_ccs ? " CCS=1\n" : " CCS=0\n");
    return 0;
}
// 0 = ok, buf receives 512 bytes.
static int sd_read_block(unsigned lba, unsigned char *buf)
{
    unsigned char r, tok = 0xFF;
    unsigned n = 0;
    int i;
    sd_cs(1);
    r = sd_send_cmd(17, sd_ccs ? lba : (lba << 9), 0xFF);
    if (r != 0x00) { sd_cs(0); return -1; }
    do {
        tok = spi_xfer(0xFF);
        n++;
    } while (tok == 0xFF && n < 100000u);
    if (tok != 0xFE) { sd_cs(0); return -1; }
    for (i = 0; i < 512; i++) buf[i] = spi_xfer(0xFF);
    spi_xfer(0xFF);
    spi_xfer(0xFF);
    sd_cs(0);
    spi_xfer(0xFF);
    return 0;
}
/*SDLOW_END*/

// ---------- FAT32 (read-only) ----------
static unsigned char blk[512];
static unsigned fat_part_lba, fat_begin, fat_data_begin;
static unsigned fat_spc, fat_root_cluster;
static unsigned auto_cluster, auto_size;
#define AUTOBUF_SIZE 2048
static unsigned char autobuf[AUTOBUF_SIZE];

static unsigned rd16(const unsigned char *p)
{
    return (unsigned)p[0] | ((unsigned)p[1] << 8);
}
static unsigned rd32(const unsigned char *p)
{
    return (unsigned)p[0] | ((unsigned)p[1] << 8) |
           ((unsigned)p[2] << 16) | ((unsigned)p[3] << 24);
}
static unsigned cluster_lba(unsigned c)
{
    return fat_data_begin + (c - 2) * fat_spc;
}
// Next cluster in the chain (0x0FFFFFFF-masked). Byte-wise FAT reads,
// so an entry straddling a sector boundary still works; no division.
static unsigned fat_next(unsigned c)
{
    unsigned base = c << 2;
    unsigned v = 0;
    int i;
    for (i = 0; i < 4; i++) {
        unsigned p = base + (unsigned)i;
        if (sd_read_block(fat_begin + (p >> 9), blk) != 0) return 0x0FFFFFFFu;
        v |= (unsigned)blk[p & 511u] << (i * 8);
    }
    return v & 0x0FFFFFFFu;
}
static int fat_mount(void)
{
    unsigned ptype, plba, bps, reserved, nfats, fatsz;
    int i, exfat = 1;
    static const char exfat_name[] = "EXFAT   ";
    if (sd_init() != 0) return -1;
    if (sd_read_block(0, blk) != 0) { puts_("FAT: block0 read fail\n"); return -1; }
    if (blk[510] != 0x55 || blk[511] != 0xAA) { puts_("FAT: bad boot signature\n"); return -1; }
    fat_part_lba = 0;
    if ((blk[0] == 0xEB || blk[0] == 0xE9) && rd16(blk + 11) == 512 && blk[13] != 0) {
        puts_("FAT: superfloppy (BPB in block 0)\n");
    } else {
        ptype = blk[0x1C2];
        plba = rd32(blk + 0x1C6);
        puts_("FAT: MBR partition type 0x"); puthex8(ptype);
        puts_(" start LBA "); putnum((int)plba); putc_('\n');
        if (ptype == 0 || plba == 0) { puts_("FAT: no partition\n"); return -1; }
        fat_part_lba = plba;
        if (sd_read_block(plba, blk) != 0) { puts_("FAT: BPB read fail\n"); return -1; }
    }
    for (i = 0; i < 8; i++) if (blk[3 + i] != (unsigned char)exfat_name[i]) exfat = 0;
    if (exfat) { puts_("FAT: exFAT detected -- not supported, skipping SD\n"); return -1; }
    bps = rd16(blk + 11);
    if (bps != 512) { puts_("FAT: sector size not 512\n"); return -1; }
    fat_spc = blk[13];
    reserved = rd16(blk + 14);
    nfats = blk[16];
    fatsz = rd32(blk + 36);
    fat_root_cluster = rd32(blk + 44);
    if (fat_spc == 0 || fatsz == 0 || nfats == 0) {
        puts_("FAT: not a FAT32 BPB (FAT12/16?)\n");
        return -1;
    }
    fat_begin = fat_part_lba + reserved;
    fat_data_begin = fat_begin + nfats * fatsz;
    puts_("FAT32: spc="); putnum((int)fat_spc);
    puts_(" fat_begin="); putnum((int)fat_begin);
    puts_(" data_begin="); putnum((int)fat_data_begin);
    puts_(" root_cluster="); putnum((int)fat_root_cluster);
    putc_('\n');
    return 0;
}
static void print_dirent(const unsigned char *e)
{
    int i, end;
    end = 8;
    while (end > 0 && e[end - 1] == ' ') end--;
    for (i = 0; i < end; i++) putc_((char)e[i]);
    if (e[8] != ' ') {
        putc_('.');
        end = 3;
        while (end > 0 && e[8 + end - 1] == ' ') end--;
        for (i = 0; i < end; i++) putc_((char)e[8 + i]);
    }
    if (e[11] & 0x10) puts_(" <DIR>");
    puts_("  ");
    putnum((int)rd32(e + 28));
    puts_(" bytes\n");
}
// Lists the root directory; returns AUTOEXEC.LSP's first cluster
// (0 = not found) and sets auto_size.
static unsigned fat_scan_root(void)
{
    unsigned c = fat_root_cluster;
    unsigned found = 0;
    int guard = 0;
    auto_cluster = 0;
    auto_size = 0;
    puts_("--- root directory ---\n");
    while (c >= 2 && c < 0x0FFFFFF8u && guard++ < 10000) {
        unsigned s;
        for (s = 0; s < fat_spc; s++) {
            int off, stop = 0;
            if (sd_read_block(cluster_lba(c) + s, blk) != 0) return found;
            for (off = 0; off < 512; off += 32) {
                const unsigned char *e = blk + off;
                int i, match;
                if (e[0] == 0x00) { stop = 1; break; }
                if (e[0] == 0xE5) continue;
                if (e[11] == 0x0F) continue; // LFN entry
                if (e[11] & 0x08) continue;  // volume label
                print_dirent(e);
                match = 1;
                for (i = 0; i < 11; i++)
                    if (e[i] != (unsigned char)"AUTOEXECLSP"[i]) match = 0;
                if (match && !(e[11] & 0x10)) {
                    found = (rd16(e + 20) << 16) | rd16(e + 26);
                    auto_size = rd32(e + 28);
                }
            }
            if (stop) return found;
        }
        c = fat_next(c);
    }
    return found;
}
static int fat_load(unsigned first_cluster, unsigned size)
{
    unsigned want = size < (AUTOBUF_SIZE - 1) ? size : (AUTOBUF_SIZE - 1);
    unsigned loaded = 0;
    unsigned c = first_cluster;
    int guard = 0;
    while (c >= 2 && c < 0x0FFFFFF8u && loaded < want && guard++ < 10000) {
        unsigned s;
        for (s = 0; s < fat_spc && loaded < want; s++) {
            unsigned take, i;
            if (sd_read_block(cluster_lba(c) + s, blk) != 0) return -1;
            take = want - loaded < 512 ? want - loaded : 512;
            for (i = 0; i < take; i++) autobuf[loaded + i] = blk[i];
            loaded += take;
        }
        c = fat_next(c);
    }
    autobuf[loaded] = 0;
    return (int)loaded;
}

// ---------- values ----------
// odd            -> fixnum (v >> 1)
// 0              -> nil
// (v & 7) == 0   -> cons cell pointer
// (v & 7) == 2   -> symbol (symtab entry pointer | 2)
// (v & 7) == 6   -> primitive (index << 3 | 6)
typedef int val;
#define NIL 0
static int is_cons(val v) { return v != 0 && (v & 7) == 0; }
static int is_sym(val v)  { return (v & 7) == 2; }
static int is_prim(val v) { return (v & 7) == 6; }
static int is_int(val v)  { return v & 1; }
static val mk_int(int n)  { return (n << 1) | 1; }
static int int_val(val v) { return v >> 1; }

struct Cell { val car, cdr; };
#define NCELLS 1200
static struct Cell cells[NCELLS];
static val car(val v) { return ((struct Cell *)v)->car; }
static val cdr(val v) { return ((struct Cell *)v)->cdr; }

// ---------- errors ----------
static int lisp_err = 0;
static void error_(const char *msg)
{
    if (!lisp_err) { puts_("ERR: "); puts_(msg); putc_('\n'); }
    lisp_err = 1;
}

// ---------- GC: mark-sweep. Roots: genv + an explicit root stack.
// eval/apply/parse push every value that is alive only in a C local,
// so cons() may run gc() when the heap runs dry, even mid-eval. ----
#define NWORDS ((NCELLS + 31) / 32)
#define NROOTS 512
static val roots[NROOTS];
static int nroots = 0;
static void push_root(val v) { if (nroots < NROOTS) roots[nroots++] = v; }
static unsigned markbits[NWORDS];
static unsigned usedbits[NWORDS];
static val freelist = NIL;
static val genv = NIL; // global environment (root)

static void mark(val v)
{
    while (is_cons(v)) {
        int i = (int)(((unsigned)v - (unsigned)cells) >> 3);
        if (markbits[i >> 5] & (1u << (i & 31))) return;
        markbits[i >> 5] |= (1u << (i & 31));
        mark(car(v));
        v = cdr(v);
    }
}
static void gc(void)
{
    int i;
    for (i = 0; i < NWORDS; i++) markbits[i] = 0;
    mark(genv);
    for (i = 0; i < nroots; i++) mark(roots[i]);
    freelist = NIL;
    for (i = NCELLS - 1; i >= 0; i--) {
        int used = (int)((usedbits[i >> 5] >> (i & 31)) & 1u);
        int marked = (int)((markbits[i >> 5] >> (i & 31)) & 1u);
        if (!used || !marked) {
            usedbits[i >> 5] &= ~(1u << (i & 31));
            cells[i].cdr = freelist;
            freelist = (val)&cells[i];
        }
    }
}
static val cons(val a, val d)
{
    val v;
    int i;
    if (freelist == NIL) gc();
    if (freelist == NIL) { error_("heap full"); return NIL; }
    v = freelist;
    freelist = cdr(freelist);
    i = (int)(((unsigned)v - (unsigned)cells) >> 3);
    usedbits[i >> 5] |= (1u << (i & 31));
    ((struct Cell *)v)->car = a;
    ((struct Cell *)v)->cdr = d;
    return v;
}
static void gc_init(void)
{
    int i;
    for (i = 0; i < NWORDS; i++) { markbits[i] = 0; usedbits[i] = 0; }
    freelist = NIL;
    for (i = NCELLS - 1; i >= 0; i--) {
        cells[i].cdr = freelist;
        freelist = (val)&cells[i];
    }
}

// ---------- symbols ----------
struct Sym { char name[16]; };
#define NSYMS 96
static struct Sym symtab[NSYMS] __attribute__((aligned(8)));
static int nsyms = 0;
static val sym_t, sym_quote, sym_if, sym_lambda, sym_define, sym_let,
           sym_begin, sym_closure, sym_set;

static int streq(const char *a, const char *b)
{
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}
static val intern(const char *name)
{
    int i, j;
    for (i = 0; i < nsyms; i++)
        if (streq(symtab[i].name, name)) return (val)&symtab[i] | 2;
    if (nsyms >= NSYMS) { error_("too many symbols"); return NIL; }
    for (j = 0; j < 15 && name[j]; j++) symtab[nsyms].name[j] = name[j];
    symtab[nsyms].name[j] = 0;
    return (val)&symtab[nsyms++] | 2;
}
static const char *sym_name(val v) { return ((struct Sym *)(v & ~7))->name; }

// ---------- printer ----------
static void print_val(val v)
{
    if (lisp_err) return;
    if (v == NIL) { puts_("()"); return; }
    if (is_int(v)) { putnum(int_val(v)); return; }
    if (is_sym(v)) { puts_(sym_name(v)); return; }
    if (is_prim(v)) { puts_("#<prim>"); return; }
    if (is_cons(v)) {
        if (car(v) == sym_closure) { puts_("#<closure>"); return; }
        putc_('(');
        for (;;) {
            print_val(car(v));
            v = cdr(v);
            if (v == NIL) break;
            if (!is_cons(v)) { puts_(" . "); print_val(v); break; }
            putc_(' ');
        }
        putc_(')');
        return;
    }
    puts_("#<?>");
}

// ---------- reader ----------
static const char *rp;
static void skip_ws(void)
{
    for (;;) {
        char c = *rp;
        if (c == ' ' || c == '\t' || c == '\r' || c == '\n') { rp++; continue; }
        if (c == ';') { while (*rp && *rp != '\n') rp++; continue; }
        return;
    }
}
static int is_delim(char c)
{
    return c == 0 || c == ' ' || c == '\t' || c == '\r' || c == '\n' ||
           c == '(' || c == ')' || c == '\'' || c == ';';
}
static val parse_val(void);
static val parse_list(void)
{
    val head, tail;
    skip_ws();
    if (*rp == ')') { rp++; return NIL; }
    if (*rp == '.' && is_delim(rp[1])) {
        rp++;
        tail = parse_val();
        skip_ws();
        if (*rp == ')') rp++;
        return tail;
    }
    head = parse_val();
    if (lisp_err) return NIL;
    push_root(head);
    tail = parse_list();
    if (lisp_err) { nroots--; return NIL; }
    push_root(tail);
    head = cons(head, tail);
    nroots -= 2;
    return head;
}
static val parse_val(void)
{
    char c;
    skip_ws();
    c = *rp;
    if (c == 0) { error_("unexpected end of input"); return NIL; }
    if (c == '(') { rp++; return parse_list(); }
    if (c == '\'') {
        val x;
        int slot;
        rp++;
        x = parse_val();
        if (lisp_err) return NIL;
        slot = nroots;
        push_root(x);
        x = cons(x, NIL);
        roots[slot] = x;
        if (!lisp_err) x = cons(sym_quote, x);
        nroots = slot;
        return x;
    }
    if ((c >= '0' && c <= '9') || (c == '-' && rp[1] >= '0' && rp[1] <= '9')) {
        int neg = 0, n = 0;
        if (c == '-') { neg = 1; rp++; }
        while (*rp >= '0' && *rp <= '9') { n = n * 10 + (*rp - '0'); rp++; }
        return mk_int(neg ? -n : n);
    }
    {
        char tok[16];
        int i = 0;
        while (!is_delim(*rp)) {
            if (i < 15) tok[i++] = *rp;
            rp++;
        }
        tok[i] = 0;
        if (i == 0) { error_("bad token"); return NIL; }
        return intern(tok);
    }
}

// ---------- evaluator ----------
static val eval(val e, val env);
static val eval_seq(val body, val env)
{
    val r = NIL;
    while (is_cons(body) && !lisp_err) {
        r = eval(car(body), env);
        body = cdr(body);
    }
    return r;
}
static val lookup(val sym, val env)
{
    while (is_cons(env)) {
        val bind = car(env);
        if (is_cons(bind) && car(bind) == sym) return cdr(bind);
        env = cdr(env);
    }
    error_("unbound variable");
    return NIL;
}
static void set_var(val sym, val v, val env)
{
    while (is_cons(env)) {
        val bind = car(env);
        if (is_cons(bind) && car(bind) == sym) {
            ((struct Cell *)bind)->cdr = v;
            return;
        }
        env = cdr(env);
    }
    error_("set! on unbound variable");
}
static val eval_list(val exprs, val env)
{
    val head = NIL, *tailp = &head;
    int hslot = nroots;
    push_root(NIL);
    while (is_cons(exprs) && !lisp_err) {
        val a = eval(car(exprs), env);
        val node;
        if (lisp_err) break;
        push_root(a);
        node = cons(a, NIL);
        nroots--;
        if (lisp_err) break;
        *tailp = node;
        roots[hslot] = head;
        tailp = &((struct Cell *)node)->cdr;
        exprs = cdr(exprs);
    }
    nroots = hslot;
    return head;
}

#define PRIM_ADD 0
#define PRIM_SUB 1
#define PRIM_MUL 2
#define PRIM_EQ  3
#define PRIM_LT  4
#define PRIM_GT  5
#define PRIM_CONS 6
#define PRIM_CAR 7
#define PRIM_CDR 8
#define PRIM_NULLP 9
#define PRIM_PAIRP 10
#define PRIM_EQP 11
#define PRIM_NOT 12
#define PRIM_LIST 13
#define PRIM_PRINT 14

static val apply_prim(int idx, val args)
{
    val a, b;
    switch (idx) {
    case PRIM_ADD: {
        int s = 0;
        while (is_cons(args)) { s += int_val(car(args)); args = cdr(args); }
        return mk_int(s);
    }
    case PRIM_SUB: {
        int r;
        if (!is_cons(args)) { error_("bad args"); return NIL; }
        r = int_val(car(args));
        args = cdr(args);
        if (!is_cons(args)) return mk_int(-r);
        while (is_cons(args)) { r -= int_val(car(args)); args = cdr(args); }
        return mk_int(r);
    }
    case PRIM_MUL: {
        int s = 1;
        while (is_cons(args)) { s *= int_val(car(args)); args = cdr(args); }
        return mk_int(s);
    }
    case PRIM_EQ:
    case PRIM_LT:
    case PRIM_GT: {
        int x, y;
        if (!is_cons(args) || !is_cons(cdr(args))) { error_("bad args"); return NIL; }
        x = int_val(car(args));
        y = int_val(car(cdr(args)));
        if (idx == PRIM_EQ) return x == y ? sym_t : NIL;
        if (idx == PRIM_LT) return x < y ? sym_t : NIL;
        return x > y ? sym_t : NIL;
    }
    case PRIM_CONS:
        if (!is_cons(args) || !is_cons(cdr(args))) { error_("bad args"); return NIL; }
        return cons(car(args), car(cdr(args)));
    case PRIM_CAR:
        a = is_cons(args) ? car(args) : NIL;
        if (a == NIL) return NIL;
        if (!is_cons(a)) { error_("car of non-pair"); return NIL; }
        return car(a);
    case PRIM_CDR:
        a = is_cons(args) ? car(args) : NIL;
        if (a == NIL) return NIL;
        if (!is_cons(a)) { error_("cdr of non-pair"); return NIL; }
        return cdr(a);
    case PRIM_NULLP:
        return (is_cons(args) && car(args) == NIL) ? sym_t : NIL;
    case PRIM_PAIRP:
        return (is_cons(args) && is_cons(car(args))) ? sym_t : NIL;
    case PRIM_EQP:
        if (!is_cons(args) || !is_cons(cdr(args))) { error_("bad args"); return NIL; }
        return car(args) == car(cdr(args)) ? sym_t : NIL;
    case PRIM_NOT:
        return (is_cons(args) && car(args) == NIL) ? sym_t : NIL;
    case PRIM_LIST:
        return args;
    case PRIM_PRINT:
        a = is_cons(args) ? car(args) : NIL;
        print_val(a);
        putc_('\n');
        return a;
    }
    error_("bad primitive");
    return NIL;
}

// Build (tag params body env) with the partial chain rooted, so a
// gc triggered by any of these conses cannot sweep it mid-build.
static val make_closure(val params, val body, val env)
{
    val r = cons(env, NIL);
    int slot;
    if (lisp_err) return NIL;
    slot = nroots;
    push_root(r);
    r = cons(body, r);
    roots[slot] = r;
    if (!lisp_err) {
        r = cons(params, r);
        roots[slot] = r;
    }
    if (!lisp_err) r = cons(sym_closure, r);
    nroots = slot;
    return r;
}

// Bind params to args on top of the closure env. Returns the new env
// (NIL on error, with lisp_err set). f and args stay rooted by caller.
static val bind_params(val f, val args)
{
    val params, newenv, p, a;
    int nslot;
    params = car(cdr(f));
    newenv = car(cdr(cdr(cdr(f))));
    nslot = nroots;
    push_root(newenv);
    p = params;
    a = args;
    while (is_cons(p) && is_cons(a)) {
        val bind = cons(car(p), car(a));
        if (lisp_err) break;
        push_root(bind);
        newenv = cons(bind, newenv);
        roots[nslot] = newenv;
        nroots--;
        if (lisp_err) break;
        p = cdr(p);
        a = cdr(a);
    }
    if (!lisp_err && (p != NIL || a != NIL)) error_("arity mismatch");
    nroots = nslot;
    return lisp_err ? NIL : newenv;
}

static val apply(val f, val args)
{
    val newenv;
    if (lisp_err) return NIL;
    if (is_prim(f)) return apply_prim(f >> 3, args);
    if (!is_cons(f) || car(f) != sym_closure) {
        error_("not a function");
        return NIL;
    }
    newenv = bind_params(f, args);
    if (lisp_err) return NIL;
    return eval_seq(car(cdr(cdr(f))), newenv);
}

// Helper for the trampoline: evaluate every form in body except the
// last one (in env), return the last form. NIL body -> NIL flag via
// *empty. body is part of an already-rooted structure, so walking it
// across eval() calls (which may gc) is safe.
static val seq_last(val body, val env, int *empty)
{
    *empty = 0;
    if (!is_cons(body)) { *empty = 1; return NIL; }
    while (is_cons(cdr(body)) && !lisp_err) {
        eval(car(body), env);
        body = cdr(body);
    }
    if (lisp_err) return NIL;
    return car(body);
}

// eval() is a trampoline: tail positions never recurse in C.
// The loop state is (e, env); roots[base] / roots[base+1] always hold
// the current pair, so a gc triggered by any cons can mark them, and
// they are refreshed at the top of every iteration.
// Tail positions handled by looping: if branches, the last form of a
// begin / let body / closure body, and a closure call in tail position
// (bind params, then loop over its body). Everything else (operator,
// operands, if condition, let init forms, set! value, non-last body
// forms) goes through a nested eval() call, whose own trampoline keeps
// its depth at one frame per non-tail nesting level.
static val eval(val e, val env)
{
    int base = nroots;
    push_root(e);
    push_root(env);
    for (;;) {
        val head;
        roots[base] = e;
        roots[base + 1] = env;
        if (lisp_err) break;
        if (e == NIL || is_int(e) || is_prim(e)) break;
        if (is_sym(e)) { e = lookup(e, env); break; }
        if (!is_cons(e)) break;
        head = car(e);
        if (head == sym_quote) { e = car(cdr(e)); break; }
        if (head == sym_if) {
            val cond = eval(car(cdr(e)), env);
            if (lisp_err) break;
            if (cond != NIL) e = car(cdr(cdr(e)));
            else if (is_cons(cdr(cdr(cdr(e))))) e = car(cdr(cdr(cdr(e))));
            else { e = NIL; break; }
            continue;
        }
        if (head == sym_lambda) {
            e = make_closure(car(cdr(e)), cdr(cdr(e)), env);
            break;
        }
        if (head == sym_define) {
            val target = car(cdr(e));
            if (is_cons(target)) {
                // (define (name . params) body...) -- bind first so the
                // closure's env includes its own binding (recursion).
                val bind = cons(car(target), NIL);
                val clo;
                int bslot;
                if (lisp_err) break;
                bslot = nroots;
                push_root(bind);
                genv = cons(bind, genv);
                clo = lisp_err ? NIL
                               : make_closure(cdr(target), cdr(cdr(e)), genv);
                if (!lisp_err) ((struct Cell *)bind)->cdr = clo;
                nroots = bslot;
                e = lisp_err ? NIL : clo;
                break;
            }
            {
                val bind = cons(target, NIL);
                val v;
                int bslot;
                if (lisp_err) break;
                bslot = nroots;
                push_root(bind);
                genv = cons(bind, genv);
                v = lisp_err ? NIL : eval(car(cdr(cdr(e))), genv);
                if (!lisp_err) ((struct Cell *)bind)->cdr = v;
                nroots = bslot;
                e = lisp_err ? NIL : v;
                break;
            }
        }
        if (head == sym_set) {
            // (set! name value) -- value is not a tail position.
            val target = car(cdr(e));
            val v;
            if (!is_sym(target) || !is_cons(cdr(cdr(e)))) {
                error_("bad set!");
                break;
            }
            v = eval(car(cdr(cdr(e))), env);
            if (lisp_err) break;
            set_var(target, v, env);
            e = v;
            break;
        }
        if (head == sym_let) {
            val binds = car(cdr(e));
            val newenv = env;
            int nslot = nroots;
            int empty = 0;
            val last;
            push_root(newenv);
            while (is_cons(binds) && !lisp_err) {
                val b = car(binds);
                val v = eval(car(cdr(b)), env);
                val bind;
                if (lisp_err) break;
                push_root(v);
                bind = cons(car(b), v);
                nroots--;
                if (lisp_err) break;
                push_root(bind);
                newenv = cons(bind, newenv);
                roots[nslot] = newenv;
                nroots--;
                binds = cdr(binds);
            }
            if (lisp_err) { nroots = nslot; break; }
            last = seq_last(cdr(cdr(e)), newenv, &empty);
            nroots = nslot;
            if (lisp_err) break;
            if (empty) { e = NIL; break; }
            e = last;
            env = newenv;
            continue;
        }
        if (head == sym_begin) {
            int empty = 0;
            val last = seq_last(cdr(e), env, &empty);
            if (lisp_err) break;
            if (empty) { e = NIL; break; }
            e = last;
            continue;
        }
        {
            // Function call. Operator and operands are not tail
            // positions; the call itself is, if this eval is.
            val f = eval(head, env);
            val args;
            int fslot;
            if (lisp_err) break;
            fslot = nroots;
            push_root(f);
            args = eval_list(cdr(e), env);
            if (lisp_err) { nroots = fslot; break; }
            push_root(args);
            if (is_prim(f)) {
                e = apply_prim(f >> 3, args);
                nroots = fslot;
                break;
            }
            if (!is_cons(f) || car(f) != sym_closure) {
                error_("not a function");
                nroots = fslot;
                break;
            }
            {
                val newenv = bind_params(f, args);
                int empty = 0;
                val last;
                if (lisp_err) { nroots = fslot; break; }
                push_root(newenv);
                last = seq_last(car(cdr(cdr(f))), newenv, &empty);
                if (lisp_err) { nroots = fslot; break; }
                if (empty) { nroots = fslot; e = NIL; break; }
                // Tail call: reuse this frame. f/args/newenv roots are
                // dropped; the loop roots take over with (last, newenv).
                nroots = base + 2;
                e = last;
                env = newenv;
                continue;
            }
        }
    }
    {
        val r = lisp_err ? NIL : e;
        nroots = base;
        return r;
    }
}


// ---------- SD boot stage: mount, list root, run AUTOEXEC.LSP ----------
static void sd_boot(void)
{
    unsigned fc;
    int n;
    if (fat_mount() != 0) {
        puts_("SD: unavailable -- starting REPL only\n");
        return;
    }
    fc = fat_scan_root();
    if (!fc) {
        puts_("AUTOEXEC.LSP not found\n");
        return;
    }
    auto_cluster = fc;
    puts_("AUTOEXEC.LSP found, ");
    putnum((int)auto_size);
    puts_(" bytes\n");
    n = fat_load(fc, auto_size);
    if (n <= 0) { puts_("AUTOEXEC.LSP load failed\n"); return; }
    rp = (const char *)autobuf;
    for (;;) {
        val e, r;
        skip_ws();
        if (*rp == 0) break;
        lisp_err = 0;
        e = parse_val();
        if (lisp_err) { puts_("AUTOEXEC: parse error\n"); break; }
        r = eval(e, genv);
        if (lisp_err) { puts_("AUTOEXEC: eval error\n"); break; }
        puts_("AUTOEXEC> ");
        print_val(r);
        putc_('\n');
        gc();
    }
    lisp_err = 0;
    puts_("AUTOEXEC done\n");
}

// ---------- REPL ----------
static void read_line(char *buf, int max)
{
    int n = 0;
    for (;;) {
        int c = getc_();
        if (c == '\r' || c == '\n') {
            putc_('\r'); putc_('\n');
            buf[n] = 0;
            return;
        }
        if ((c == 8 || c == 127) && n > 0) {
            n--;
            putc_('\b'); putc_(' '); putc_('\b');
            continue;
        }
        if (c >= 32 && c < 127 && n < max - 1) {
            buf[n++] = (char)c;
            putc_((char)c);
        }
    }
}
static int paren_balance(const char *s)
{
    int bal = 0;
    while (*s) {
        if (*s == '(') bal++;
        else if (*s == ')') bal--;
        s++;
    }
    return bal;
}

static const char *prim_names[] = {
    "+", "-", "*", "=", "<", ">", "cons", "car", "cdr",
    "null?", "pair?", "eq?", "not", "list", "print", 0
};

int main(void)
{
    static char line[256];
    static char expr[640];
    int i;

    puts_("\nTangLisp v2+SD -- a tiny Lisp on PicoRV32 / Tang Primer 25K\n");
    gc_init();
    sym_t = intern("t");
    sym_quote = intern("quote");
    sym_if = intern("if");
    sym_lambda = intern("lambda");
    sym_define = intern("define");
    sym_let = intern("let");
    sym_begin = intern("begin");
    sym_set = intern("set!");
    sym_closure = intern("*closure*");
    genv = cons(cons(sym_t, sym_t), NIL);
    for (i = 0; prim_names[i]; i++) {
        val s = intern(prim_names[i]);
        genv = cons(cons(s, (val)((i << 3) | 6)), genv);
    }

    sd_boot();

    for (;;) {
        int elen = 0;
        expr[0] = 0;
        for (;;) {
            int j, bal;
            puts_(elen == 0 ? "> " : "... ");
            read_line(line, (int)sizeof(line));
            for (j = 0; line[j] && elen < (int)sizeof(expr) - 2; j++)
                expr[elen++] = line[j];
            expr[elen++] = '\n';
            expr[elen] = 0;
            bal = paren_balance(expr);
            if (bal < 0) { puts_("ERR: unbalanced parens\n"); elen = -1; }
            if (bal <= 0) break;
        }
        if (elen <= 0) { gc(); continue; }
        rp = expr;
        lisp_err = 0;
        {
            val e = parse_val();
            if (!lisp_err) {
                val r = eval(e, genv);
                if (!lisp_err) {
                    print_val(r);
                    putc_('\n');
                }
            }
        }
        lisp_err = 0;
        gc();
    }
}
