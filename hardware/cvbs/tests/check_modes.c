// SPDX-License-Identifier: GPL-2.0-only
#include "h618-drm.c"

int check_modes(void);
int check_modes(void)
{
	static struct drm_device drm;
	static struct h618_drm tv;
	static struct drm_crtc_state crtc;
	static struct drm_connector_state conn;
	int standard;

	tv.pal = drm_mode_analog_pal_576i(&drm);
	tv.ntsc = drm_mode_analog_ntsc_480i(&drm);
	if (!tv.pal || !tv.ntsc)
		return 1;
	for (standard = 0; standard < 2; standard++) {
		const struct drm_display_mode *output = standard ? tv.ntsc : tv.pal;
		const struct drm_display_mode *input = standard ? &ntsc_input : &pal_input;

		crtc.encoder_mask = drm_encoder_mask(&tv.encoder);
		conn.tv.mode = standard ? DRM_MODE_TV_MODE_NTSC : DRM_MODE_TV_MODE_PAL;
		drm_mode_init(&crtc.mode, output);
		if (h618_mode_valid(&tv.encoder, output) != MODE_OK ||
		    h618_atomic_check(&tv.encoder, &crtc, &conn))
			return 2;
		if (!drm_mode_equal(&crtc.adjusted_mode, input) ||
		    crtc.adjusted_mode.crtc_clock != 27000 ||
		    crtc.adjusted_mode.crtc_vtotal != (standard ? 525 : 625) ||
		    crtc.adjusted_mode.crtc_vdisplay != (standard ? 480 : 576) ||
		    crtc.mode.clock != 13500 || !(crtc.mode.flags & DRM_MODE_FLAG_INTERLACE))
			return 3;
		crtc.encoder_mask |= BIT(1);
		if (!h618_atomic_check(&tv.encoder, &crtc, &conn))
			return 4;
		crtc.encoder_mask = drm_encoder_mask(&tv.encoder);
		conn.tv.mode = standard ? DRM_MODE_TV_MODE_PAL : DRM_MODE_TV_MODE_NTSC;
		if (!h618_atomic_check(&tv.encoder, &crtc, &conn))
			return 5;
		crtc.mode.htotal++;
		if (h618_mode_valid(&tv.encoder, &crtc.mode) == MODE_OK)
			return 6;
	}
	drm_mode_destroy(&drm, tv.ntsc);
	drm_mode_destroy(&drm, tv.pal);
	return 0;
}

/* User-mode substitutes for allocation and printk, using kernel prototypes. */
extern void *test_zalloc(size_t size);
extern void test_free(const void *ptr);
kmem_buckets kmalloc_caches[NR_KMALLOC_TYPES];

void *__kmalloc_cache_noprof(struct kmem_cache *cache, gfp_t flags, size_t size)
{
	return test_zalloc(size);
}

void kfree(const void *ptr)
{
	test_free(ptr);
}

void __drm_dev_dbg(struct _ddebug *desc, const struct device *dev,
		   enum drm_debug_category category, const char *fmt, ...)
{
}

void _dev_err(const struct device *dev, const char *fmt, ...)
{
}
