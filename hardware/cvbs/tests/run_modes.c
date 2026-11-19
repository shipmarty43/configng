// SPDX-License-Identifier: GPL-2.0-only
#include <stdio.h>
#include <stdlib.h>

extern int check_modes(void);

void *test_zalloc(size_t size)
{
	return calloc(1, size);
}

void test_free(const void *ptr)
{
	free((void *)ptr);
}

int main(void)
{
	int ret = check_modes();

	if (ret)
		fprintf(stderr, "KMS mode check failed at case %d\n", ret);
	else
		puts("PASS: PAL/NTSC wire and TCON timings, mode/standard mismatch, clone and custom timing rejection");
	return ret;
}
