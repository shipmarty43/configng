"""Compare the clock planner with the register space and sun6i transfer thresholds."""
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share/armbian-config"))
import h616_spi_clock as clk
import sx1262_spi as hat


class ClockTests(unittest.TestCase):
    def test_all_ccr_encodings_and_ccu_parents(self):
        model = clk.ClockTree(24_000_000, clk.EXAMPLE, "test")
        self.assertEqual(set(clk.CDR_DIVISORS),
                         {2**m for m in range(16)} | {2*(n+1) for n in range(256)})
        rates = sorted(model.silicon_settings(clk.MAX_HZ), reverse=True)
        self.assertEqual(rates[0], 100_000_000)
        self.assertEqual(len(rates), 6450)
        fixed = clk.ClockTree(24_000_000, (), "fixed").silicon_settings(clk.MAX_HZ)
        self.assertEqual(fixed[Fraction(24_000_000, 14)], "fixed MCLK  DRS=1 CDR2=6")
        self.assertIn(Fraction(24_000_000, 14), rates)
        self.assertIn(Fraction(24_000_000, 13 * 8 * 64), rates)
        self.assertTrue(all(clk.MIN_HZ <= v <= clk.MAX_HZ for v in rates))

    def test_driver_boundaries(self):
        model = clk.ClockTree(24_000_000, clk.EXAMPLE, "test")
        for request, field, divider in ((12_000_000, "CDR2=0", 2), (1_714_285, "CDR2=7", 16),
                                        (1_714_286, "CDR2=6", 14), (46_875, "CDR2=255", 512),
                                        (46_874, "CDR1=10", 1024), (3000, "CDR1=13", 8192)):
            with self.subTest(request=request):
                res = model.transfer(request)
                self.assertEqual((res.field, res.divider), (field, divider))
        self.assertIn("below specified", clk.estimate(model, 3000))
        self.assertEqual(model.transfer(16_000_000).effective, 15_000_000)
        self.assertEqual(model.transfer(100_000_000).effective, 100_000_000)
        self.assertEqual(model.transfer(100_000_000).mclk, 200_000_000)
        self.assertIsNone(clk.ClockTree(24_000_000, (), "fixed").transfer(16_000_000))

    def test_grid_rows_reproduce_every_clock_transition(self):
        # Small clock tree allows an exhaustive integer-Hz sweep, including a
        # CCU retune immediately above half of an odd initial module rate.
        model = clk.ClockTree(31_337, (31_337, 190_001, 370_001), "test")
        grid = dict(model.requests(50_000))
        for hz in range(3000, 50_001):
            rate = model.transfer(hz)
            if hz in grid:
                current = grid[hz]
            self.assertEqual(current, rate, hz)
        fast = clk.ClockTree(200_000_000, clk.EXAMPLE, "test")
        self.assertIn("above request", clk.estimate(fast, 3000))
        self.assertIn(6104, dict(fast.requests(10_000)))

    def test_live_clock_inputs(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            node = root/"firmware/devicetree/base/soc/spi@5011000"
            node.mkdir(parents=True)
            node.joinpath("compatible").write_bytes(b"allwinner,sun50i-h616-spi\0allwinner,sun8i-h3-spi\0")
            for name, hz in zip(("spi1", *clk.PARENTS), (24_000_000, *clk.EXAMPLE)):
                d = root/"kernel/debug/clk"/name
                d.mkdir(parents=True)
                (d/"clk_rate").write_text(str(hz))
            tree = clk.clock_tree("spi1", sysroot=root)
            self.assertIn("live", tree.source)
            self.assertEqual(tree.parents, clk.EXAMPLE)
            (root/"kernel/debug/clk/pll-periph1/clk_rate").unlink()
            self.assertIsNone(clk.clock_tree("spi1", sysroot=root).transfer(16_000_000))
            self.assertIn("example", clk.clock_tree("spi0", sysroot=root).source)

    def test_endpoint_bounds_default_and_legacy_clock(self):
        with TemporaryDirectory() as tmp:
            prop, setting = Path(tmp)/"cell", Path(tmp)/"hz"
            for dt, cap, default in ((100_000_000, 16_000_000, 2_000_000),
                                     (16_000_000, 16_000_000, 2_000_000),
                                     (2_000_000, 2_000_000, 2_000_000), (800_000, 800_000, 800_000)):
                prop.write_bytes(dt.to_bytes(4, "big"))
                self.assertEqual(hat.ceiling(prop), cap)
                self.assertEqual(hat.selected(cap, setting), default)
                for hz in (3000, 500_000, cap):
                    hat.save(str(hz), cap, setting)
                    self.assertEqual(hat.selected(cap, setting), hz)
                for bad in ("2999", str(cap + 1), "100000000", "0x80"):
                    with self.assertRaises(ValueError):
                        hat.save(bad, cap, setting)
                    self.assertEqual(hat.selected(cap, setting), cap)
                hat.save("default", cap, setting)
            prop.write_bytes((2999).to_bytes(4, "big"))
            with self.assertRaises(ValueError):
                hat.ceiling(prop)


if __name__ == "__main__":
    unittest.main()
