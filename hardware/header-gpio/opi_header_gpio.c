// SPDX-License-Identifier: GPL-2.0-only
/* Apply boot defaults through the owning gpiochip without retaining the line. */
#include <linux/device.h>
#include <linux/gpio/consumer.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/pinctrl/pinconf-generic.h>
#include <linux/platform_device.h>
#include <linux/property.h>

static int opi_header_gpio_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct gpio_desc *line;
	unsigned long config[2];
	unsigned int n = 0, i;
	u32 drive;
	int ret;
	bool up = device_property_read_bool(dev, "bias-pull-up");
	bool down = device_property_read_bool(dev, "bias-pull-down");
	bool off = device_property_read_bool(dev, "bias-disable");

	if (up + down + off > 1)
		return dev_err_probe(dev, -EINVAL, "conflicting bias settings\n");
	if (device_property_present(dev, "drive-strength")) {
		ret = device_property_read_u32(dev, "drive-strength", &drive);
		if (ret || drive < 10 || drive > 40 || drive % 10)
			return dev_err_probe(dev, -EINVAL, "invalid drive-strength\n");
		config[n++] = pinconf_to_config_packed(PIN_CONFIG_DRIVE_STRENGTH, drive);
	}
	if (up)
		config[n++] = pinconf_to_config_packed(PIN_CONFIG_BIAS_PULL_UP, 1);
	if (down)
		config[n++] = pinconf_to_config_packed(PIN_CONFIG_BIAS_PULL_DOWN, 1);
	if (off)
		config[n++] = pinconf_to_config_packed(PIN_CONFIG_BIAS_DISABLE, 0);
	if (!n)
		return -EINVAL;

	line = gpiod_get(dev, "target", GPIOD_ASIS);
	if (IS_ERR(line))
		return dev_err_probe(dev, PTR_ERR(line), "cannot claim target GPIO\n");
	for (i = 0; i < n; i++) {
		ret = gpiod_set_config(line, config[i]);
		if (ret)
			break;
	}
	gpiod_put(line);
	return ret ? dev_err_probe(dev, ret, "gpiochip rejected setting %u\n", i) : 0;
}

static const struct of_device_id opi_header_gpio_matches[] = {
	{ .compatible = "armbian,header-gpio-preset" },
	{}
};
MODULE_DEVICE_TABLE(of, opi_header_gpio_matches);

static struct platform_driver opi_header_gpio_driver = {
	.probe = opi_header_gpio_probe,
	.driver = {
		.name = "opi-header-gpio",
		.of_match_table = opi_header_gpio_matches,
	},
};
module_platform_driver(opi_header_gpio_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("One-shot Orange Pi header GPIO bias and drive settings");
