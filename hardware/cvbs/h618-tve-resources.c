// SPDX-License-Identifier: GPL-2.0-only
/* Resource operations for the H618 DRM component. */
#include <linux/clk.h>
#include <linux/io.h>
#include <linux/nvmem-consumer.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/reset.h>
#include <linux/slab.h>

#include "h618-tve-resources.h"

#define TVE_RATE_HZ 216000000

static struct regmap *map_window(struct platform_device *pdev, const char *name,
				 unsigned int size)
{
	const struct regmap_config config = {
		.name = name,
		.reg_bits = 32,
		.val_bits = 32,
		.reg_stride = 4,
		.max_register = size - 4,
		.val_format_endian = REGMAP_ENDIAN_LITTLE,
		.cache_type = REGCACHE_NONE,
	};
	struct resource *res;
	void __iomem *base;

	res = platform_get_resource_byname(pdev, IORESOURCE_MEM, name);
	if (!res || resource_size(res) < size)
		return ERR_PTR(-EINVAL);
	base = devm_ioremap_resource(&pdev->dev, res);
	if (IS_ERR(base))
		return ERR_CAST(base);
	return devm_regmap_init_mmio(&pdev->dev, base, &config);
}

static int read_trim(struct device *dev, u16 *trim)
{
	struct nvmem_cell *cell;
	size_t len;
	void *data;
	int ret;

	cell = nvmem_cell_get(dev, "tvout");
	if (IS_ERR(cell))
		return PTR_ERR(cell);
	data = nvmem_cell_read(cell, &len);
	nvmem_cell_put(cell);
	if (IS_ERR(data))
		return PTR_ERR(data);
	ret = h618_tve_decode_trim(data, len, trim);
	kfree(data);
	return ret;
}

int h618_cvbs_acquire(struct platform_device *pdev, struct h618_cvbs_hw *hw)
{
	struct device *dev = &pdev->dev;

	hw->active = false;
	hw->tve.top = map_window(pdev, "top", 0x100);
	if (IS_ERR(hw->tve.top))
		return PTR_ERR(hw->tve.top);
	hw->tve.encoder = map_window(pdev, "encoder", 0x3fc);
	if (IS_ERR(hw->tve.encoder))
		return PTR_ERR(hw->tve.encoder);
	hw->top_bus = devm_clk_get(dev, "top-bus");
	if (IS_ERR(hw->top_bus))
		return PTR_ERR(hw->top_bus);
	hw->bus = devm_clk_get(dev, "bus");
	if (IS_ERR(hw->bus))
		return PTR_ERR(hw->bus);
	hw->module = devm_clk_get(dev, "tve");
	if (IS_ERR(hw->module))
		return PTR_ERR(hw->module);
	hw->top_reset = devm_reset_control_get_exclusive(dev, "top");
	if (IS_ERR(hw->top_reset))
		return PTR_ERR(hw->top_reset);
	hw->encoder_reset = devm_reset_control_get_exclusive(dev, "encoder");
	if (IS_ERR(hw->encoder_reset))
		return PTR_ERR(hw->encoder_reset);
	return read_trim(dev, &hw->trim);
}

int h618_cvbs_enable(struct h618_cvbs_hw *hw, enum h618_cvbs_mode mode)
{
	int ret;

	if (mode != H618_CVBS_PAL && mode != H618_CVBS_NTSC)
		return -EINVAL;
	if (hw->active)
		return -EBUSY;

	/* Establish a cold start even if the bootloader left PAL active. */
	ret = reset_control_assert(hw->encoder_reset);
	if (ret)
		return ret;
	ret = reset_control_assert(hw->top_reset);
	if (ret)
		return ret;
	ret = clk_set_rate_exclusive(hw->module, TVE_RATE_HZ);
	if (ret)
		return ret;
	if (clk_get_rate(hw->module) != TVE_RATE_HZ) {
		ret = -ERANGE;
		goto put_rate;
	}
	ret = reset_control_deassert(hw->top_reset);
	if (ret)
		goto put_rate;
	ret = clk_prepare_enable(hw->top_bus);
	if (ret)
		goto assert_top;
	ret = clk_prepare_enable(hw->module);
	if (ret)
		goto disable_top;
	ret = clk_prepare_enable(hw->bus);
	if (ret)
		goto disable_module;
	ret = reset_control_deassert(hw->encoder_reset);
	if (ret)
		goto disable_bus;
	ret = h618_tve_start(&hw->tve, mode, hw->trim);
	if (!ret) {
		hw->active = true;
		return 0;
	}
	reset_control_assert(hw->encoder_reset);
disable_bus:
	clk_disable_unprepare(hw->bus);
disable_module:
	clk_disable_unprepare(hw->module);
disable_top:
	clk_disable_unprepare(hw->top_bus);
assert_top:
	reset_control_assert(hw->top_reset);
put_rate:
	clk_rate_exclusive_put(hw->module);
	return ret;
}

int h618_cvbs_disable(struct h618_cvbs_hw *hw)
{
	int ret, encoder, top;

	if (!hw->active)
		return 0;
	ret = h618_tve_stop(&hw->tve);
	encoder = reset_control_assert(hw->encoder_reset);
	clk_disable_unprepare(hw->bus);
	clk_disable_unprepare(hw->module);
	clk_disable_unprepare(hw->top_bus);
	top = reset_control_assert(hw->top_reset);
	clk_rate_exclusive_put(hw->module);
	hw->active = false;
	return ret ? ret : (encoder ? encoder : top);
}
