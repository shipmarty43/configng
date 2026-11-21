// SPDX-License-Identifier: GPL-2.0-only
/* QEMU-only register model. No physical adapter, MMIO or GPIO access. */
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>

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

static u32 twin_funcs(struct i2c_adapter *adap)
{
    return I2C_FUNC_SMBUS_READ_BYTE_DATA | I2C_FUNC_SMBUS_WRITE_BYTE_DATA;
}

static const struct i2c_algorithm twin_algo = {
    .smbus_xfer = twin_read,
    .functionality = twin_funcs,
};

static int twin_probe(struct platform_device *pdev)
{
    struct i2c_adapter *adap;
    u32 rate;

    if (!of_machine_is_compatible("linux,dummy-virt") ||
        of_property_read_u32(pdev->dev.of_node, "clock-frequency", &rate) ||
        !rate || rate > 400000)
        return -EINVAL;
    adap = devm_kzalloc(&pdev->dev, sizeof(*adap), GFP_KERNEL);
    if (!adap)
        return -ENOMEM;
    snprintf(adap->name, sizeof(adap->name), "Virtual TWI1 %u Hz", rate);
    adap->owner = THIS_MODULE;
    adap->algo = &twin_algo;
    adap->dev.parent = &pdev->dev;
    adap->dev.of_node = pdev->dev.of_node;
    return devm_i2c_add_adapter(&pdev->dev, adap);
}

static const struct of_device_id twin_ids[] = {
    { .compatible = "test,dfr0528-adapter" }, {}
};

static struct platform_driver twin_driver = {
    .probe = twin_probe,
    .driver = { .name = "dfr0528-test-adapter", .of_match_table = twin_ids },
};
module_platform_driver(twin_driver);
MODULE_LICENSE("GPL");
