#!/usr/bin/env python3
"""Generate lisp_rp2040.c from ../lisp-sd/lisp_sd.c.

Same trick as hosttest/make_host_sd.py: the interpreter core is portable C;
only the UART macros, putc_/getc_, and the SDLOW section touch hardware.
For RP2040 (Pico SDK, stdio over USB CDC):
  - UART macros become dummies, putc_/getc_ become stdio calls.
  - The whole SDLOW block is replaced by stubs: no SD card, so sd_init
    fails and main() falls back to "REPL only" (see sd_boot). peek/poke
    keep their real dereference implementation (they now address ARM
    memory -- the user's own board, same as on Tang). SPI prims idle.
  - Heap grows to RP2040 scale: NCELLS 950 -> 16384 (128KB of cells),
    bytes arena 528 -> 32768.
"""
import pathlib, re

HERE = pathlib.Path(__file__).resolve().parent
src = (HERE.parent / "lisp-sd" / "lisp_sd.c").read_text()

# --- UART -> stdio (mirrors make_host_sd.py) ---
src = src.replace(
    '#define UART_DATA (*(volatile unsigned int *)0x02000000u)\n'
    '#define UART_STAT (*(volatile unsigned int *)0x02000004u)',
    '#include <stdio.h>\n#include <stdlib.h>\n#include "pico/stdio.h"\n'
    'static unsigned int uart_dummy_data, uart_dummy_stat;\n'
    '#define UART_DATA uart_dummy_data\n'
    '#define UART_STAT uart_dummy_stat')
src = re.sub(r'static void putc_\(char c\)\n\{.*?\n\}',
             'static void putc_(char c) { fputc(c, stdout); fflush(stdout); macropad_console_putc(c); }',
             src, flags=re.S)
src = re.sub(r'static int getc_\(void\)\n\{.*?\n\}',
             'static int getc_(void) { for (;;) { int pc = macropad_getc_poll(); '
             'if (pc >= 0) return pc; int c = getchar_timeout_us(10000); '
             'if (c >= 0) return c; } }',
             src, flags=re.S)

# --- SDLOW block -> RP2040 stubs ---
stub = r'''
/* ---- RP2040 stubs: no SD on this build ---- */
static int lisp_peek(unsigned addr) { return (int)*(volatile unsigned *)addr; }
static void lisp_poke(unsigned addr, unsigned v) { *(volatile unsigned *)addr = v; }
static void lisp_spi_cs(int a) { (void)a; }
static void lisp_spi_fast(int f) { (void)f; }
static int lisp_spi_byte(int b) { (void)b; return 0xFF; }
static int lisp_keybits(void) { return macropad_keybits(); }
static int lisp_encpos(void) { return macropad_encpos(); }
static int sd_init(void) { return -1; }
static int sd_read_block(unsigned lba, unsigned char *buf)
{ (void)lba; (void)buf; return -1; }
static int sd_write_block(unsigned lba, const unsigned char *buf)
{ (void)lba; (void)buf; return -1; }
'''
src, n = re.subn(r'/\*SDLOW_BEGIN\*/.*?/\*SDLOW_END\*/', stub.strip(),
                 src, flags=re.S)
assert n == 1, "SDLOW block not found"

# --- scale + banner ---
src = src.replace('#define NCELLS 800', '#define NCELLS 16384')
src = src.replace('#define BYTES_ARENA_SIZE 528',
                  '#define BYTES_ARENA_SIZE 32768')
src = src.replace(
    'TangLisp v2+SD -- a tiny Lisp on PicoRV32 / Tang Primer 25K',
    'TangLisp RP2040')

# --- OLED splash hook (display_macropad.c) ---
src = src.replace(
    'puts_("\\nTangLisp RP2040\\n");',
    'stdio_init_all();\n'
    '    macropad_keys_init();\n'
    '    macropad_splash();\n'
    '    puts_("\\nTangLisp RP2040\\n");')
src = ('extern void macropad_splash(void);\n'
       'extern void macropad_idle_tick(void);\n'
       'extern void macropad_keys_init(void);\n'
       'extern int macropad_keybits(void);\n'
       'extern int macropad_encpos(void);\n'
       'extern int macropad_getc_poll(void);\n'
       'extern void macropad_console_putc(int c);\n') + src

(HERE / "lisp_rp2040.c").write_text(src)
print("wrote", HERE / "lisp_rp2040.c", len(src), "bytes")
