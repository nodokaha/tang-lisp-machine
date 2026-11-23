/* MacroPad RP2040 OLED splash: SH1106 128x64 on SPI1.
 *
 * Pins (Pico SDK board header / Adafruit pinout):
 *   SCK GP26, MOSI GP27, CS GP22, RESET GP23, DC GP24.
 * Draws a static proof-of-life splash from macropad_splash(), called
 * from the interpreter's main() right after the banner. Also lights
 * the board LED (GP13) so "main was reached" is visible even if the
 * display path misbehaves. Write-only SPI: nothing here can block.
 */
#include "pico/stdlib.h"
#include "pico/stdio_usb.h"
#include "hardware/spi.h"
#include "hardware/gpio.h"
#include <stdio.h>

#define PIN_SCK 26
#define PIN_MOSI 27
#define PIN_CS 22
#define PIN_RST 23
#define PIN_DC 24
#define PIN_LED 13

static uint8_t fb[128 * 64 / 8];

static void cs(int on) { gpio_put(PIN_CS, on ? 0 : 1); }

static void write_cmd(uint8_t c)
{
    gpio_put(PIN_DC, 0);
    cs(1);
    spi_write_blocking(spi1, &c, 1);
    cs(0);
}

static void write_data(const uint8_t *p, int n)
{
    gpio_put(PIN_DC, 1);
    cs(1);
    spi_write_blocking(spi1, p, n);
    cs(0);
}

static void oled_init(void)
{
    gpio_init(PIN_CS);
    gpio_set_dir(PIN_CS, GPIO_OUT);
    gpio_put(PIN_CS, 1);
    gpio_init(PIN_DC);
    gpio_set_dir(PIN_DC, GPIO_OUT);
    gpio_init(PIN_RST);
    gpio_set_dir(PIN_RST, GPIO_OUT);
    gpio_put(PIN_RST, 1);
    sleep_ms(10);
    gpio_put(PIN_RST, 0);
    sleep_ms(10);
    gpio_put(PIN_RST, 1);

    spi_init(spi1, 8000 * 1000);
    gpio_set_function(PIN_SCK, GPIO_FUNC_SPI);
    gpio_set_function(PIN_MOSI, GPIO_FUNC_SPI);

    static const uint8_t init[] = {
        0xAE,             /* display off */
        0xD5, 0x80,       /* clock divide */
        0xA8, 0x3F,       /* multiplex 64 */
        0xD3, 0x00,       /* display offset 0 */
        0x40,             /* start line 0 */
        0xAD, 0x8B,       /* SH1106 charge pump on */
        0xA1,             /* segment remap */
        0xC8,             /* COM scan reverse */
        0xDA, 0x12,       /* COM pins */
        0x81, 0xCF,       /* contrast */
        0xD9, 0xF1,       /* pre-charge */
        0xDB, 0x40,       /* VCOMH */
        0xA4,             /* display from RAM */
        0xA6,             /* normal (not inverted) */
        0xAF,             /* display on */
    };
    for (unsigned i = 0; i < sizeof(init); i++)
        write_cmd(init[i]);
}

static void oled_flush(void)
{
    for (int page = 0; page < 8; page++) {
        write_cmd(0xB0 + page);
        write_cmd(0x02); /* SH1106 column offset: visible area starts at 2 */
        write_cmd(0x10);
        write_data(fb + page * 128, 128);
    }
}

