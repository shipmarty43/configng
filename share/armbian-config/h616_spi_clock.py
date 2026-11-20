"""H616/H618 master-mode clock tree and the Armbian 6.18 sun6i/H3 selection rule."""
from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

MIN_HZ = 3_000
MAX_HZ = 100_000_000
PARENTS = ("osc24M", "pll-periph0", "pll-periph1", "pll-periph0-2x", "pll-periph1-2x")
CCU_DIVISORS = sorted({m << n for m in range(1, 17) for n in range(4)})
CDR_DIVISORS = sorted({1 << m for m in range(16)} | {2 * n for n in range(1, 257)})
EXAMPLE = (24_000_000, 600_000_000, 600_000_000, 1_200_000_000, 1_200_000_000)


def ceil_div(number, divisor):
    return (number + divisor - 1) // divisor


@dataclass(frozen=True)
class TransferClock:
    mclk: int
    divider: int
    field: str

    @property
    def effective(self):
        # The kernel's integer effective_speed_hz; a wire clock can be fractional.
        return self.mclk // self.divider

    def label(self, request):
        suffix = ""
        if self.mclk > request * self.divider:
            suffix = " (divider saturated: above request)"
        elif self.mclk < MIN_HZ * self.divider:
            suffix = " (below specified SCLK range)"
        return f"{self.effective} Hz  MCLK {self.mclk} / {self.divider}  {self.field}{suffix}"


class ClockTree:
    def __init__(self, mclk, parents, source):
        if not 0 < mclk <= 0xffffffff or any(not 0 < hz <= 0xffffffff for hz in parents):
            raise ValueError("Clock sources must be positive 32-bit Hz values")
        self.mclk = mclk
        self.parents = tuple(parents)
        self.source = source
        self.module_rates = sorted({parent // div for parent in parents for div in CCU_DIVISORS})

    def transfer(self, request):
        if not MIN_HZ <= request <= MAX_HZ:
            raise ValueError("H616 SPI request outside 3000..100000000 Hz")
        mclk = self.mclk
        if mclk < 2 * request:
            # clk_set_rate(2 * request); ccu_mp picks the highest achievable
            # module rate at or below target across all five parent clocks.
            if not self.module_rates:
                return None
            idx = bisect_right(self.module_rates, 2 * request)
            if idx:
                mclk = self.module_rates[idx - 1]
        div = ceil_div(mclk, 2 * request)
        if div <= 256:
            return TransferClock(mclk, 2 * div, f"CDR2={div - 1}")
        power = min(15, (ceil_div(mclk, request) - 1).bit_length())
        return TransferClock(mclk, 1 << power, f"CDR1={power}")

    def requests(self, limit):
        # Each change is at a divider boundary or a CCU reparent boundary.
        # Round the REQUEST up at fractional boundaries so selecting a row
        # actually reaches the displayed divider (e.g. 24 MHz / 14).
        edges = {MIN_HZ, self.mclk // 2 + 1}
        edges.update(ceil_div(self.mclk, div) for div in CDR_DIVISORS)
        edges.update(ceil_div(rate, 2) for rate in self.module_rates)
        previous = None
        for request in sorted(r for r in edges if MIN_HZ <= r <= limit):
            result = self.transfer(request)
            if result is None:
                continue
            key = (result, result.mclk > request * result.divider)
            if key != previous:
                yield request, result
            previous = key

    def silicon_settings(self, limit):
        # Keep one legal register configuration per distinct exact output.
        modules = {}
        for name, parent in zip(PARENTS, self.parents):
            for n in range(4):
                for m in range(16):
                    module = Fraction(parent, (m + 1) << n)
                    modules.setdefault(module, f"{name} M={m} N={n}")
        if not modules:
            modules[Fraction(self.mclk)] = "fixed MCLK"
        rates = {}
        for module, ccu in modules.items():
            for div in CDR_DIVISORS:
                if not MIN_HZ * div <= module <= limit * div:
                    continue
                if div == 1 or div > 512:
                    ccr = f"DRS=0 CDR1={div.bit_length() - 1}"
                else:
                    ccr = f"DRS=1 CDR2={div // 2 - 1}"
                rates.setdefault(module / div, f"{ccu}  {ccr}")
        return rates


def clock_tree(bus, mclk=None, parents=None, sysroot=Path("/sys")):
    if mclk is not None:
        return ClockTree(mclk, parents or (), "supplied MCLK" + (" and parents" if parents else "; CCU retunes unknown"))
    if parents is not None:
        raise ValueError("--parents requires --mclk")
    node = {"spi0": "spi@5010000", "spi1": "spi@5011000"}[bus]
    clk = sysroot / "kernel/debug/clk"
    try:
        compat = (sysroot / "firmware/devicetree/base/soc" / node / "compatible").read_bytes().split(b"\0")
        if b"allwinner,sun50i-h616-spi" not in compat or b"allwinner,sun8i-h3-spi" not in compat:
            raise ValueError("different controller")
        live = int((clk / bus / "clk_rate").read_text())
        if live <= 0:
            raise ValueError("invalid MCLK")
    except (OSError, ValueError):
        return ClockTree(EXAMPLE[0], EXAMPLE, "example clock tree (no verified live CCF snapshot)")
    try:
        rates = tuple(int((clk / parent / "clk_rate").read_text()) for parent in PARENTS)
        if any(rate <= 0 for rate in rates):
            raise ValueError("invalid parent rate")
    except (OSError, ValueError):
        rates = ()
    return ClockTree(live, rates, "live CCF snapshot" + ("" if rates else "; CCU retunes unknown"))


def estimate(tree, request):
    result = tree.transfer(request)
    return result.label(request) if result else "unknown (parent rates needed for retune)"


def print_grid(args, limit):
    bus = "spi1" if args.scope == "hat" else args.scope
    tree = clock_tree(bus, args.mclk, args.parents)
    title = f"{bus.upper()} | {tree.source} | initial MCLK {tree.mclk} Hz"
    print(title)
    if args.registers:
        print("Silicon SCLK in Hz (exact fractions); " +
              ("all CCU and CCR divisors" if tree.parents else "CCR divisors at the supplied or live MCLK"))
        settings = tree.silicon_settings(limit)
        for rate in sorted(settings, reverse=True):
            print(f"{rate}\t{settings[rate]}")
    else:
        if not args.menu:
            print(f"Linux requests {MIN_HZ}..{limit} Hz; request Hz -> predicted SCLK for this snapshot")
        for request, result in reversed(list(tree.requests(limit))):
            if args.menu and (result.mclk > request * result.divider or result.mclk < MIN_HZ * result.divider):
                continue
            print(f"{request}\t{result.label(request)}")
