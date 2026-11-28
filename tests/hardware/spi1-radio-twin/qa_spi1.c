// SPDX-License-Identifier: GPL-2.0
/* QEMU-only. The Linux SPI core owns the select GPIOs; the three models accept
 * only identification reads and observe those lines at every transfer. */
#include <linux/bitmap.h>
#include <linux/gpio/driver.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/spi/spi.h>

static const unsigned int pad[] = {259, 233, 229}; /* PI3, PH9, PH5 */
static DECLARE_BITMAP(levels, 288);
static DECLARE_BITMAP(outputs, 288);
static DEFINE_SPINLOCK(lock);
static unsigned int active, overlaps, rejected, count[3], asserts[3];
module_param(active, uint, 0444);
module_param(overlaps, uint, 0444);
module_param(rejected, uint, 0444);
module_param_array(count, uint, NULL, 0444);
module_param_array(asserts, uint, NULL, 0444);

static int get(struct gpio_chip *gc, unsigned int n)
{
	return test_bit(n, levels);
}
static int set(struct gpio_chip *gc, unsigned int n, int value)
{
	unsigned long flags;
	unsigned int i;
	spin_lock_irqsave(&lock, flags);
	assign_bit(n, levels, value);
	for (i = 0; i < ARRAY_SIZE(pad); i++) {
		if (n != pad[i]) continue;
		if (!value && !(active & BIT(i))) asserts[i]++;
		if (value) active &= ~BIT(i);
		else active |= BIT(i);
		if (hweight32(active) > 1) overlaps++;
	}
	spin_unlock_irqrestore(&lock, flags);
	return 0;
}
static int input(struct gpio_chip *gc, unsigned int n)
{
	clear_bit(n, outputs);
	return 0;
}
static int output(struct gpio_chip *gc, unsigned int n, int value)
{
	set_bit(n, outputs);
	return set(gc, n, value);
}
static int direction(struct gpio_chip *gc, unsigned int n)
{
	return !test_bit(n, outputs);
}
static int xlate(struct gpio_chip *gc, const struct of_phandle_args *spec, u32 *flags)
{
	if (spec->args_count != 3 || spec->args[0] > 8 || spec->args[1] >= 32)
		return -EINVAL;
	if (flags) *flags = spec->args[2];
	return spec->args[0]*32 + spec->args[1];
}

static struct gpio_chip gpio = {
	.label = "300b000.pinctrl", .base = -1, .ngpio = 288, .owner = THIS_MODULE,
	.get = get, .set = set, .get_direction = direction,
	.direction_input = input, .direction_output = output,
	.of_gpio_n_cells = 3, .of_xlate = xlate,
};
static int transfer(struct spi_controller *ctl, struct spi_device *spi, struct spi_transfer *t)
{
	unsigned int cs = spi_get_chipselect(spi, 0);
	const unsigned int rates[] = {2000000, 1000000, 4000000};
	const u8 *tx = t->tx_buf;
	u8 *rx = t->rx_buf;
	int reply = -1;
	if (cs >= 3 || READ_ONCE(active) != BIT(cs) || !test_bit(pad[cs], outputs) ||
	    t->len != 2 || !rx || !tx || (spi->mode & (SPI_CPOL|SPI_CPHA|SPI_LSB_FIRST)) ||
	    t->speed_hz != rates[cs])
		goto reject;
	switch (cs) {
	case 0:
		if (tx[0] == 0xc0 && !tx[1]) reply = 0x24;
		break;
	case 1:
		if (tx[1]) break;
		switch (tx[0]) {
		case 0xf0: reply = 0; break;
		case 0xf1: reply = 0x14; break;
		case 0xf5: reply = 1; break;
		}
		break;
	case 2:
		if (tx[1] != 0xff || !test_bit(228, outputs) || test_bit(228, levels)) break;
		switch (tx[0]) {
		case 0: reply = 8; break;
		case 5: reply = 76; break;
		case 9: reply = 0; break;
		}
	}
	if (reply < 0) goto reject;
	rx[0] = cs == 2 ? 0x0e : 0;
	rx[1] = reply;
	count[cs]++;
	return 0;
reject:
	rejected++;
	return -EPROTO;
}

static struct platform_device *gpio_parent, *spi_parent;
static int __init fixture_init(void)
{
	struct spi_controller *ctl;
	struct device_node *pio, *bus;
	unsigned int i;
	int ret;
	if (!of_machine_is_compatible("linux,dummy-virt")) return -ENODEV;
	pio = of_find_node_by_path("/soc/pinctrl@300b000");
	bus = of_find_node_by_path("/soc/spi@5011000");
	if (!of_device_is_compatible(pio,"test,memory-gpio") || !of_device_is_compatible(bus,"test,memory-spi")) {
		ret = -ENODEV;
		goto put;
	}
	for (i = 0; i < ARRAY_SIZE(pad); i++) set_bit(pad[i], levels);
	gpio_parent = platform_device_register_simple("qa-radio-pio", -1, NULL, 0);
	if (IS_ERR(gpio_parent)) { ret = PTR_ERR(gpio_parent); goto put; }
	gpio.parent = &gpio_parent->dev;
	gpio.fwnode = of_fwnode_handle(pio);
	ret = devm_gpiochip_add_data(&gpio_parent->dev, &gpio, NULL);
	if (ret) goto free_gpio;
	spi_parent = platform_device_register_simple("qa-radio-spi", -1, NULL, 0);
	if (IS_ERR(spi_parent)) { ret = PTR_ERR(spi_parent); goto free_gpio; }
	ctl = devm_spi_alloc_host(&spi_parent->dev, 0);
	if (!ctl) { ret = -ENOMEM; goto free_spi; }
	device_set_node(&ctl->dev, of_fwnode_handle(bus));
	ctl->bus_num = 7; /* Deliberately not Linux bus 1. */
	ctl->num_chipselect = 3;
	ctl->use_gpio_descriptors = true;
	ctl->bits_per_word_mask = SPI_BPW_MASK(8);
	ctl->max_speed_hz = 16000000;
	ctl->transfer_one = transfer;
	ret = devm_spi_register_controller(&spi_parent->dev, ctl);
	if (!ret) goto put;
free_spi:
	platform_device_unregister(spi_parent);
free_gpio:
	platform_device_unregister(gpio_parent);
put:
	of_node_put(bus);
	of_node_put(pio);
	return ret;
}
static void __exit fixture_exit(void)
{
	platform_device_unregister(spi_parent);
	platform_device_unregister(gpio_parent);
}
module_init(fixture_init);
module_exit(fixture_exit);
MODULE_DESCRIPTION("QEMU-only three-client SPI1 and GPIO select model");
MODULE_LICENSE("GPL");
