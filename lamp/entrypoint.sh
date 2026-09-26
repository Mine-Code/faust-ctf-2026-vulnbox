#!/bin/sh
# Per-connection XeLaTeX runner for the "lamp" service.
#
# Each connection gets its own socat -> entrypoint.sh -> xelatex process tree.
# Without resource limits a flood of connections spawns many xelatex processes;
# since one request peaks around 580 MiB of virtual address space, that exhausts
# host RAM and triggers the kernel OOM killer (which in turn wedges / reboots the
# vulnbox).  The limits below make a single request fail fast instead:
#
#   -c 0        no core dumps (they are huge and useless here)
#   -v 1048576  virtual address space cap: 1 GiB (normal peak ~580 MiB)
#   -m 786432   resident set cap: 768 MiB
#   -t 30       CPU seconds: hard-kill a wedged/looping run
#   -f 65536    max file size: 32 MiB (no giant output files)
#
# socat's own concurrency limit (max-children) is set where socat is started
# (see Dockerfile CMD); ulimit cannot bound the *number* of processes.
ulimit -c 0
ulimit -v 1048576
ulimit -m 786432
ulimit -t 30
ulimit -f 65536 2>/dev/null || true

(export TMPDIR=$(mktemp -d); cd "$TMPDIR"; TEXINPUTS=$TEXINPUTS:/srv max_print_line=2147483647 openout_any=a stdbuf -o0 xelatex -8bit --shell-escape /srv/main.tex; rm -r "$TMPDIR") | stdbuf -o0 tail -n +8
