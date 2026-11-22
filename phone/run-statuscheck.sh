#!/data/data/com.termux/files/usr/bin/sh
exec python3 /data/data/com.termux/files/home/status_check.py "$@" > /data/data/com.termux/files/home/status_check.log 2>&1
