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
    sd_img = fopen(path, "rb");
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
'''
src = re.sub(r'/\*SDLOW_BEGIN\*/.*?/\*SDLOW_END\*/', '/*SDLOW_BEGIN*/' + host_low + '/*SDLOW_END*/', src, flags=re.S)

src = src.replace("failed" + chr(10) + '");', "failed" + chr(92) + 'n");')
src = src.replace("opened" + chr(10) + '");', "opened" + chr(92) + 'n");')
assert 'host image opened' in src
pathlib.Path("/tmp/lisp_sd_host.c").write_text(src)
print("host source written")
