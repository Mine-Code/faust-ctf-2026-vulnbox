#!/bin/sh

(export TMPDIR=$(mktemp -d); cd $TMPDIR; TEXINPUTS=$TEXINPUTS:/srv max_print_line=2147483647 openout_any=a stdbuf -o0 xelatex -8bit --shell-escape /srv/main.tex; rm -r $TMPDIR) | stdbuf -o0 tail -n +8 
