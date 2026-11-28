// SPDX-License-Identifier: GPL-2.0
/* Serialize explicit recovery with normal I2C traffic on the selected controller. */
#include <linux/capability.h>
#include <linux/compat.h>
#include <linux/i2c.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/uaccess.h>

struct opi_bus { __u32 number, controller, supported; };
#define OPI_STATUS _IOWR('O', 0x61, struct opi_bus)
#define OPI_RECOVER _IOW('O', 0x62, struct opi_bus)

static long opi_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	struct opi_bus bus;
	struct i2c_adapter *adap;
	struct device_node *node;
	char path[64];
	int ret = 0;

	if (cmd != OPI_STATUS && cmd != OPI_RECOVER)
		return -ENOTTY;
	if (cmd == OPI_RECOVER && !capable(CAP_SYS_ADMIN))
		return -EPERM;
	if (copy_from_user(&bus, (void __user *)arg, sizeof(bus)))
		return -EFAULT;
	if (bus.number > INT_MAX)
		return -EINVAL;
	if (of_machine_is_compatible("xunlong,orangepi-zero2w") && bus.controller <= 4)
		snprintf(path, sizeof(path), "/soc/i2c@%x", 0x5002000 + bus.controller * 0x400);
	else if (of_machine_is_compatible("xunlong,orangepi-zero3w") && bus.controller <= 3)
		snprintf(path, sizeof(path), "/soc@3000000/twi@%x", 0x2510000 + bus.controller * 0x1000);
	else
		return -ENODEV;
	adap = i2c_get_adapter(bus.number);
	if (!adap)
		return -ENODEV;
	node = of_find_node_by_path(path);
	if (!node || adap->dev.of_node != node) {
		ret = -ENODEV;
		goto out;
	}
	bus.supported = adap->bus_recovery_info && adap->bus_recovery_info->recover_bus;
	if (cmd == OPI_STATUS)
		ret = copy_to_user((void __user *)arg, &bus, sizeof(bus)) ? -EFAULT : 0;
	else if (!bus.supported)
		ret = -EOPNOTSUPP;
	else if (!i2c_trylock_bus(adap, I2C_LOCK_ROOT_ADAPTER))
		ret = -EBUSY;
	else {
		ret = i2c_recover_bus(adap);
		i2c_unlock_bus(adap, I2C_LOCK_ROOT_ADAPTER);
	}
out:
	of_node_put(node);
	i2c_put_adapter(adap);
	return ret;
}

static const struct file_operations opi_fops = {
	.owner = THIS_MODULE, .unlocked_ioctl = opi_ioctl,
	.compat_ioctl = compat_ptr_ioctl,
};
static struct miscdevice opi_misc = {
	.minor = MISC_DYNAMIC_MINOR, .name = "opi-i2c-recovery", .mode = 0600, .fops = &opi_fops,
};
module_misc_device(opi_misc);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Orange Pi I2C adapter recovery using the kernel bus lock");
