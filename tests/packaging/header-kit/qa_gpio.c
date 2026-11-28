// SPDX-License-Identifier: GPL-2.0
/* Two independent QEMU-only gpiochips with the A733 bank layouts. */
#include <linux/gpio/driver.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>

struct bank {
	struct platform_device *pdev;
	struct gpio_chip chip;
	DECLARE_BITMAP(level, 352);
	DECLARE_BITMAP(output, 352);
};
static struct bank banks[2];
static int get(struct gpio_chip *g, unsigned int n) {
	struct bank *b = gpiochip_get_data(g);
	return test_bit(n, b->level);
}
static void set(struct gpio_chip *g, unsigned int n, int value) {
	struct bank *b = gpiochip_get_data(g);
	assign_bit(n, b->level, value);
}
static int input(struct gpio_chip *g, unsigned int n) {
	struct bank *b = gpiochip_get_data(g);
	clear_bit(n,b->output);
	return 0;
}
static int output(struct gpio_chip *g, unsigned int n, int value) {
	struct bank *b = gpiochip_get_data(g);
	set(g,n,value); set_bit(n,b->output);
	return 0;
}
static int direction(struct gpio_chip *g, unsigned int n) {
	struct bank *b = gpiochip_get_data(g);
	return !test_bit(n,b->output);
}
static int add_bank(int i) {
	struct bank *b = &banks[i];
	struct device_node *node;
	const char *path = i ? "/soc@3000000/pinctrl@7025000" : "/soc@3000000/pinctrl@2000000";
	int ret;
	node = of_find_node_by_path(path);
	if (!node) return -ENODEV;
	b->pdev = platform_device_alloc("qa-a733-bank", i);
	if (!b->pdev) { of_node_put(node); return -ENOMEM; }
	b->pdev->dev.of_node = node;
	ret = platform_device_add(b->pdev);
	if (ret) { platform_device_put(b->pdev); return ret; }
	b->chip = (struct gpio_chip){
		.parent=&b->pdev->dev, .owner=THIS_MODULE, .base=-1, .label=dev_name(&b->pdev->dev),
		.ngpio=i ? 64 : 352, .get=get, .set=set, .get_direction=direction,
		.direction_input=input, .direction_output=output,
	};
	ret = devm_gpiochip_add_data(&b->pdev->dev,&b->chip,b);
	if (ret) platform_device_unregister(b->pdev);
	return ret;
}
static int __init fixture_init(void) {
	int ret;
	if (!of_machine_is_compatible("linux,dummy-virt") || !of_machine_is_compatible("xunlong,orangepi-zero3w")) return -ENODEV;
	/* Register the standby controller first, opposite to the board table. */
	ret=add_bank(1);
	if (ret) return ret;
	ret=add_bank(0);
	if (ret) platform_device_unregister(banks[1].pdev);
	return ret;
}
static void __exit fixture_exit(void) {
	platform_device_unregister(banks[0].pdev); platform_device_unregister(banks[1].pdev);
}
module_init(fixture_init);
module_exit(fixture_exit);
MODULE_LICENSE("GPL");
