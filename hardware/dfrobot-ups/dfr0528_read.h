/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef DFR0528_READ_H
#define DFR0528_READ_H
/* Shared with the host tests. The caller supplies errno constants. */
typedef int (*dfr0528_reader)(void *ctx, unsigned char reg);
static int dfr0528_pair(dfr0528_reader read, void *ctx, unsigned char reg)
{
	int hi, lo, again, tries;
	for (tries = 0; tries < 3; tries++) {
		hi = read(ctx, reg);
		if (hi < 0) return hi;
		lo = read(ctx, reg + 1);
		if (lo < 0) return lo;
		again = read(ctx, reg);
		if (again < 0) return again;
		if (hi == again) return (hi << 8) | lo;
	}
	return -EAGAIN;
}
static int dfr0528_sample(dfr0528_reader read, void *ctx, int *uv, int *pct)
{
	int id, voltage, soc;
	id = read(ctx, 1);
	if (id < 0) return id;
	if (id != 0xdf) return -ENODEV;
	voltage = dfr0528_pair(read, ctx, 3);
	if (voltage < 0) return voltage;
	soc = dfr0528_pair(read, ctx, 5);
	if (soc < 0) return soc;
	/* One 3.7 V lithium cell; reject disconnected/invalid measurements. */
	voltage = (voltage & 0x0fff) * 1250;
	if (voltage < 2500000 || voltage > 4500000 || soc > 110 * 256)
		return -ENODATA;
	*uv = voltage;
	*pct = soc / 256;
	if (*pct > 100) *pct = 100;
	return 0;
}
#endif
