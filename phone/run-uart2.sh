#!/data/data/com.termux/files/usr/bin/sh
exec python3 /data/data/com.termux/files/home/uart_listen2.py "$@" > /data/data/com.termux/files/home/uart_listen2.log 2>&1
