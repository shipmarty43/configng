obj-m += dfr0528_battery.o
KDIR ?= /lib/modules/$(shell uname -r)/build
all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules
clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
host-test:
	@set -eu; tmp=$$(mktemp); trap 'rm -f "$$tmp"' EXIT; \
	$(CC) -Wall -Wextra -Werror -fsanitize=address,undefined -o "$$tmp" test_read.c; "$$tmp"
