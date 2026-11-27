#ifdef A733
static int scenario;
static long deliver(int *done, unsigned long timeout) {
    unsigned n=chip.capture_channel, stride=n*64;
    assert(timeout == 1000 && (regs[PWM_CER/4] & BIT(n)) && supply && pin_active);
    if (scenario==1) return 0;
    if (scenario==2) return -ERESTARTSYS;
    unsigned edges[] = {1,2,1};
    for (int i=0; i<3 && !*done; i++) {
        regs[PWM_CISR/4] = (scenario==3 ? 3 : edges[i]) << (2*n);
        regs[(PWM_CRLR_BASE+stride)/4] = 600;
        regs[(PWM_CFLR_BASE+stride)/4] = 1800;
        assert(sunxi_pwm_handler(1,&chip)==IRQ_HANDLED);
    }
    assert(*done); time_ns += scenario == 4 ? 3000000 : 100000; return 1;
}
static void check_capture(struct pwm_device *d) {
    struct pwm_capture result;
    chip.config[2].bind_pwm=255;
    for (scenario=0; scenario<=4; scenario++) {
        int ret=sunxi_pwm_capture_a733(&chip,d,&result,1000);
        int expected[]={0,-ETIMEDOUT,-ERESTARTSYS,-EOVERFLOW,-ERANGE};
        assert(ret==expected[scenario]);
        if (!ret) { assert(result.period==100000); assert(result.duty_cycle==25000); }
        assert(!supply && !pin_active && chip.capture_channel==-1);
        assert(!regs[PWM_CER/4] && !regs[PWM_CIER/4] && regs[PWM_PCGR/4]==BIT(5));
    }
}
static void check_burst(struct pwm_device *d) {
    const unsigned counts[]={1,2,17,65536}; unsigned r=(PWM_PCR + 2*64)/4;
    for (unsigned i=0;i<4;i++) {
        struct pwm_state next={.period=100000,.duty_cycle=25000,.enabled=true};
        chip.config[2].pulse_count=counts[i];
        assert(sunxi_pwm_apply(&chip.pwm_chip,d,&next)==0);
        assert((regs[r] & (BIT(9)|BIT(10)))==(BIT(9)|BIT(10)));
        /* Hardware model consumes N-1 and clears START after its final cycle. */
        unsigned encoded=regs[r]>>16, pulses=0;
        do { pulses++; } while (encoded--);
        regs[r] &= ~BIT(10);
        assert(pulses==counts[i] && (regs[PWM_PER/4] & BIT(5)));
        assert(regs[(PWM_PPR+2*64)/4] == (2399U<<16 | 600));
        d->state=next; next.enabled=false;
        assert(sunxi_pwm_apply(&chip.pwm_chip,d,&next)==0); d->state=next;
        assert(regs[PWM_PER/4]==BIT(5));
    }
    assert(enables==4);
}
#endif
int main(void) {
    struct pwm_device d={.hwpwm=2,.chip=&chip.pwm_chip};
    chip.pwm_chip.dev=&fake_child.dev; regs[PWM_PER/4]=BIT(5);
    chip.config[2].bind_pwm=3; chip.config[2].dead_time=500;
#ifdef A733
    struct hw_data hw={.ccr_base_offset=PWM_CCR_BASE,.pcr_base_offset=PWM_PCR,
        .ppr_base_offset=PWM_PPR,.pwm_reg_uniform_offset=64,
        .pdzcr01_offset=PWM_PDZCR01,.pdzcr23_offset=PWM_PDZCR23,.pdzcr45_offset=PWM_PDZCR45};
    regs[PWM_PCGR/4]=BIT(5); regs[(PWM_PPR+5*64)/4]=0x02570078;
    chip.data=&hw; hw.per_offset=PWM_PER; hw.clk_gating_separate=1; chip.pwm_chip.npwm=10;
#endif
    assert(sunxi_pwm_config_dual(&chip.pwm_chip,&d,25000,100000,3)==0);
    assert((regs[PWM_PDZCR23/4] & 0xff01)==(12<<8|1));
#ifdef H618
    assert(sunxi_pwm_enable_dual(&chip.pwm_chip,&d,3)==0);
    assert(regs[PWM_PER/4]==(BIT(2)|BIT(3)|BIT(5)));
    assert(regs[(PWM_PCR_BASE+2*32)/4]&BIT(8)); assert(!(regs[(PWM_PCR_BASE+3*32)/4]&BIT(8)));
    sunxi_pwm_disable_dual(&chip.pwm_chip,&d,3);
    assert(regs[PWM_PER/4]==BIT(5) && !(regs[PWM_PDZCR23/4]&1));
    puts("H618: both pair gates close, opposite polarity and 12 dead ticks, PWM5 preserved");
#else
    struct pwm_state requested={.period=100000,.duty_cycle=25000,.enabled=true};
    assert(sunxi_pwm_apply(&chip.pwm_chip,&d,&requested)==0);
    assert(regs[PWM_PER/4]==(BIT(2)|BIT(3)|BIT(5)));
    assert(regs[(PWM_PCR+2*64)/4]&BIT(8)); assert(!(regs[(PWM_PCR+3*64)/4]&BIT(8)));
    d.state=requested; requested.enabled=false;
    assert(sunxi_pwm_apply(&chip.pwm_chip,&d,&requested)==0); d.state=requested;
    assert(regs[PWM_PER/4]==BIT(5) && !(regs[PWM_PDZCR23/4]&1) && regs[PWM_PCGR/4]==BIT(5));
    check_capture(&d); check_burst(&d);
    assert(regs[(PWM_PPR+5*64)/4]==0x02570078 && regs[PWM_PCGR/4]==BIT(5));
    puts("A733: 12 dead ticks; capture IRQ, timeout, interrupt and overrun cleanup; exact 1/2/17/65536 periods; fan gate preserved");
#endif
    return 0;
}
