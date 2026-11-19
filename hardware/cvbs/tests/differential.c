// SPDX-License-Identifier: GPL-2.0-only
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <linux/regmap.h>
#include "../h618-tve.h"

static struct regmap top, enc;
static const struct h618_tve tve = { .top = &top, .encoder = &enc };

struct access {
	unsigned int is_top, write, offset, value;
};

static struct access trace[128], reference[128];
static size_t count, fail_at;

static int record(struct regmap *map, bool write, unsigned int offset, unsigned int value)
{
	assert((map == &top || map == &enc) && !(offset % 4) && offset < map->limit);
	assert(count < ARRAY_SIZE(trace));
	trace[count++] = (struct access){ map == &top, write, offset, value };
	return count == fail_at ? -EIO : 0;
}

int regmap_write(struct regmap *map, unsigned int reg, unsigned int value)
{
	int ret = record(map, true, reg, value);
	if (!ret)
		map->values[reg / 4] = value;
	return ret;
}

int regmap_read(struct regmap *map, unsigned int reg, unsigned int *value)
{
	assert(reg < map->limit);
	*value = map->values[reg / 4];
	return record(map, false, reg, *value);
}

int regmap_write_bits(struct regmap *map, unsigned int reg, unsigned int mask, unsigned int value)
{
	unsigned int prev;
	int ret = regmap_read(map, reg, &prev);
	return ret ? ret : regmap_write(map, reg, (prev & ~mask) | (value & mask));
}

static void reset(void)
{
	top = (struct regmap){ .limit = 0x100 };
	enc = (struct regmap){ .limit = 0x3fc };
	count = fail_at = 0;
}

static unsigned int vendor_read(struct regmap *map, unsigned int reg)
{
	unsigned int value;
	assert(regmap_read(map, reg, &value) == 0);
	return value;
}

#define TVE_WUINT32(sel, r, v) regmap_write(&enc, r, v)
#define TVE_RUINT32(sel, r) vendor_read(&enc, r)
#define TVE_INIT_BIT(sel, r, clr, set) TVE_WUINT32(sel, r, (TVE_RUINT32(sel, r) & ~(clr)) | (set))
#define TVE_SET_BIT(sel, r, bit) TVE_WUINT32(sel, r, TVE_RUINT32(sel, r) | (bit))
#define TVE_CLR_BIT(sel, r, bit) TVE_WUINT32(sel, r, TVE_RUINT32(sel, r) & ~(bit))
#define TVE_TOP_WUINT32(r, v) regmap_write(&top, r, v)
#define TVE_TOP_SET_BIT(r, bit) TVE_TOP_WUINT32(r, vendor_read(&top, r) | (bit))
#define TVE_TOP_CLR_BIT(r, bit) TVE_TOP_WUINT32(r, vendor_read(&top, r) & ~(bit))

#include "vendor-oracle.inc"

static void compare_mode(enum h618_cvbs_mode mode, unsigned int trim)
{
	unsigned int dac = 0, type = 0;
	s32 offset = 0;
	size_t start_count, stop_count, i;

	reset();
	tve_low_init(0, &dac, &trim, &offset, &type, 1);
	tve_low_set_tv_mode(0, mode == H618_CVBS_PAL ? DISP_TV_MOD_PAL : DISP_TV_MOD_NTSC, &trim);
	tve_low_dac_enable(0);
	tve_adjust_resync(0, -1, -1);
	tve_low_open(0);
	start_count = count;
	tve_low_close(0);
	tve_low_dac_disable(0);
	stop_count = count;
	memcpy(reference, trace, sizeof(reference));

	reset();
	assert(h618_tve_start(&tve, mode, trim) == 0);
	assert(count == start_count);
	assert(h618_tve_stop(&tve) == 0 && count == stop_count);
	assert(memcmp(trace, reference, count * sizeof(trace[0])) == 0);

	/* Fail every individual read/write once, including the last enable. */
	for (i = 1; i <= start_count; i++) {
		reset();
		fail_at = i;
		assert(h618_tve_start(&tve, mode, trim) == -EIO);
		assert(!(top.values[0x28 / 4] & 1));
		assert(!(enc.values[0] & 0x80000001));
	}
	printf("%s, trim=%u: %zu start + %zu stop accesses match; %zu injected failures\n",
	       mode == H618_CVBS_PAL ? "PAL" : "NTSC", trim, start_count,
	       stop_count - start_count, start_count);
}

int main(void)
{
	u8 cell[8] = { 0xfe, 0xdc, 0x23, 0x01, 0xff, 0xff, 0xff, 0xff };
	u16 trim = 0;
	assert(h618_tve_decode_trim(cell, sizeof(cell), &trim) == 0 && trim == 0x123);
	cell[2] = cell[3] = 0;
	assert(h618_tve_decode_trim(cell, sizeof(cell), &trim) == 0 && trim == 625);
	cell[3] = 4;
	assert(h618_tve_decode_trim(cell, sizeof(cell), &trim) == -ERANGE);
	assert(h618_tve_decode_trim(cell, 3, &trim) == -EINVAL);
	reset();
	assert(h618_tve_start(&tve, 99, 625) == -EINVAL);
	assert(h618_tve_start(&tve, H618_CVBS_PAL, 1024) == -ERANGE);
	assert(h618_tve_start(&tve, H618_CVBS_PAL, 0) == -ERANGE);
	assert(count == 0);
	compare_mode(H618_CVBS_PAL, 625);
	compare_mode(H618_CVBS_NTSC, 625);
	compare_mode(H618_CVBS_PAL, 1);
	compare_mode(H618_CVBS_NTSC, 1023);
}
