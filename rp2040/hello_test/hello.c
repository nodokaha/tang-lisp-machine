#include <stdio.h>
#include "pico/stdlib.h"
#include "pico/stdio_usb.h"

int main(void)
{
    stdio_init_all();
    gpio_init(13);
    gpio_set_dir(13, GPIO_OUT);
    int n = 0;
    for (;;) {
        gpio_put(13, n & 1);
        printf("hello %d usb_connected=%d\n", n++,
               stdio_usb_connected() ? 1 : 0);
        sleep_ms(1000);
    }
}
