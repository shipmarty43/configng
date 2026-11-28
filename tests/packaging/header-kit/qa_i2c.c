// SPDX-License-Identifier: GPL-2.0
/* Memory-backed test adapter used only in the QEMU fixture. */
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>

static int fault;
module_param(fault, int, 0600);
static bool supported = true;
module_param(supported, bool, 0444);
static int clocks, scl = 1;
static void drive_clock(struct i2c_adapter *a, int value)
{
	if (!scl && value)
		clocks++;
	scl = value;
}
static int clock_level(struct i2c_adapter *a) { return fault == 2 ? 0 : scl; }
static int data_level(struct i2c_adapter *a) { return !fault && clocks >= 3; }
static int recover(struct i2c_adapter *a)
{
	clocks = 0;
	if (fault == 3)
		return -ETIMEDOUT;
	return i2c_generic_scl_recovery(a);
}
static struct i2c_bus_recovery_info recovery = {
	.recover_bus = recover, .get_scl = clock_level, .set_scl = drive_clock, .get_sda = data_level,
};
static s32 twin_read(struct i2c_adapter *adap, u16 addr, unsigned short flags,
                     char rw, u8 reg, int size, union i2c_smbus_data *data)
{
    static const u8 regs[] = { 0x10, 0xdf, 0x13, 0x0b, 0x3b, 51, 0xd0 };

    if (addr != 0x10 || rw != I2C_SMBUS_READ || size != I2C_SMBUS_BYTE_DATA ||
        reg >= ARRAY_SIZE(regs))
        return -EOPNOTSUPP;
    data->byte = regs[reg];
    return 0;
}

static u32 caps(struct i2c_adapter *a) { return I2C_FUNC_I2C | I2C_FUNC_SMBUS_BYTE_DATA; }
static int transfer(struct i2c_adapter *a, struct i2c_msg *msg, int n) { return -EOPNOTSUPP; }
static const struct i2c_algorithm algorithm = {.functionality = caps, .master_xfer = transfer, .smbus_xfer = twin_read};
static struct i2c_adapter adapter = {.owner = THIS_MODULE, .algo = &algorithm, .name = "QEMU stuck-SDA fixture"};
static struct i2c_client *battery;
static struct platform_device *parent;
static int __init fixture_init(void)
{
	const char *path = of_machine_is_compatible("xunlong,orangepi-zero2w")
		? "/soc/i2c@5002400" : "/soc@3000000/twi@2510000";
	int ret;
	if (!of_machine_is_compatible("linux,dummy-virt"))
		return -ENODEV;
	adapter.dev.of_node = of_find_node_by_path(path);
	if (!adapter.dev.of_node)
		return -ENODEV;
	parent = platform_device_register_simple("qa-i2c-host", -1, NULL, 0);
	if (IS_ERR(parent)) {
		of_node_put(adapter.dev.of_node);
		return PTR_ERR(parent);
	}
	adapter.dev.parent = &parent->dev;
	adapter.bus_recovery_info = supported ? &recovery : NULL;
	ret = i2c_add_adapter(&adapter);
	if (!ret && supported && of_machine_is_compatible("xunlong,orangepi-zero2w")) {
		struct i2c_board_info info = { I2C_BOARD_INFO("dfr0528", 0x10) };
		battery = i2c_new_client_device(&adapter, &info);
		if (IS_ERR(battery)) {
			ret = PTR_ERR(battery);
			i2c_del_adapter(&adapter);
		}
	}
	if (ret) {
		platform_device_unregister(parent);
		of_node_put(adapter.dev.of_node);
	}
	return ret;
}
static void __exit fixture_exit(void)
{
	struct device_node *node = adapter.dev.of_node;
	if (battery)
		i2c_unregister_device(battery);
	i2c_del_adapter(&adapter);
	platform_device_unregister(parent);
	of_node_put(node);
}
module_init(fixture_init);
module_exit(fixture_exit);
MODULE_LICENSE("GPL");
