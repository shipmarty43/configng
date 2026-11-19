// SPDX-License-Identifier: GPL-2.0-only
/*
 * Allwinner H618 native CVBS TVE0 + DAC0.
 * Register programming derived from Allwinner de_tve_sun8iw11.c
 * Copyright (C) 2015 Allwinnertech, z.q <zengqi@allwinnertech.com>
 */

#include <linux/errno.h>
#include <linux/regmap.h>

#include "h618-tve.h"

#define TOP_DAC_MAP	0x020
#define TOP_DAC_CFG0	0x028
#define TOP_DAC_CFG1	0x02c
#define TOP_DAC_CFG2	0x030
#define DAC_ENABLE	1U
#define DAC_TRIM_MAX	0x3ff
#define DAC_TRIM_DEFAULT 625

#define TVE_CTRL	0x000
#define TVE_ENABLE	1U
#define TVE_GATE_DIS	(1U << 31)
#define TVE_MODE	0x004
#define TVE_DAC_TYPE	0x008
#define TVE_PORCH	0x014
#define TVE_RESYNC	0x130
#define TVE_DEFLICKER	0x380

/* Multi-write regmaps may coalesce accesses. The vendor program relies on
 * individual ordered writes, including several to the same register.
 */
struct mode_reg {
	unsigned int reg;
	unsigned int pal;
	unsigned int ntsc;
};

static const struct mode_reg mode_regs[] = {
	{ 0x004, 0x07060001, 0x07060000 },
	{ 0x00c, 0x02004000, 0x02004000 },
	{ 0x010, 0x2a098acb, 0x21f07c1f },
	{ 0x014, 0x008a0018, 0x00760020 },
	{ 0x018, 0x00000016, 0x00000016 },
	{ 0x01c, 0x00160271, 0x0016020d },
	{ 0x020, 0x00fc00fc, 0x00f000f0 },
	{ 0x100, 0x00000000, 0x00000001 },
	{ 0x104, 0x00000001, 0x00000000 },
	{ 0x108, 0x00000005, 0x00000002 },
	{ 0x10c, 0x00002929, 0x0000004f },
	{ 0x110, 0x00000000, 0x00000000 },
	{ 0x114, 0x0016447e, 0x0016447e },
	{ 0x118, 0x0000a8a8, 0x0000a0a0 },
	{ 0x11c, 0x001000fc, 0x001000f0 },
	{ 0x124, 0x000005a0, 0x000005a0 },
	{ 0x128, 0x00010000, 0x00000000 },
	{ 0x12c, 0x00000101, 0x00000101 },
	{ 0x130, 0x200f000c, 0x200f000c },
	{ 0x134, 0x00000000, 0x00000000 },
	{ 0x138, 0x00000000, 0x00000000 },
	{ 0x13c, 0x00000000, 0x00000001 },
};

int h618_tve_decode_trim(const u8 *cell, size_t len, u16 *trim)
{
	unsigned int field;

	if (!cell || len < 4 || !trim)
		return -EINVAL;
	field = cell[2] | ((unsigned int)cell[3] << 8);
	if (field > DAC_TRIM_MAX)
		return -ERANGE;
	*trim = field ? field : DAC_TRIM_DEFAULT;
	return 0;
}

static int h618_tve_program_mode(struct regmap *enc, enum h618_cvbs_mode mode)
{
	bool pal = mode == H618_CVBS_PAL;
	unsigned int i, sync;
	int ret;

	for (i = 0; i < ARRAY_SIZE(mode_regs); i++) {
		const struct mode_reg *r = &mode_regs[i];

		ret = regmap_write(enc, r->reg, pal ? r->pal : r->ntsc);
		if (ret)
			return ret;
	}

	/* The BSP writes the noise-reduction register only in the PAL case. */
	if (pal) {
		ret = regmap_write(enc, 0x3a0, 0x00030001);
		if (ret)
			return ret;
	}
	ret = regmap_write(enc, 0x0f8, 0x00000200);
	if (ret)
		return ret;
	ret = regmap_write(enc, 0x120, 0x01e80320);
	if (ret)
		return ret;
	ret = regmap_write(enc, TVE_DEFLICKER, 0);
	if (ret)
		return ret;
	ret = regmap_write_bits(enc, TVE_MODE, 1U << 16, 1U << 16);
	if (ret)
		return ret;
	ret = regmap_write(enc, TVE_CTRL, 0x00300000);
	if (ret)
		return ret;
	ret = regmap_write_bits(enc, TVE_CTRL, TVE_ENABLE, 0);
	if (ret)
		return ret;
	sync = pal ? 0x2005000a : 0x20050368;
	ret = regmap_write(enc, TVE_RESYNC, sync);
	if (ret)
		return ret;
	if (pal) {
		ret = regmap_write(enc, TVE_PORCH, 0x00820020);
		if (ret)
			return ret;
	}
	ret = regmap_write(enc, TVE_RESYNC, pal ? 0x20050013 : 0x20050364);
	if (ret)
		return ret;
	return regmap_write(enc, TVE_DEFLICKER, 0x300);
}

int h618_tve_stop(const struct h618_tve *tve)
{
	int gate, output, dac;

	/* Attempt every mute operation even if an earlier write failed. */
	gate = regmap_write_bits(tve->encoder, TVE_CTRL, TVE_GATE_DIS, 0);
	output = regmap_write_bits(tve->encoder, TVE_CTRL, TVE_ENABLE, 0);
	dac = regmap_write_bits(tve->top, TOP_DAC_CFG0, DAC_ENABLE, 0);
	return gate ? gate : (output ? output : dac);
}

int h618_tve_start(const struct h618_tve *tve, enum h618_cvbs_mode mode,
		   u16 trim)
{
	int ret;
	unsigned int sync;

	if (mode != H618_CVBS_PAL && mode != H618_CVBS_NTSC)
		return -EINVAL;
	if (!trim || trim > DAC_TRIM_MAX)
		return -ERANGE;

	ret = regmap_write(tve->top, TOP_DAC_MAP, 1); /* TVE0 -> DAC0 */
	if (ret)
		goto mute;
	ret = regmap_write(tve->top, TOP_DAC_CFG1, 0x023a);
	if (ret)
		goto mute;
	ret = regmap_write(tve->top, TOP_DAC_CFG2, 0x0010);
	if (ret)
		goto mute;
	ret = regmap_write(tve->top, TOP_DAC_CFG0, 0x80004200U | ((u32)trim << 16));
	if (ret)
		goto mute;
	ret = regmap_write(tve->encoder, TVE_DAC_TYPE, 0); /* CVBS */
	if (ret)
		goto mute;
	ret = h618_tve_program_mode(tve->encoder, mode);
	if (ret)
		goto mute;

	ret = regmap_write_bits(tve->top, TOP_DAC_CFG0, DAC_ENABLE, DAC_ENABLE);
	if (ret)
		goto mute;
	/* Android's default tve_adjust_resync(-1, -1) latches the mode value. */
	ret = regmap_read(tve->encoder, TVE_RESYNC, &sync);
	if (ret)
		goto mute;
	ret = regmap_write(tve->encoder, TVE_RESYNC, sync);
	if (ret)
		goto mute;
	ret = regmap_write_bits(tve->encoder, TVE_CTRL, TVE_GATE_DIS, TVE_GATE_DIS);
	if (ret)
		goto mute;
	ret = regmap_write_bits(tve->encoder, TVE_CTRL, TVE_ENABLE, TVE_ENABLE);
	if (!ret)
		return 0;
mute:
	h618_tve_stop(tve);
	return ret;
}
