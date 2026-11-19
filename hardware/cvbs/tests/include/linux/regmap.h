/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef TEST_LINUX_REGMAP_H
#define TEST_LINUX_REGMAP_H
#include <linux/types.h>
#define ARRAY_SIZE(array) (sizeof(array) / sizeof((array)[0]))
struct regmap {
	unsigned int limit;
	unsigned int values[256];
};
int regmap_write(struct regmap *, unsigned int reg, unsigned int value);
int regmap_read(struct regmap *, unsigned int reg, unsigned int *value);
int regmap_write_bits(struct regmap *, unsigned int reg, unsigned int mask,
		      unsigned int value);
#endif
