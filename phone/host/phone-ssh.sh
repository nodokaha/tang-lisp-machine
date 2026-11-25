#!/bin/sh
exec ssh -i /home/hatch/.ssh/id_ed25519 -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=no \
  -o "ProxyCommand=python3 /tmp/ts-proxy-connect.py %h %p" \
  -p 8022 u0_a483@100.120.108.8 "$@"
