/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include "dfr0528_read.h"
struct fake { int reg[7], fail, unstable; };
static int read_reg(void *ctx, unsigned char reg) {
	struct fake *f = ctx;
	if (reg == f->fail) return -EIO;
	if (reg == 3 && f->unstable) return f->unstable++ & 15;
	return f->reg[reg];
}
int main(void) {
	struct fake f = { .reg = {0x10,0xdf,0x13,0x0b,0x3b,0x33,0xd0}, .fail = -1 };
	int uv = -1, pct = -1;
	assert(!dfr0528_sample(read_reg,&f,&uv,&pct));
	assert(uv == 3593750 && pct == 51);
	for (int i=1;i<=6;i++) { if(i==2) continue; f.fail=i;
		uv=-1; pct=-1; assert(dfr0528_sample(read_reg,&f,&uv,&pct)==-EIO); assert(uv==-1 && pct==-1); }
	f.fail=-1; f.reg[1]=0; assert(dfr0528_sample(read_reg,&f,&uv,&pct)==-ENODEV);
	f.reg[1]=0xdf; f.unstable=1; assert(dfr0528_sample(read_reg,&f,&uv,&pct)==-EAGAIN);
	f.unstable=0; f.reg[5]=101; assert(!dfr0528_sample(read_reg,&f,&uv,&pct) && pct==100);
	f.reg[5]=255; assert(dfr0528_sample(read_reg,&f,&uv,&pct)==-ENODATA);
	f.reg[5]=51; f.reg[3]=0; f.reg[4]=0; assert(dfr0528_sample(read_reg,&f,&uv,&pct)==-ENODATA);
	puts("DFR0528 decoding, bounds, identity, I/O and torn-read tests passed");
}
