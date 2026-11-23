import pathlib, re
src = pathlib.Path.home().joinpath("workspace/tang/lisp-sd/lisp_sd.c").read_text()
src = src.replace('#define UART_DATA (*(volatile unsigned int *)0x02000000u)\n#define UART_STAT (*(volatile unsigned int *)0x02000004u)',
 '#include <stdio.h>\n#include <stdlib.h>\nstatic unsigned int uart_dummy_data, uart_dummy_stat;\n#define UART_DATA uart_dummy_data\n#define UART_STAT uart_dummy_stat')
src = re.sub(r'static void putc_\(char c\)\n\{.*?\n\}', 'static void putc_(char c) { fputc(c, stdout); fflush(stdout); }', src, flags=re.S)
src = re.sub(r'static int getc_\(void\)\n\{.*?\n\}', 'static int getc_(void) { int c = getchar(); if (c == EOF) exit(0); return c; }', src, flags=re.S)
# swap SD low-level for image-backed version
host_low = r'''
static int sd_ccs = 1;
static FILE *sd_img = 0;
static int sd_init(void)
{
    const char *path = getenv("SD_IMAGE");
    if (!path) path = "/tmp/fat32.img";
    sd_img = fopen(path, "r+b");
    if (!sd_img) sd_img = fopen(path, "rb");
    if (!sd_img) { puts_("SD: host image open failed\n"); return -1; }
    puts_("SD: host image opened\n");
    return 0;
}
static int sd_read_block(unsigned lba, unsigned char *buf)
{
    if (!sd_img) return -1;
    if (fseek(sd_img, (long)lba * 512L, SEEK_SET) != 0) return -1;
    return fread(buf, 1, 512, sd_img) == 512 ? 0 : -1;
}
static int sd_write_block(unsigned lba, const unsigned char *buf)
{
    if (!sd_img) return -1;
    if (fseek(sd_img, (long)lba * 512L, SEEK_SET) != 0) return -1;
    if (fwrite(buf, 1, 512, sd_img) != 512) return -1;
    fflush(sd_img);
    return 0;
}
// ---- SPI-byte-level SD emulator behind the Lisp glue (host only) ----
static FILE *emu_fp = 0;
static int emu_cs = 0, emu_ready = 0;
static unsigned char emu_cmd[6];
static int emu_cmdlen = 0;
static unsigned char emu_resp[600];
static int emu_resp_len = 0, emu_resp_pos = 0;
static int emu_wr_state = 0;
static unsigned emu_wr_lba = 0, emu_wr_count = 0;
static unsigned char emu_wr_buf[512];
static FILE *emu_open(void)
{
    const char *path;
    if (emu_fp) return emu_fp;
    path = getenv("SD_IMAGE");
    if (!path) path = "/tmp/fat32.img";
    emu_fp = fopen(path, "r+b");
    if (!emu_fp) emu_fp = fopen(path, "rb");
    return emu_fp;
}
static void emu_queue(const unsigned char *p, int n)
{
    int i;
    for (i = 0; i < n && emu_resp_len < 600; i++) emu_resp[emu_resp_len++] = p[i];
}
static void emu_command(void)
{
    unsigned idx = emu_cmd[0] & 0x3F;
    unsigned arg = ((unsigned)emu_cmd[1] << 24) | ((unsigned)emu_cmd[2] << 16) |
                   ((unsigned)emu_cmd[3] << 8) | (unsigned)emu_cmd[4];
    unsigned char r1;
    emu_resp_len = 0; emu_resp_pos = 0;
    switch (idx) {
    case 0: r1 = 0x01; emu_queue(&r1, 1); break;
    case 8: { unsigned char resp[5]; int i;
              resp[0] = 0x01; for (i = 0; i < 4; i++) resp[1 + i] = emu_cmd[1 + i];
              emu_queue(resp, 5); } break;
    case 55: r1 = emu_ready ? 0x00 : 0x01; emu_queue(&r1, 1); break;
    case 41: emu_ready = 1; r1 = 0x00; emu_queue(&r1, 1); break;
    case 58: { unsigned char resp[5] = {0x00, 0xC0, 0xFF, 0x80, 0x00};
               emu_queue(resp, 5); } break;
    case 17: {
        unsigned char hdr[3];
        FILE *f = emu_open();
        hdr[0] = 0x00; hdr[1] = 0xFF; hdr[2] = 0xFE;
        emu_queue(hdr, 3);
        if (f && fseek(f, (long)arg * 512L, SEEK_SET) == 0) {
            unsigned char buf[512];
            if (fread(buf, 1, 512, f) == 512) emu_queue(buf, 512);
        }
        { unsigned char crc[2] = {0xFF, 0xFF}; emu_queue(crc, 2); }
        } break;
    case 24: r1 = 0x00; emu_queue(&r1, 1); emu_wr_state = 1; emu_wr_lba = arg; break;
    default: r1 = 0x01; emu_queue(&r1, 1); break;
    }
}
static int emu_xfer(int b)
{
    int out = 0xFF;
    if (emu_resp_pos < emu_resp_len) out = emu_resp[emu_resp_pos++];
    if (!emu_cs) return 0xFF;
    if (emu_wr_state == 1) {
        if (b == 0xFE) { emu_wr_state = 2; emu_wr_count = 0; }
        return out;
    }
    if (emu_wr_state == 2) {
        emu_wr_buf[emu_wr_count++] = (unsigned char)b;
        if (emu_wr_count >= 512) emu_wr_state = 3;
        return out;
    }
    if (emu_wr_state == 3) { emu_wr_state = 4; return out; }
    if (emu_wr_state == 4) {
        FILE *f = emu_open();
        unsigned char resp = 0x05, done = 0xFF;
        if (f && fseek(f, (long)emu_wr_lba * 512L, SEEK_SET) == 0) {
            fwrite(emu_wr_buf, 1, 512, f);
            fflush(f);
        }
        emu_resp_len = 0; emu_resp_pos = 0;
        emu_queue(&resp, 1);
        emu_queue(&done, 1);
        emu_wr_state = 0;
        return out;
    }
    if (emu_cmdlen == 0 && (b & 0xC0) != 0x40) return out;
    emu_cmd[emu_cmdlen++] = (unsigned char)b;
    if (emu_cmdlen == 6) { emu_cmdlen = 0; emu_command(); }
    return out;
}
static void lisp_spi_cs(int a);
static int lisp_peek(unsigned addr)
{
    if (addr == 0x02000004u) return 2;
    if (addr == 0x03000004u) return 0;
    if (addr == 0x03000008u) return emu_cs ? 1 : 0;
    if (addr == 0x03000000u) return emu_xfer(0xFF);
    return 0;
}
static void lisp_poke(unsigned addr, unsigned v)
{
    if (addr == 0x03000008u) { lisp_spi_cs((v & 1u) != 0); return; }
    if (addr == 0x03000000u) { emu_xfer((int)(v & 0xFFu)); return; }
}
static void lisp_spi_cs(int a)
{
    if (a && !emu_cs) { emu_cmdlen = 0; emu_resp_len = 0; emu_resp_pos = 0; }
    if (!a) { emu_cmdlen = 0; emu_wr_state = 0; }
    emu_cs = a != 0;
}
static void lisp_spi_fast(int f) { (void)f; }
static int lisp_spi_byte(int b) { return emu_cs ? emu_xfer(b) : 0xFF; }
static int lisp_keybits(void) { return 0; }
static int lisp_encpos(void) { return 0; }
'''
src = re.sub(r'/\*SDLOW_BEGIN\*/.*?/\*SDLOW_END\*/', '/*SDLOW_BEGIN*/' + host_low + '/*SDLOW_END*/', src, flags=re.S)

src = src.replace("failed" + chr(10) + '");', "failed" + chr(92) + 'n");')
src = src.replace("opened" + chr(10) + '");', "opened" + chr(92) + 'n");')
assert 'host image opened' in src
pathlib.Path("/tmp/lisp_sd_host.c").write_text(src)
print("host source written")