/* ---- tiny 5x7 font (columns, LSB = top) ---- */
struct glyph { char c; uint8_t col[5]; };
static const struct glyph font[] = {
    {' ', {0x00, 0x00, 0x00, 0x00, 0x00}},
    {'(', {0x00, 0x1C, 0x22, 0x41, 0x00}},
    {')', {0x00, 0x41, 0x22, 0x1C, 0x00}},
    {'+', {0x08, 0x08, 0x3E, 0x08, 0x08}},
    {'-', {0x08, 0x08, 0x08, 0x08, 0x08}},
    {'.', {0x00, 0x60, 0x60, 0x00, 0x00}},
    {'0', {0x3E, 0x51, 0x49, 0x45, 0x3E}},
    {'1', {0x00, 0x42, 0x7F, 0x40, 0x00}},
    {'2', {0x42, 0x61, 0x51, 0x49, 0x46}},
    {'3', {0x21, 0x41, 0x45, 0x4B, 0x31}},
    {'4', {0x18, 0x14, 0x12, 0x7F, 0x10}},
    {'5', {0x27, 0x45, 0x45, 0x45, 0x39}},
    {'6', {0x3C, 0x4A, 0x49, 0x49, 0x30}},
    {'7', {0x01, 0x71, 0x09, 0x05, 0x03}},
    {'8', {0x36, 0x49, 0x49, 0x49, 0x36}},
    {'9', {0x06, 0x49, 0x49, 0x29, 0x1E}},
    {':', {0x00, 0x36, 0x36, 0x00, 0x00}},
    {'=', {0x14, 0x14, 0x14, 0x14, 0x14}},
    {'>', {0x00, 0x41, 0x22, 0x14, 0x08}},
    {'B', {0x7F, 0x49, 0x49, 0x49, 0x36}},
    {'E', {0x7F, 0x49, 0x49, 0x49, 0x41}},
    {'L', {0x7F, 0x40, 0x40, 0x40, 0x40}},
    {'M', {0x7F, 0x02, 0x0C, 0x02, 0x7F}},
    {'P', {0x7F, 0x09, 0x09, 0x09, 0x06}},
    {'R', {0x7F, 0x09, 0x19, 0x29, 0x46}},
    {'T', {0x01, 0x01, 0x7F, 0x01, 0x01}},
    {'U', {0x3F, 0x40, 0x40, 0x40, 0x3F}},
    {'a', {0x20, 0x54, 0x54, 0x54, 0x78}},
    {'b', {0x7F, 0x48, 0x44, 0x44, 0x38}},
    {'c', {0x38, 0x44, 0x44, 0x44, 0x20}},
    {'d', {0x38, 0x44, 0x44, 0x48, 0x7F}},
    {'e', {0x38, 0x54, 0x54, 0x54, 0x18}},
    {'f', {0x08, 0x7E, 0x09, 0x01, 0x02}},
    {'g', {0x0C, 0x52, 0x52, 0x52, 0x3E}},
    {'i', {0x00, 0x44, 0x7D, 0x40, 0x00}},
    {'k', {0x7F, 0x10, 0x28, 0x44, 0x00}},
    {'q', {0x38, 0x44, 0x44, 0x48, 0x7A}},
    {'v', {0x1C, 0x20, 0x40, 0x20, 0x1C}},
    {'h', {0x7F, 0x08, 0x04, 0x04, 0x78}},
    {'j', {0x20, 0x40, 0x44, 0x3D, 0x00}},
    {'m', {0x7C, 0x04, 0x18, 0x04, 0x78}},
    {'w', {0x3C, 0x40, 0x30, 0x40, 0x3C}},
    {'x', {0x44, 0x28, 0x10, 0x28, 0x44}},
    {'z', {0x44, 0x64, 0x54, 0x4C, 0x44}},
    {'#', {0x14, 0x7F, 0x14, 0x7F, 0x14}},
    {'<', {0x08, 0x14, 0x22, 0x41, 0x00}},
    {'*', {0x14, 0x08, 0x3E, 0x08, 0x14}},
    {'/', {0x20, 0x10, 0x08, 0x04, 0x02}},
    {'\'', {0x00, 0x05, 0x03, 0x00, 0x00}},
    {'!', {0x00, 0x00, 0x5F, 0x00, 0x00}},
    {'?', {0x02, 0x01, 0x51, 0x09, 0x06}},
    {'l', {0x00, 0x41, 0x7F, 0x40, 0x00}},
    {'n', {0x7C, 0x08, 0x04, 0x04, 0x78}},
    {'o', {0x38, 0x44, 0x44, 0x44, 0x38}},
    {'p', {0x7C, 0x14, 0x14, 0x14, 0x08}},
    {'r', {0x7C, 0x08, 0x04, 0x04, 0x08}},
    {'s', {0x48, 0x54, 0x54, 0x54, 0x20}},
    {'t', {0x04, 0x3F, 0x44, 0x40, 0x20}},
    {'u', {0x3C, 0x40, 0x40, 0x20, 0x7C}},
    {'y', {0x0C, 0x50, 0x50, 0x50, 0x3C}},
};

