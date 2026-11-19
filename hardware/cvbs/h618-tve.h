/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef H618_TVE_H
#define H618_TVE_H

#include <linux/types.h>

struct regmap;

enum h618_cvbs_mode {
	H618_CVBS_PAL,
	H618_CVBS_NTSC,
};

/* Both little-endian 32-bit, stride-4 MMIO regmaps must use REGCACHE_NONE. */
struct h618_tve {
	struct regmap *top;
	struct regmap *encoder;
};

/* Android tvout cell starts at SID+0x2c. Use the upper half of LE word 0. */
int h618_tve_decode_trim(const u8 *cell, size_t len, u16 *trim);

/* Caller serializes modesets, owns clocks/resets, starts from hardware reset
 * and supplies a ready TCON input. On write errors the caller must reset TVE
 * before releasing clocks or retrying (including switching standards).
 */
int h618_tve_start(const struct h618_tve *tve, enum h618_cvbs_mode mode,
		   u16 trim);
int h618_tve_stop(const struct h618_tve *tve);

#endif
