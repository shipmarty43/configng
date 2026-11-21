// SPDX-License-Identifier: GPL-2.0-only
/* QEMU-only six-channel PWM provider, no clocks connected to hardware. */
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/pwm.h>

static int model_apply(struct pwm_chip *chip, struct pwm_device *pwm,
                       const struct pwm_state *state)
{
    if ((pwm->hwpwm < 1 || pwm->hwpwm > 4) || state->polarity != PWM_POLARITY_NORMAL)
        return -EPERM;
    return 0; /* Linux PWM core caches this accepted request for sysfs. */
}

static const struct pwm_ops ops = { .apply = model_apply };

static int model_probe(struct platform_device *pdev)
{
    struct pwm_chip *chip;

    if (!of_machine_is_compatible("linux,dummy-virt"))
        return -ENODEV;
    chip = devm_pwmchip_alloc(&pdev->dev, 6, 0);
    if (IS_ERR(chip))
        return PTR_ERR(chip);
    chip->ops = &ops;
    return devm_pwmchip_add(&pdev->dev, chip);
}

static const struct of_device_id ids[] = {
    { .compatible = "test,h616-pwm" }, {}
};
static struct platform_driver model = {
    .probe = model_probe,
    .driver = { .name = "sunxi_pwm", .of_match_table = ids },
};
module_platform_driver(model);
MODULE_LICENSE("GPL");