static const uint8_t *glyph_for(char c)
{
    for (unsigned i = 0; i < sizeof(font) / sizeof(font[0]); i++)
        if (font[i].c == c)
            return font[i].col;
    return font[0].col;
}

static void fb_pixel(int x, int y, int on)
{
    if (x < 0 || x >= 128 || y < 0 || y >= 64)
        return;
    if (on)
        fb[(y / 8) * 128 + x] |= (1u << (y % 8));
    else
        fb[(y / 8) * 128 + x] &= ~(1u << (y % 8));
}

static void draw_text(int x, int y, const char *s, int scale)
{
    for (; *s; s++) {
        const uint8_t *g = glyph_for(*s);
        for (int col = 0; col < 5; col++)
            for (int row = 0; row < 7; row++)
                if ((g[col] >> row) & 1)
                    for (int dx = 0; dx < scale; dx++)
                        for (int dy = 0; dy < scale; dy++)
                            fb_pixel(x + col * scale + dx,
                                     y + row * scale + dy, 1);
        x += 6 * scale;
    }
}

void macropad_console_init(void);

void macropad_splash(void)
{
    gpio_init(PIN_LED);
    gpio_set_dir(PIN_LED, GPIO_OUT);
    gpio_put(PIN_LED, 1);

    oled_init();
    for (unsigned i = 0; i < sizeof(fb); i++)
        fb[i] = 0;
    oled_flush();
    macropad_console_init();
}

/* ---- OLED console --------------------------------------------------
 * A 21x5 character console mirroring everything the interpreter
 * prints (its putc_ feeds both USB stdio and this). The bottom two
 * lines of the display stay reserved for the pad composer status.
 */
#define CON_COLS 21
#define CON_ROWS 5
static char con_grid[CON_ROWS][CON_COLS];
static int con_cx, con_cy;
static int con_dirty;
static int con_ready; /* set once the OLED is initialized */

void macropad_console_init(void)
{
    for (int r = 0; r < CON_ROWS; r++)
        for (int c = 0; c < CON_COLS; c++)
            con_grid[r][c] = ' ';
    con_cx = con_cy = 0;
    con_dirty = 1;
    con_ready = 1;
}

static void con_scroll(void)
{
    for (int r = 0; r < CON_ROWS - 1; r++)
        for (int c = 0; c < CON_COLS; c++)
            con_grid[r][c] = con_grid[r + 1][c];
    for (int c = 0; c < CON_COLS; c++)
        con_grid[CON_ROWS - 1][c] = ' ';
}

static void con_newline(void)
{
    con_cx = 0;
    if (con_cy < CON_ROWS - 1)
        con_cy++;
    else
        con_scroll();
}

void macropad_console_flush(void)
{
    if (!con_dirty || !con_ready)
        return;
    con_dirty = 0;
    for (int r = 0; r < CON_ROWS; r++) {
        char line[CON_COLS + 1];
        for (int c = 0; c < CON_COLS; c++)
            line[c] = con_grid[r][c];
        line[CON_COLS] = 0;
        for (int x = 0; x < 128; x++)
            for (int y = r * 8; y < r * 8 + 8; y++)
                fb_pixel(x, y, 0);
        draw_text(2, r * 8, line, 1);
    }
    for (int page = 0; page < 5; page++) {
        write_cmd(0xB0 + page);
        write_cmd(0x02);
        write_cmd(0x10);
        write_data(fb + page * 128, 128);
    }
}

