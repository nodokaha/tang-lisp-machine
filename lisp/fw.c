#define UART_DATA (*(volatile unsigned int *)0x02000000u)
#define UART_STAT (*(volatile unsigned int *)0x02000004u)

static void putc_(char c)
{
    while (UART_STAT & 2u) { }
    UART_DATA = (unsigned int)(unsigned char)c;
}

static void puts_(const char *s)
{
    while (*s) putc_(*s++);
}

static int getc_(void)
{
    while (!(UART_STAT & 1u)) { }
    return (int)(UART_DATA & 0xFFu);
}

static const char BANNER[] =
    "\nTangLisp embryo: PicoRV32 alive. send '?' for banner, echo is on.\n> ";

int main(void)
{
    puts_(BANNER);
    for (;;) {
        int c = getc_();
        if (c == '?') {
            puts_(BANNER);
            continue;
        }
        putc_((char)c);
        if (c == '\n' || c == '\r') puts_("\n> ");
    }
}
