#!/bin/sh

cd /tmp

while true; do
    TEXINPUTS=$TEXINPUTS:/srv max_print_line=2147483647 openout_any=a xelatex -8bit --shell-escape /srv/cleanup.tex

    sleep 5m
done