void macropad_console_putc(int c)
{
    if (c == '\r')
        return;
    if (c == '\n') {
        con_newline();
        con_dirty = 1;
        macropad_console_flush();
        return;
    }
    if (c == '\b') {
        if (con_cx > 0)
            con_cx--;
        con_dirty = 1;
        return;
    }
    if (c < 32 || c >= 127)
        return;
    con_grid[con_cy][con_cx] = (char)c;
    if (++con_cx >= CON_COLS)
        con_newline();
    con_dirty = 1;
}

/* ---- Keys + encoder ------------------------------------------------
 * KEY1..KEY12 are GP1..GP12, the encoder push is GP0, rotation is
 * GP17 (A) / GP18 (B); everything is active-low with pull-ups.
 * Rotation is decoded in an edge IRQ into whole detents.
 */
#define PIN_ENC_PUSH 0
#define PIN_ENC_A 17
#define PIN_ENC_B 18

static volatile int enc_pos;
static volatile int enc_rem;
static volatile int enc_state;

static void enc_irq(uint gpio, uint32_t events)
{
    (void)gpio; (void)events;
    static const int dt[16] = { 0, -1, 1, 0,
                                1, 0, 0, -1,
                                -1, 0, 0, 1,
                                0, 1, -1, 0 };
    int cur = (gpio_get(PIN_ENC_A) ? 2 : 0) | (gpio_get(PIN_ENC_B) ? 1 : 0);
    int d = dt[(enc_state << 2) | cur];
    enc_state = cur;
    if (d == 0)
        return;
    enc_rem += d;
    if (enc_rem >= 4) { enc_pos++; enc_rem -= 4; }
    else if (enc_rem <= -4) { enc_pos--; enc_rem += 4; }
}

void macropad_keys_init(void)
{
    for (int p = 0; p <= 12; p++) {
        gpio_init(p);
        gpio_set_dir(p, GPIO_IN);
        gpio_pull_up(p);
    }
    gpio_init(PIN_ENC_A);
    gpio_set_dir(PIN_ENC_A, GPIO_IN);
    gpio_pull_up(PIN_ENC_A);
    gpio_init(PIN_ENC_B);
    gpio_set_dir(PIN_ENC_B, GPIO_IN);
    gpio_pull_up(PIN_ENC_B);
    enc_state = (gpio_get(PIN_ENC_A) ? 2 : 0) | (gpio_get(PIN_ENC_B) ? 1 : 0);
    gpio_set_irq_enabled_with_callback(PIN_ENC_A,
        GPIO_IRQ_EDGE_RISE | GPIO_IRQ_EDGE_FALL, true, &enc_irq);
    gpio_set_irq_enabled(PIN_ENC_B,
        GPIO_IRQ_EDGE_RISE | GPIO_IRQ_EDGE_FALL, true);
}

/* bit 0..11 = KEY1..KEY12, bit 12 = encoder push; 1 = pressed */
int macropad_keybits(void)
{
    int bits = 0;
    for (int k = 1; k <= 12; k++)
        if (!gpio_get(k))
            bits |= 1 << (k - 1);
    if (!gpio_get(PIN_ENC_PUSH))
        bits |= 1 << 12;
    return bits;
}

int macropad_encpos(void)
{
    return enc_pos;
}

/* ---- Expression composer ------------------------------------------
 * The pad can type into the REPL: the encoder scrolls a palette of
 * tokens, its push appends the selected token to a compose line,
 * KEY11 erases a character, KEY12 submits the line. KEY1..KEY10 are
 * quick tokens. Submitted text reaches the interpreter through
 * macropad_getc_poll(), which getc_ consults before USB input.
 */
void macropad_draw_status(void);

