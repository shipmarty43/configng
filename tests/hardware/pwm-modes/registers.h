#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
typedef uint64_t u64;
typedef int irqreturn_t;
enum pwm_polarity { PWM_POLARITY_NORMAL, PWM_POLARITY_INVERSED };
#define BIT(n) (1U << (n))
#define GENMASK(h,l) ((~0U << (l)) & (~0U >> (31-(h))))
#define SET_BITS(s,w,r,v) (((r) & ~(((1U<<(w))-1U)<<(s))) | (((v)&((1U<<(w))-1U))<<(s)))
#define do_div(n,d) ((n) /= (d))
#define div_u64(n,d) ((n)/(d))
#define div64_u64(n,d) ((n)/(d))
#define NSEC_PER_SEC 1000000000ULL
#define U32_MAX UINT32_MAX
#define PWM_BIND_NUM 2
#define PRESCALE_MAX 256
#define SUNXI_DIV_CLK NSEC_PER_SEC
#define SUNXI_PWM_BIND_DEFAULT 255
#define SUNXI_PWM_DUAL 2
#define PWM_PIN_STATE_ACTIVE "active"
#define PWM_PIN_STATE_SLEEP "sleep"
#define pr_err(...) ((void)0)
#define sunxi_err(...) ((void)0)
#define sunxi_warn(...) ((void)0)
#define sunxi_debug(...) ((void)0)
#define pwm_debug(...) ((void)0)
#define spin_lock_irqsave(l,f) ((void)0)
#define spin_unlock_irqrestore(l,f) ((void)0)
#define ERESTARTSYS 512
#define IRQ_HANDLED 1
#define IRQ_NONE 0
#define IS_ERR_OR_NULL(p) (!(p))
#define wake_up(p) ((void)0)
#define of_node_put(p) ((void)0)
#define put_device(p) ((void)0)
#define mutex_unlock(p) ((void)0)
#define mutex_lock_interruptible(p) 0
#define msecs_to_jiffies(t) (t)
#define reinit_completion(p) (*(p)=0)
#define complete(p) (*(p)=1)
struct device_node { int n; };
struct device { struct device_node *of_node; };
struct platform_device { struct device dev; };
struct pwm_state { u64 period, duty_cycle; bool enabled; enum pwm_polarity polarity; };
struct pwm_chip { int base, id, npwm; struct device *dev; };
struct pwm_device { unsigned int hwpwm; struct pwm_chip *chip; struct pwm_state state; void *chip_data; };
struct pwm_capture { u32 period, duty_cycle; };
struct group_pwm_config {int group_channel, group_run_count, pwm_period, pwm_polarity;};
struct hw_data {int per_offset, pcntr_base_offset, clk_gating_separate, has_hosc_clock; unsigned int ccr_base_offset, pcr_base_offset, ppr_base_offset, pwm_reg_uniform_offset;
                 unsigned int pdzcr01_offset, pdzcr23_offset, pdzcr45_offset; };
struct sunxi_pwm_chip {
    struct pwm_chip pwm_chip; struct hw_data *data;
    struct { unsigned bind_pwm, dead_time, pulse_count, clk_bypass_osc24m; } config[10];
    struct group_pwm_config group_config[10];
    unsigned group_ch, group_period, group_polarity;
    int irq, capture_channel, capture_done, capture_error, index;
    unsigned int high_ticks, low_ticks, capture_edge, cap_time[3];
    bool channel_first_boot_flag[10], channel_polarity_flag[10], resume_polarity_flag[10];
};
static struct sunxi_pwm_chip chip;
static struct sunxi_pwm_chip *to_sunxi_pwm_chip(struct pwm_chip *p) { return &chip; }
static struct platform_device fake_child;
static struct device_node node;
#define pwmchip_parent(p) (&fake_child.dev)
#define of_parse_phandle(p,k,n) (&node)
#define of_find_device_by_node(n) (&fake_child)
static u32 regs[512];
static unsigned int supply, pin_active, enables;
static u32 sunxi_pwm_readl(struct pwm_chip *p, unsigned r) { assert(r < sizeof(regs)); return regs[r/4]; }
static void sunxi_pwm_writel(struct pwm_chip *p, unsigned r, u32 v) {
    assert(r < sizeof(regs));
#ifdef A733
    if (r == PWM_PER && !(regs[r/4] & BIT(2)) && (v & BIT(2)) && chip.config[2].pulse_count) {
        assert((regs[(PWM_PCR+2*64)/4] & (BIT(9)|BIT(10))) == BIT(9));
        enables++;
    }
#endif
    if (r == PWM_CISR) regs[r/4] &= ~v; else regs[r/4] = v;
}
static void sunxi_pwm_set_reg(struct pwm_chip *p, unsigned r, unsigned s, unsigned w, unsigned v) {
    unsigned value = sunxi_pwm_readl(p,r);
    sunxi_pwm_writel(p,r,SET_BITS(s,w,value,v));
}
static int sunxi_pwm_pin_set_state(struct device *d, const char *s) { pin_active = !strcmp(s,"active"); return 0; }
#ifdef A733
static const unsigned sunxi_pwm_regs[] = {0x20,0x24,0x28,0x2c,0x30};
static const unsigned sunxi_pwm_pre_scal[][2] = {{0,1},{1,2},{2,4},{3,8},{4,16},{5,32},{6,64},{7,128},{8,256}};
static int sunxi_pwm_regulator_request(struct sunxi_pwm_chip *c, struct device *d, int n) { return 0; }
static int sunxi_pwm_regulator_enable(struct sunxi_pwm_chip *c,int n) { supply++; return 0; }
static int sunxi_pwm_regulator_disable(struct sunxi_pwm_chip *c,int n) { assert(supply); supply--; return 0; }
static int sunxi_pwm_a733(struct sunxi_pwm_chip *c) { return 1; }
#define spin_lock(p) ((void)0)
#define spin_unlock(p) ((void)0)
#define clk_get_rate(p) 24000000U
#define SUNXI_PWM_SINGLE 1
#define SUNXI_PWM_NORMAL 1
#define SUNXI_PWM_INVERSED 0
#define SUNXI_CLK_24M 24000000
#define SUNXI_CLK_100M 100000000
#define PWM_NUM_MAX 16
#define sunxi_pwm_regulator_release(p) assert(!"unexpected global regulator release")
static u64 time_ns;
#define ktime_get_ns() (time_ns)
static long deliver(int *done, unsigned long timeout);
#define wait_for_completion_interruptible_timeout(p,t) deliver(p,t)
#endif
