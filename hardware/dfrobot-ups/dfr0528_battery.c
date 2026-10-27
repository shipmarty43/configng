// SPDX-License-Identifier: GPL-2.0-only
/* DFRobot DFR0528 MCU protocol, not the MAX17043 register map.
 * Read-only telemetry. No address changes, reset, charger or cutoff writes.
 */
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/power_supply.h>
#include <linux/workqueue.h>
#include "dfr0528_read.h"

struct dfr0528 {
	struct i2c_client *client;
	struct power_supply *psy;
	struct power_supply_desc desc;
	struct delayed_work poll;
	struct mutex lock;
	int voltage_uv, capacity;
	bool valid;
};
static int dfr_read(void *ctx, unsigned char reg)
{
	return i2c_smbus_read_byte_data(ctx, reg);
}
static enum power_supply_property dfr_props[] = {
	POWER_SUPPLY_PROP_PRESENT, POWER_SUPPLY_PROP_STATUS,
	POWER_SUPPLY_PROP_CAPACITY, POWER_SUPPLY_PROP_VOLTAGE_NOW,
	POWER_SUPPLY_PROP_SCOPE, POWER_SUPPLY_PROP_MODEL_NAME,
	POWER_SUPPLY_PROP_MANUFACTURER,
};
static int dfr_get(struct power_supply *psy, enum power_supply_property prop,
		   union power_supply_propval *value)
{
	struct dfr0528 *d = power_supply_get_drvdata(psy);
	int ret = 0;
	mutex_lock(&d->lock);
	switch (prop) {
	case POWER_SUPPLY_PROP_PRESENT: value->intval = d->valid; break;
	case POWER_SUPPLY_PROP_STATUS:
		/* The MCU exposes no charger/input-power status. Never invent it. */
		value->intval = POWER_SUPPLY_STATUS_UNKNOWN; break;
	case POWER_SUPPLY_PROP_CAPACITY:
		if (!d->valid) ret = -ENODATA;
		else value->intval = d->capacity;
		break;
	case POWER_SUPPLY_PROP_VOLTAGE_NOW:
		if (!d->valid) ret = -ENODATA;
		else value->intval = d->voltage_uv;
		break;
	case POWER_SUPPLY_PROP_SCOPE: value->intval = POWER_SUPPLY_SCOPE_SYSTEM; break;
	case POWER_SUPPLY_PROP_MODEL_NAME: value->strval = "DFR0528"; break;
	case POWER_SUPPLY_PROP_MANUFACTURER: value->strval = "DFRobot"; break;
	default: ret = -EINVAL;
	}
	mutex_unlock(&d->lock);
	return ret;
}
static void dfr_poll(struct work_struct *work)
{
	struct dfr0528 *d = container_of(to_delayed_work(work), struct dfr0528, poll);
	int uv, pct, ret;
	bool changed;
	ret = dfr0528_sample(dfr_read, d->client, &uv, &pct);
	mutex_lock(&d->lock);
	changed = d->valid != (ret == 0);
	if (!ret) {
		changed |= d->voltage_uv != uv || d->capacity != pct;
		d->voltage_uv = uv; d->capacity = pct;
	}
	d->valid = !ret;
	mutex_unlock(&d->lock);
	if (changed) power_supply_changed(d->psy);
	schedule_delayed_work(&d->poll, msecs_to_jiffies(5000));
}
static void dfr_stop(void *data)
{
	struct dfr0528 *d = data;
	cancel_delayed_work_sync(&d->poll);
}
static int dfr_probe(struct i2c_client *client)
{
	struct power_supply_config config = {};
	struct dfr0528 *d;
	int ret, version;
	if (!i2c_check_functionality(client->adapter, I2C_FUNC_SMBUS_BYTE_DATA))
		return -EOPNOTSUPP;
	ret = dfr_read(client, 1);
	if (ret < 0) return ret;
	if (ret != 0xdf) return -ENODEV;
	version = dfr_read(client, 2);
	if (version < 0) return version;
	if (version < 0x10 || version > 0x13)
		return dev_err_probe(&client->dev, -ENODEV, "Unqualified firmware 0x%x\n", version);
	d = devm_kzalloc(&client->dev, sizeof(*d), GFP_KERNEL);
	if (!d) return -ENOMEM;
	d->client = client;
	mutex_init(&d->lock);
	INIT_DELAYED_WORK(&d->poll, dfr_poll);
	ret = dfr0528_sample(dfr_read, client, &d->voltage_uv, &d->capacity);
	if (ret) return dev_err_probe(&client->dev, ret, "No valid battery telemetry\n");
	d->valid = true;
	d->desc.name = devm_kasprintf(&client->dev, GFP_KERNEL, "dfr0528-%s", dev_name(&client->dev));
	if (!d->desc.name) return -ENOMEM;
	d->desc.type = POWER_SUPPLY_TYPE_BATTERY;
	d->desc.properties = dfr_props;
	d->desc.num_properties = ARRAY_SIZE(dfr_props);
	d->desc.get_property = dfr_get;
	config.drv_data = d;
	config.fwnode = dev_fwnode(&client->dev);
	i2c_set_clientdata(client, d);
	d->psy = devm_power_supply_register(&client->dev, &d->desc, &config);
	if (IS_ERR(d->psy)) return PTR_ERR(d->psy);
	/* LIFO devres: cancel work before unregistering the power_supply. */
	ret = devm_add_action_or_reset(&client->dev, dfr_stop, d);
	if (ret) return ret;
	schedule_delayed_work(&d->poll, msecs_to_jiffies(5000));
	dev_info(&client->dev, "DFR0528 firmware %x.%x, read-only battery telemetry\n", version >> 4, version & 15);
	return 0;
}
static int dfr_suspend(struct device *dev) { dfr_stop(dev_get_drvdata(dev)); return 0; }
static int dfr_resume(struct device *dev)
{
	struct dfr0528 *d = dev_get_drvdata(dev);
	schedule_delayed_work(&d->poll, 0);
	return 0;
}
static DEFINE_SIMPLE_DEV_PM_OPS(dfr_pm, dfr_suspend, dfr_resume);
static const struct of_device_id dfr_of[] = { { .compatible = "dfrobot,dfr0528" }, {} };
MODULE_DEVICE_TABLE(of, dfr_of);
static const struct i2c_device_id dfr_ids[] = { { "dfr0528", 0 }, {} };
MODULE_DEVICE_TABLE(i2c, dfr_ids);
static struct i2c_driver dfr_driver = {
	.driver = { .name = "dfr0528_battery", .of_match_table = dfr_of, .pm = pm_sleep_ptr(&dfr_pm) },
	.probe = dfr_probe, .id_table = dfr_ids,
};
module_i2c_driver(dfr_driver);
MODULE_AUTHOR("shipmarty43");
MODULE_DESCRIPTION("DFRobot DFR0528 read-only battery telemetry");
MODULE_LICENSE("GPL");
