#!/bin/sh
exec scp -i /home/hatch/.ssh/id_ed25519 -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=no \
  -o "ProxyCommand=python3 /tmp/ts-proxy-connect.py %h %p" \
  -P 8022 "$@"
