// SPDX-License-Identifier: GPL-2.0-only
/* Inspect and re-request lines on the in-memory test chip. */
#include <errno.h>
#include <fcntl.h>
#include <linux/gpio.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

static int failure(int line)
{
	fprintf(stderr, "GPIO v2 check failed at %d: %s\n", line, strerror(errno));
	return 1;
}

static int check(int fd)
{
	struct gpio_v2_line_info info = { .offset = 0 };
	struct gpio_v2_line_request req = {
		.num_lines = 1, .consumer = "header-qa",
		.config = { .flags = GPIO_V2_LINE_FLAG_INPUT, .num_attrs = 1,
			.attrs = {{ .attr = { .id = GPIO_V2_LINE_ATTR_ID_DEBOUNCE,
				.debounce_period_us = 244 }, .mask = 1 }} },
	};
	unsigned int i;
	int seen = 0;

	if (ioctl(fd, GPIO_V2_GET_LINEINFO_IOCTL, &info) || info.flags & GPIO_V2_LINE_FLAG_USED)
		return failure(__LINE__);
	if (ioctl(fd, GPIO_V2_GET_LINE_IOCTL, &req))
		return failure(__LINE__);
	if (ioctl(fd, GPIO_V2_GET_LINEINFO_IOCTL, &info) || strcmp(info.consumer, "header-qa"))
		return failure(__LINE__);
	for (i = 0; i < info.num_attrs; i++)
		if (info.attrs[i].id == GPIO_V2_LINE_ATTR_ID_DEBOUNCE)
			seen = info.attrs[i].debounce_period_us == 244;
	if (!seen || close(req.fd))
		return failure(__LINE__);
	memset(&req, 0, sizeof(req));
	req.num_lines = 1;
	req.config.flags = GPIO_V2_LINE_FLAG_INPUT;
	req.offsets[0] = 1;
	if (!ioctl(fd, GPIO_V2_GET_LINE_IOCTL, &req) || errno != EBUSY)
		return failure(__LINE__);
	req.offsets[0] = 2;
	req.config.num_attrs = 1;
	req.config.attrs[0].mask = 1;
	req.config.attrs[0].attr.id = GPIO_V2_LINE_ATTR_ID_DEBOUNCE;
	req.config.attrs[0].attr.debounce_period_us = 244;
	req.config.flags |= GPIO_V2_LINE_FLAG_EDGE_RISING;
	/* Chip has neither hardware debounce on line 2 nor an IRQ for software fallback. */
	if (!ioctl(fd, GPIO_V2_GET_LINE_IOCTL, &req))
		return failure(__LINE__);
	return errno == ENXIO || errno == ENODEV ? 0 : failure(__LINE__);
}

int main(int argc, char **argv)
{
	for (int i = 1; i < argc; i++) {
		struct gpiochip_info chip = {};
		int fd = open(argv[i], O_RDONLY | O_CLOEXEC);
		if (fd < 0)
			return failure(__LINE__);
		if (!ioctl(fd, GPIO_GET_CHIPINFO_IOCTL, &chip) && !strcmp(chip.label, "header-gpio-double"))
			return check(fd);
		close(fd);
	}
	return failure(__LINE__);
}
