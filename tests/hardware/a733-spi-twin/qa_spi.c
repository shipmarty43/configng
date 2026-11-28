// SPDX-License-Identifier: GPL-2.0
/* CPU-only controllers. The child nodes carry the limits from the board DT. */
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/of.h>
#include <linux/spi/spi.h>

static int transfer_one(struct spi_controller *ctl, struct spi_device *spi, struct spi_transfer *t)
{
	const u8 *tx = t->tx_buf;
	u8 *rx = t->rx_buf;
	if (!rx || !tx || t->len != 8 || t->speed_hz != spi->max_speed_hz)
		return -EINVAL;
	rx[0] = ctl->bus_num;
	rx[1] = spi->mode & 3;
	rx[2] = t->speed_hz >> 24;
	rx[3] = t->speed_hz >> 16;
	rx[4] = t->speed_hz >> 8;
	rx[5] = t->speed_hz;
	rx[6] = tx[6];
	rx[7] = tx[7];
	return 0;
}
static int probe(struct platform_device *pdev)
{
	struct spi_controller *ctl;
	u32 n;
	if (!of_machine_is_compatible("linux,dummy-virt") ||
	    of_property_read_u32(pdev->dev.of_node,"qa,number",&n) || (n!=2 && n!=3))
		return -ENODEV;
	ctl = devm_spi_alloc_master(&pdev->dev,0);
	if (!ctl) return -ENOMEM;
	ctl->dev.of_node = pdev->dev.of_node;
	ctl->bus_num = n;
	ctl->num_chipselect = 1;
	ctl->mode_bits = SPI_CPOL | SPI_CPHA;
	ctl->max_speed_hz = 100000000;
	ctl->transfer_one = transfer_one;
	return devm_spi_register_controller(&pdev->dev,ctl);
}
static const struct of_device_id ids[]={{.compatible="test,opi-spi-double"},{}};
static struct platform_driver fixture={.probe=probe,.driver={.name="opi-spi-twin",.of_match_table=ids}};
module_platform_driver(fixture);
MODULE_LICENSE("GPL");
