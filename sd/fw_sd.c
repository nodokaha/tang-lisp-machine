// SD test firmware -- SD card SPI-mode initialization + block 0 read.
// Standalone test for the TangLisp SoC's SPI master (not the Lisp itself).
// No libc, no division/modulo operators (RV32I has no div; libgcc avoided).
#define UART_DATA (*(volatile unsigned int *)0x02000000u)
#define UART_STAT (*(volatile unsigned int *)0x02000004u)
#define SPI_DATA  (*(volatile unsigned int *)0x03000000u)
#define SPI_STAT  (*(volatile unsigned int *)0x03000004u)
#define SPI_CTRL  (*(volatile unsigned int *)0x03000008u)

// ---------- minimal runtime helpers (in case gcc emits calls) ----------
// volatile pointers: without them (and without -fno-builtin) gcc's
// loop-idiom recognizer turns the loop in memset into a call to
// memset itself -> infinite recursion. Same trap as lisp.c.
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

static void delay(unsigned n)
{
    volatile unsigned i;
    for (i = 0; i < n; i++) { }
}

// ---------- SPI ----------
static unsigned spi_ctrl_shadow = 0;
static void spi_ctrl_write(void) { SPI_CTRL = spi_ctrl_shadow; }
static void sd_cs(int assert_)
{
    if (assert_) spi_ctrl_shadow |= 1u;
    else         spi_ctrl_shadow &= ~1u;
    spi_ctrl_write();
}
static void spi_set_fast(int fast)
{
    if (fast) spi_ctrl_shadow |= 2u;
    else      spi_ctrl_shadow &= ~2u;
    spi_ctrl_write();
}
static unsigned char spi_xfer(unsigned char b)
{
    while (SPI_STAT & 1u) { }
    SPI_DATA = (unsigned int)b;
    while (SPI_STAT & 1u) { }
    return (unsigned char)(SPI_DATA & 0xFFu);
}

// ---------- SD commands ----------
// CS must already be asserted by the caller; it stays asserted after
// the call so the caller can read trailing bytes (R7 / OCR / data).
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

static void fail(unsigned cmd, unsigned resp)
{
    puts_("FAIL CMD");
    putnum((int)cmd);
    puts_(" R1=0x");
    puthex8(resp);
    putc_('\n');
    for (;;) { }
}

static unsigned char blk[512];

int main(void)
{
    unsigned char r = 0xFF;
    unsigned char r7[4];
    unsigned char ocr[4];
    int v2 = 0;
    int ccs = 0;
    int i;

    puts_("\nSD test -- SPI SD init on Tang Primer 25K\n");

    // Power-up wait, then 80+ clocks with CS high (SD spec).
    delay(200000);
    sd_cs(0);
    spi_set_fast(0);
    for (i = 0; i < 10; i++) spi_xfer(0xFF);
    puts_("clocks sent\n");

    // CMD0: go idle. CRC 0x95 is mandatory here.
    for (i = 0; i < 100 && r != 0x01; i++) {
        sd_cs(1);
        r = sd_send_cmd(0, 0, 0x95);
        sd_cs(0);
        spi_xfer(0xFF);
        delay(10000);
    }
    if (r != 0x01) fail(0, r);
    puts_("CMD0 ok (idle)\n");

    // CMD8: send-if-cond. 0x000001AA, CRC 0x87 mandatory.
    sd_cs(1);
    r = sd_send_cmd(8, 0x000001AAu, 0x87);
    if (r == 0x01) {
        for (i = 0; i < 4; i++) r7[i] = spi_xfer(0xFF);
        sd_cs(0);
        puts_("CMD8 R7: ");
        for (i = 0; i < 4; i++) { puthex8(r7[i]); putc_(' '); }
        putc_('\n');
        if (r7[3] != 0xAA || r7[2] != 0x01) fail(8, r7[3]);
        v2 = 1;
        puts_("SDv2 detected\n");
    } else if (r == 0x05) {
        // idle + illegal-command: pre-v2 card, no HCS.
        sd_cs(0);
        v2 = 0;
        puts_("CMD8 rejected: SDv1, continuing without HCS\n");
    } else {
        sd_cs(0);
        fail(8, r);
    }

    // ACMD41: CMD55 + CMD41 until the card leaves idle (R1 == 0x00).
    r = 0xFF;
    for (i = 0; i < 1000; i++) {
        sd_cs(1);
        r = sd_send_cmd(55, 0, 0xFF);
        sd_cs(0);
        if (r != 0x00 && r != 0x01) fail(55, r);
        sd_cs(1);
        r = sd_send_cmd(41, v2 ? 0x40000000u : 0u, 0xFF);
        sd_cs(0);
        if (r == 0x00) break;
        if (r != 0x01) fail(41, r);
        delay(50000);
    }
    if (r != 0x00) fail(41, r);
    puts_("ACMD41 ok (ready)\n");

    // Data speed from here on.
    spi_set_fast(1);

    // CMD58: read OCR, check CCS (card capacity status).
    sd_cs(1);
    r = sd_send_cmd(58, 0, 0xFF);
    if (r != 0x00) { sd_cs(0); fail(58, r); }
    for (i = 0; i < 4; i++) ocr[i] = spi_xfer(0xFF);
    sd_cs(0);
    puts_("OCR: 0x");
    puthex32(((unsigned)ocr[0] << 24) | ((unsigned)ocr[1] << 16) |
             ((unsigned)ocr[2] << 8) | (unsigned)ocr[3]);
    putc_('\n');
    ccs = (ocr[0] & 0x40u) != 0;
    puts_(ccs ? "CCS=1 (SDHC/SDXC, block addressing)\n"
              : "CCS=0 (SDSC, byte addressing)\n");

    // CMD17: read single block 0 (address 0 in both addressing modes).
    sd_cs(1);
    r = sd_send_cmd(17, 0, 0xFF);
    if (r != 0x00) { sd_cs(0); fail(17, r); }
    {
        unsigned char tok = 0xFF;
        unsigned n = 0;
        do {
            tok = spi_xfer(0xFF);
            n++;
        } while (tok == 0xFF && n < 100000u);
        if (tok != 0xFE) {
            sd_cs(0);
            puts_("FAIL CMD17 data token 0x");
            puthex8(tok);
            putc_('\n');
            for (;;) { }
        }
    }
    for (i = 0; i < 512; i++) blk[i] = spi_xfer(0xFF);
    spi_xfer(0xFF); // CRC hi
    spi_xfer(0xFF); // CRC lo
    sd_cs(0);
    spi_xfer(0xFF);
    puts_("CMD17 ok, block0[0..15]:");
    for (i = 0; i < 16; i++) { putc_(' '); puthex8(blk[i]); }
    putc_('\n');
    puts_("block0[510..511]: ");
    puthex8(blk[510]);
    putc_(' ');
    puthex8(blk[511]);
    if (blk[510] == 0x55 && blk[511] == 0xAA) puts_(" (sig OK)\n");
    else puts_(" (sig MISMATCH)\n");

    puts_("SD OK\n");
    for (;;) { }
}
