// SPDX-License-Identifier: GPL-2.0-only
/* ARM64 userspace stand-ins for imported kernel symbols. The enable/disable
 * functions under test are the actual Kbuild output for the target headers.
 */
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include "../h618-tve-resources.h"

struct clk { bool prepared, enabled; };
struct reset_control { bool asserted; };
static struct clk clocks[3];
static struct reset_control resets[2];
static bool exclusive, wrong_rate, started;
static int step, fail_at;

static int check(void) { return ++step == fail_at ? -EIO : 0; }

int clk_set_rate_exclusive(struct clk *clk, unsigned long rate)
{
	assert(!exclusive && clk == &clocks[1] && rate == 216000000);
	if (check()) return -EIO;
	exclusive = true;
	return 0;
}
unsigned long clk_get_rate(struct clk *clk)
{
	assert(exclusive && clk == &clocks[1]);
	return wrong_rate ? 215000000 : 216000000;
}
void clk_rate_exclusive_put(struct clk *clk)
{
	assert(exclusive && clk == &clocks[1]);
	exclusive = false;
}
int clk_prepare(struct clk *clk)
{
	assert(!clk->prepared);
	if (check()) return -EIO;
	clk->prepared = true;
	return 0;
}
int clk_enable(struct clk *clk)
{
	assert(clk->prepared && !clk->enabled);
	if (check()) return -EIO;
	clk->enabled = true;
	return 0;
}
void clk_disable(struct clk *clk)
{
	assert(clk->enabled);
	clk->enabled = false;
}
void clk_unprepare(struct clk *clk)
{
	assert(clk->prepared && !clk->enabled);
	clk->prepared = false;
}
int reset_control_assert(struct reset_control *reset)
{
	if (check()) return -EIO;
	reset->asserted = true;
	return 0;
}
int reset_control_deassert(struct reset_control *reset)
{
	assert(reset->asserted);
	if (check()) return -EIO;
	reset->asserted = false;
	return 0;
}
int h618_tve_start(const struct h618_tve *tve, enum h618_cvbs_mode mode, u16 trim)
{
	assert(tve && mode == H618_CVBS_PAL && trim == 625);
	assert(exclusive && !resets[0].asserted && !resets[1].asserted);
	for (int i = 0; i < 3; i++) assert(clocks[i].enabled);
	if (check()) return -EIO;
	started = true;
	return 0;
}
int h618_tve_stop(const struct h618_tve *tve)
{
	assert(tve && started && exclusive);
	started = false;
	return check();
}

static void no_leaks(struct h618_cvbs_hw *hw)
{
	assert(!exclusive && !hw->active && !started);
	for (int i = 0; i < 3; i++) assert(!clocks[i].prepared && !clocks[i].enabled);
}

int main(void)
{
	struct h618_cvbs_hw hw = {
		.top_bus = &clocks[0], .module = &clocks[1], .bus = &clocks[2],
		.top_reset = &resets[0], .encoder_reset = &resets[1], .trim = 625,
	};
	assert(h618_cvbs_enable(&hw, 999) == -EINVAL && !step);
	assert(!h618_cvbs_disable(&hw) && !step);
	assert(!h618_cvbs_enable(&hw, H618_CVBS_PAL));
	int enable_steps = step;
	assert(h618_cvbs_enable(&hw, H618_CVBS_PAL) == -EBUSY && step == enable_steps);
	assert(!h618_cvbs_disable(&hw));
	int disable_steps = step - enable_steps;
	no_leaks(&hw);
	for (int i = 1; i <= enable_steps; i++) {
		step = 0;
		fail_at = i;
		assert(h618_cvbs_enable(&hw, H618_CVBS_PAL) == -EIO);
		no_leaks(&hw);
	}
	for (int i = 1; i <= disable_steps; i++) {
		step = fail_at = 0;
		assert(!h618_cvbs_enable(&hw, H618_CVBS_PAL));
		fail_at = step + i;
		assert(h618_cvbs_disable(&hw) == -EIO);
		no_leaks(&hw);
	}
	fail_at = 0;
	wrong_rate = true;
	assert(h618_cvbs_enable(&hw, H618_CVBS_PAL) == -ERANGE);
	no_leaks(&hw);
	printf("Power paths: %d enable and %d disable fault points, rate mismatch and retry passed\n",
	       enable_steps, disable_steps);
}
