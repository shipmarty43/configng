// SPDX-License-Identifier: GPL-2.0-only
/* Link the actual Armbian mixer and CSC code to bounded register windows. */
#include "sun8i_mixer.c"

struct regmap {
	u32 *words;
	size_t size;
	bool out_of_range;
};

int regmap_write(struct regmap *map, unsigned int reg, unsigned int val)
{
	if (reg % 4 || reg / 4 >= map->size) {
		map->out_of_range = true;
		return -ERANGE;
	}
	map->words[reg / 4] = val;
	return 0;
}

int regmap_bulk_write(struct regmap *map, unsigned int reg, const void *val, size_t count)
{
	const u32 *words = val;
	size_t i;

	for (i = 0; i < count; i++)
		if (regmap_write(map, reg + i * 4, words[i]))
			return -ERANGE;
	return 0;
}

int regmap_update_bits_base(struct regmap *map, unsigned int reg, unsigned int mask,
			    unsigned int val, bool *change, bool async, bool force)
{
	if (reg % 4 || reg / 4 >= map->size) {
		map->out_of_range = true;
		return -ERANGE;
	}
	return regmap_write(map, reg, (map->words[reg / 4] & ~mask) | (val & mask));
}

/* Decode the Q17 field from its 20-bit register representation.
 * Model the conversion on 10-bit samples and round to an 8-bit output.
 */
static int check_bars(const u32 *regs)
{
	static const u8 bars[][6] = {
		{   0,   0,   0,  16, 128, 128 }, { 255, 255, 255, 235, 128, 128 },
		{ 255, 255,   0, 210,  16, 146 }, {   0, 255, 255, 170, 166,  16 },
		{   0, 255,   0, 145,  54,  34 }, { 255,   0, 255, 106, 202, 222 },
		{ 255,   0,   0,  81,  90, 240 }, {   0,   0, 255,  41, 240, 110 },
	};
	int bar, row, col;

	if (regs[0] != 1 || regs[1] || regs[2] || regs[3])
		return -1;
	for (bar = 0; bar < ARRAY_SIZE(bars); bar++) {
		for (row = 0; row < 3; row++) {
			const u32 *coef = regs + 4 + row * 4;
			s64 sum = (s64)coef[3] << 17;

			for (col = 0; col < 3; col++)
				sum += (s64)sign_extend32(coef[col], 19) * bars[bar][col] * 4;
			if (((sum + (1 << 18)) >> 19) != bars[bar][row + 3])
				return -1;
		}
	}
	return 0;
}

int check_de33(void);
int check_de33(void)
{
	static u32 plane_regs[0x180000 / 4], blend_regs[0x20000 / 4];
	struct regmap planes = { .words = plane_regs, .size = ARRAY_SIZE(plane_regs) };
	struct regmap blend = { .words = blend_regs, .size = ARRAY_SIZE(blend_regs) };
	static const int channels[] = { 0, 6, 7, 1, 2, 8 };
	static struct drm_device drm;
	static struct drm_crtc crtc;
	static struct drm_crtc_state output;
	static struct drm_plane_state plane;
	static struct drm_atomic_state state;
	static struct __drm_crtcs_state cstate;
	static struct drm_encoder tv, hdmi;
	static struct drm_framebuffer fb;
	static const struct drm_format_info rgb = { .format = DRM_FORMAT_XRGB8888 };
	static const struct sun8i_layer_cfg cfg = { .de_type = SUN8I_MIXER_DE33 };
	static struct sun8i_layer layer;
	int pass, i;

	INIT_LIST_HEAD(&drm.mode_config.encoder_list);
	/* Both encoders are registered, only one is attached by each commit. */
	tv.encoder_type = DRM_MODE_ENCODER_TVDAC;
	tv.index = 1;
	hdmi.encoder_type = DRM_MODE_ENCODER_TMDS;
	list_add_tail(&hdmi.head, &drm.mode_config.encoder_list);
	list_add_tail(&tv.head, &drm.mode_config.encoder_list);
	crtc.dev = &drm;
	output.crtc = &crtc;
	cstate.new_state = &output;
	state.crtcs = &cstate;
	fb.format = &rgb;
	plane.crtc = &crtc;
	plane.fb = &fb;
	plane.state = &state;
	plane.visible = true;
	layer.cfg = &cfg;
	layer.regs = &planes;

	/* CVBS -> HDMI -> CVBS; preserve the unrelated blender bits. */
	for (pass = 0; pass < 3; pass++) {
		bool cvbs = pass != 1;
		u32 black = cvbs ? 0xff108080 : 0xff000000;

		output.encoder_mask = drm_encoder_mask(cvbs ? &tv : &hdmi);
		blend_regs[0x10fc / 4] = 3;
		sun8i_de33_set_blend_space(&blend, 0x1000, sun8i_de33_is_composite(&output));
		if (blend_regs[0x10fc / 4] != (cvbs ? 0x103 : 3) ||
		    blend_regs[0x1088 / 4] != black || blend_regs[0x1004 / 4] != black)
			return 1;
		for (i = 0; i < ARRAY_SIZE(channels); i++) {
			u32 *regs = plane_regs + (0x800 + channels[i] * 0x20000) / 4;

			layer.channel = channels[i];
			sun8i_csc_config(&layer, &plane);
			if (cvbs ? check_bars(regs) : regs[0] != 0)
				return 2;
		}
	}
	return planes.out_of_range || blend.out_of_range ? 3 : 0;
}