static const char *palette[] = {
    "(", ")", "define ", "lambda ", "if ", "let ", "car ", "cdr ",
    "cons ", "list ", "print ", "quote ", "+ ", "- ", "* ", "= ",
    "< ", "> ", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    " ", "x", "y", "n", "a", "b", "fib", "keys", "enc", "save"
};
#define PALETTE_N (int)(sizeof(palette) / sizeof(palette[0]))
static const char *quick_tokens[10] = {
    "(", ")", "+ ", "- ", "* ",
    "define ", "lambda ", "car ", "cdr ", "cons "
};
static int pal_idx;
static char compose[96];
static int compose_len;
static char inq[128];
static int inq_len, inq_pos;
static int prev_keybits;
static int prev_encpos;
static int poll_count;

static void compose_add(const char *s)
{
    while (*s && compose_len < (int)sizeof(compose) - 1)
        compose[compose_len++] = *s++;
    compose[compose_len] = 0;
}

static void compose_submit(void)
{
    if (inq_pos < inq_len)
        return; /* previous line still draining */
    int i;
    for (i = 0; i < compose_len; i++)
        inq[i] = compose[i];
    inq_len = compose_len;
    inq[inq_len++] = '\n';
    inq_pos = 0;
    compose_len = 0;
    compose[0] = 0;
}

int macropad_getc_poll(void)
{
    poll_count++;
    if (poll_count % 10 == 0)
        macropad_idle_tick();
    int kb = macropad_keybits();
    int pressed = kb & ~prev_keybits;
    prev_keybits = kb;
    int ep = macropad_encpos();
    if (ep != prev_encpos) {
        pal_idx = (pal_idx + (ep - prev_encpos)) % PALETTE_N;
        if (pal_idx < 0)
            pal_idx += PALETTE_N;
        prev_encpos = ep;
        macropad_draw_status();
    }
    if (pressed) {
        if (pressed & (1 << 12))
            compose_add(palette[pal_idx]);
        for (int k = 0; k < 10; k++)
            if (pressed & (1 << k))
                compose_add(quick_tokens[k]);
        if ((pressed & (1 << 10)) && compose_len > 0)
            compose[--compose_len] = 0;
        if (pressed & (1 << 11))
            compose_submit();
        macropad_draw_status();
    }
    if (inq_pos < inq_len)
        return (unsigned char)inq[inq_pos++];
    return -1;
}

/* Status rendering for the two bottom lines: the palette selection
 * and the compose line being typed on the pad. Redrawn on every pad
 * event and periodically from the idle tick.
 */
static int tick_count;

void macropad_draw_status(void)
{
    char buf[32];
    snprintf(buf, sizeof(buf), "sel:%s", palette[pal_idx]);
    for (int x = 8; x < 122; x++)
        for (int y = 42; y < 52; y++)
            fb_pixel(x, y, 0);
    draw_text(10, 44, buf, 1);
    int start = compose_len > 17 ? compose_len - 17 : 0;
    snprintf(buf, sizeof(buf), "in:%s", compose + start);
    for (int x = 8; x < 122; x++)
        for (int y = 52; y < 62; y++)
            fb_pixel(x, y, 0);
    draw_text(10, 54, buf, 1);
    /* flush pages 5..7 (y 40..63) */
    for (int page = 5; page < 8; page++) {
        write_cmd(0xB0 + page);
        write_cmd(0x02);
        write_cmd(0x10);
        write_data(fb + page * 128, 128);
    }
}

/* Called ~every 100 ms while the REPL waits for input (via the
 * getc_ poll). Blinks the board LED and refreshes the status area:
 * the tick count advancing means the CPU is alive in the REPL loop;
 * "usb:1" means a host has opened the port.
 */
void macropad_idle_tick(void)
{
    tick_count++;
    gpio_put(PIN_LED, (tick_count >> 3) & 1);
    macropad_console_flush();
    if (tick_count % 5 == 0)
        macropad_draw_status();
}
