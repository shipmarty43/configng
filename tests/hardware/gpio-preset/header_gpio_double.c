// SPDX-License-Identifier: GPL-2.0-only
/* QEMU-only gpiochip. No physical registers, clocks or IRQs. */
#include <linux/gpio/driver.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/pinctrl/pinconf-generic.h>

static int config(struct gpio_chip *gc, unsigned int line, unsigned long cfg)
{
	enum pin_config_param p = pinconf_to_config_param(cfg);
	u32 v = pinconf_to_config_argument(cfg);

	if (!line && p == PIN_CONFIG_INPUT_DEBOUNCE) {
		dev_info(gc->parent, "debounce line=0 arg=%u\n", v);
		return 0;
	}
	if (p == PIN_CONFIG_PERSIST_STATE)
		return -ENOTSUPP;
	if (line == 2)
		return -ENOTSUPP;
	if (p == PIN_CONFIG_DRIVE_STRENGTH || p == PIN_CONFIG_BIAS_PULL_UP ||
	    p == PIN_CONFIG_BIAS_PULL_DOWN || p == PIN_CONFIG_BIAS_DISABLE) {
		dev_info(gc->parent, "config line=%u %s=%u\n", line,
			 p == PIN_CONFIG_DRIVE_STRENGTH ? "drive" :
			 p == PIN_CONFIG_BIAS_PULL_UP ? "up" :
			 p == PIN_CONFIG_BIAS_PULL_DOWN ? "down" : "off", v);
		return 0;
	}
	return -ENOTSUPP;
}

static int direction(struct gpio_chip *gc, unsigned int line) { return 1; }
static int input(struct gpio_chip *gc, unsigned int line)
{
	dev_info(gc->parent, "direction-input line=%u\n", line);
	return 0;
}
static int get(struct gpio_chip *gc, unsigned int line) { return 0; }
static void release(struct gpio_chip *gc, unsigned int line)
{
	dev_info(gc->parent, "release line=%u\n", line);
}

static int probe(struct platform_device *pdev)
{
	struct gpio_chip *gc = devm_kzalloc(&pdev->dev, sizeof(*gc), GFP_KERNEL);

	if (!gc)
		return -ENOMEM;
	gc->parent = &pdev->dev;
	gc->label = "header-gpio-double";
	gc->owner = THIS_MODULE;
	gc->base = -1;
	gc->ngpio = 6;
	gc->get_direction = direction;
	gc->direction_input = input;
	gc->get = get;
	gc->free = release;
	gc->set_config = config;
	return devm_gpiochip_add_data(&pdev->dev, gc, NULL);
}
static const struct of_device_id matches[] = {
	{ .compatible = "test,header-gpio-double" }, {}
};
static struct platform_driver double_driver = {
	.driver = { .name = "header-gpio-double", .of_match_table = matches },
	.probe = probe,
};
module_platform_driver(double_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("GPIO acceptance-test double");
