// SPDX-License-Identifier: GPL-2.0-only
/* Native composite encoder on the Orange Pi Zero 2W. */
#include <linux/component.h>
#include <linux/module.h>
#include <linux/of_graph.h>
#include <linux/platform_device.h>

#include <drm/drm_atomic.h>
#include <drm/drm_atomic_helper.h>
#include <drm/drm_of.h>
#include <drm/drm_print.h>
#include <drm/drm_probe_helper.h>
#include <drm/drm_simple_kms_helper.h>

#include "h618-tve-resources.h"

struct h618_drm {
	struct h618_cvbs_hw hw;
	struct drm_encoder encoder;
	struct drm_connector connector;
	struct drm_display_mode *pal, *ntsc;
};

/* Deflicker takes a progressive frame per output field (TVE clock / 8).
 * These are the H618 BSP's TCON input timings, in pixels and full lines.
 */
static const struct drm_display_mode pal_input = {
	DRM_MODE("720x576", DRM_MODE_TYPE_DRIVER, 27000,
		 720, 732, 796, 864, 0, 576, 581, 586, 625, 0,
		 DRM_MODE_FLAG_NHSYNC | DRM_MODE_FLAG_NVSYNC)
};

static const struct drm_display_mode ntsc_input = {
	DRM_MODE("720x480", DRM_MODE_TYPE_DRIVER, 27000,
		 720, 736, 798, 858, 0, 480, 489, 495, 525, 0,
		 DRM_MODE_FLAG_NHSYNC | DRM_MODE_FLAG_NVSYNC)
};

static enum drm_mode_status h618_mode_valid(struct drm_encoder *encoder,
					    const struct drm_display_mode *mode)
{
	struct h618_drm *tv = container_of(encoder, struct h618_drm, encoder);

	if (drm_mode_equal(mode, tv->pal) || drm_mode_equal(mode, tv->ntsc))
		return MODE_OK;
	return MODE_BAD;
}

static int h618_atomic_check(struct drm_encoder *encoder,
			     struct drm_crtc_state *crtc,
			     struct drm_connector_state *conn)
{
	struct h618_drm *tv = container_of(encoder, struct h618_drm, encoder);
	const struct drm_display_mode *input;

	if (crtc->encoder_mask != drm_encoder_mask(encoder))
		return -EINVAL;
	if (conn->tv.mode == DRM_MODE_TV_MODE_PAL &&
	    drm_mode_equal(&crtc->mode, tv->pal))
		input = &pal_input;
	else if (conn->tv.mode == DRM_MODE_TV_MODE_NTSC &&
		 drm_mode_equal(&crtc->mode, tv->ntsc))
		input = &ntsc_input;
	else
		return -EINVAL;

	drm_mode_copy(&crtc->adjusted_mode, input);
	drm_mode_set_crtcinfo(&crtc->adjusted_mode, 0);
	return 0;
}

static void h618_enable(struct drm_encoder *encoder, struct drm_atomic_state *state)
{
	struct h618_drm *tv = container_of(encoder, struct h618_drm, encoder);
	struct drm_connector_state *conn;
	int ret;

	conn = drm_atomic_get_new_connector_state(state, &tv->connector);
	ret = h618_cvbs_enable(&tv->hw, conn->tv.mode == DRM_MODE_TV_MODE_PAL
			       ? H618_CVBS_PAL : H618_CVBS_NTSC);
	if (ret)
		drm_err(encoder->dev, "CVBS enable failed: %d\n", ret);
}

static void h618_disable(struct drm_encoder *encoder, struct drm_atomic_state *state)
{
	struct h618_drm *tv = container_of(encoder, struct h618_drm, encoder);
	int ret = h618_cvbs_disable(&tv->hw);

	if (ret)
		drm_err(encoder->dev, "CVBS shutdown failed: %d\n", ret);
}

static const struct drm_encoder_helper_funcs h618_encoder_helpers = {
	.mode_valid = h618_mode_valid,
	.atomic_check = h618_atomic_check,
	.atomic_enable = h618_enable,
	.atomic_disable = h618_disable,
};

static void h618_connector_reset(struct drm_connector *connector)
{
	drm_atomic_helper_connector_reset(connector);
	if (connector->state)
		drm_atomic_helper_connector_tv_reset(connector);
}

static const struct drm_connector_funcs h618_connector_ops = {
	.reset = h618_connector_reset,
	.fill_modes = drm_helper_probe_single_connector_modes,
	.destroy = drm_connector_cleanup,
	.atomic_duplicate_state = drm_atomic_helper_connector_duplicate_state,
	.atomic_destroy_state = drm_atomic_helper_connector_destroy_state,
};

