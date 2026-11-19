/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef H618_TVE_RESOURCES_H
#define H618_TVE_RESOURCES_H

#include "h618-tve.h"

struct platform_device;
struct clk;
struct reset_control;

/* Per-device storage. The DRM caller owns serialization and the display route. */
struct h618_cvbs_hw {
	struct h618_tve tve;
	struct clk *top_bus, *module, *bus;
	struct reset_control *top_reset, *encoder_reset;
	u16 trim;
	bool active;
};

int h618_cvbs_acquire(struct platform_device *pdev, struct h618_cvbs_hw *hw);
int h618_cvbs_enable(struct h618_cvbs_hw *hw, enum h618_cvbs_mode mode);
int h618_cvbs_disable(struct h618_cvbs_hw *hw);

#endif
