NC = nekoc
VM = neko

CC = gcc
LIBARGS = -shared -fpic -lneko

src_files = db imc utils parser responder create fetch update

.PHONY: all

all: $(src_files:=.n)

run: all imc.n
	$(VM) imc.n

socks: all
	socat -T 20 TCP6-LISTEN:8080,reuseaddr,fork EXEC:'neko ./imc.n',setsid

%.n: %.neko
	$(NC) $?

buildlibs: file.ndll sqlite.ndll date.ndll

file.ndll: ./filelib/file.c
	$(CC) $(LIBARGS) -o $@ $?

sqlite.ndll: ./sqlib/sqlite-amalgamation-3530100/sqlite3.c ./sqlib/sqlite.c 
	$(CC) $(LIBARGS) -o $@ $?

date.ndll: ./datelib/date.c
	$(CC) $(LIBARGS) -o $@ $?

clean:
	rm -f *.n db.db 