static const struct drm_connector_helper_funcs h618_connector_helpers = {
	.get_modes = drm_connector_helper_tv_get_modes,
	.atomic_check = drm_atomic_helper_connector_tv_check,
};

static int h618_bind(struct device *dev, struct device *master, void *data)
{
	struct drm_device *drm = data;
	struct h618_drm *tv = dev_get_drvdata(dev);
	int ret;

	tv->pal = drm_mode_analog_pal_576i(drm);
	tv->ntsc = drm_mode_analog_ntsc_480i(drm);
	if (!tv->pal || !tv->ntsc) {
		ret = -ENOMEM;
		goto free_modes;
	}

	ret = drm_simple_encoder_init(drm, &tv->encoder, DRM_MODE_ENCODER_TVDAC);
	if (ret)
		goto free_modes;
	drm_encoder_helper_add(&tv->encoder, &h618_encoder_helpers);
	tv->encoder.possible_crtcs = drm_of_find_possible_crtcs(drm, dev->of_node);
	if (!tv->encoder.possible_crtcs) {
		ret = -ENODEV;
		goto clean_encoder;
	}

	ret = drm_connector_init(drm, &tv->connector, &h618_connector_ops,
				 DRM_MODE_CONNECTOR_Composite);
	if (ret)
		goto clean_encoder;
	tv->connector.interlace_allowed = true;
	drm_connector_helper_add(&tv->connector, &h618_connector_helpers);
	ret = drm_connector_attach_encoder(&tv->connector, &tv->encoder);
	if (ret)
		goto clean_connector;
	ret = drm_mode_create_tv_properties(drm, BIT(DRM_MODE_TV_MODE_NTSC) |
					    BIT(DRM_MODE_TV_MODE_PAL));
	if (ret)
		goto clean_connector;
	drm_object_attach_property(&tv->connector.base, drm->mode_config.tv_mode_property,
				   DRM_MODE_TV_MODE_PAL);
	return 0;

clean_connector:
	drm_connector_cleanup(&tv->connector);
clean_encoder:
	drm_encoder_cleanup(&tv->encoder);
free_modes:
	drm_mode_destroy(drm, tv->ntsc);
	drm_mode_destroy(drm, tv->pal);
	return ret;
}

static void h618_unbind(struct device *dev, struct device *master, void *data)
{
	struct h618_drm *tv = dev_get_drvdata(dev);
	struct drm_device *drm = tv->encoder.dev;
	int ret = h618_cvbs_disable(&tv->hw);

	if (ret)
		dev_err(dev, "CVBS shutdown failed: %d\n", ret);
	drm_connector_cleanup(&tv->connector);
	drm_encoder_cleanup(&tv->encoder);
	drm_mode_destroy(drm, tv->ntsc);
	drm_mode_destroy(drm, tv->pal);
}

static const struct component_ops h618_component_ops = {
	.bind = h618_bind,
	.unbind = h618_unbind,
};

static int h618_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct device_node *out;
	struct h618_drm *tv;
	int ret;

	out = of_graph_get_remote_node(dev->of_node, 1, 0);
	ret = of_device_is_compatible(out, "composite-video-connector");
	of_node_put(out);
	if (!ret)
		return -ENODEV;
	tv = devm_kzalloc(dev, sizeof(*tv), GFP_KERNEL);
	if (!tv)
		return -ENOMEM;
	ret = h618_cvbs_acquire(pdev, &tv->hw);
	if (ret)
		return dev_err_probe(dev, ret, "TVE resources\n");
	platform_set_drvdata(pdev, tv);
	return component_add(dev, &h618_component_ops);
}

static void h618_remove(struct platform_device *pdev)
{
	component_del(&pdev->dev, &h618_component_ops);
}

static const struct of_device_id h618_ids[] = {
	{ .compatible = "allwinner,sun50i-h618-tv-encoder" },
	{ }
};
MODULE_DEVICE_TABLE(of, h618_ids);

static struct platform_driver h618_driver = {
	.probe = h618_probe,
	.remove = h618_remove,
	.driver = {
		.name = "sun50i-h618-tv-encoder",
		.of_match_table = h618_ids,
	},
};
module_platform_driver(h618_driver);
MODULE_DESCRIPTION("Allwinner H618 composite TV encoder");
MODULE_LICENSE("GPL");
