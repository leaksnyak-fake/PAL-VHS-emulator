"""Run from project root: python -m unittest discover -s tests -v."""
import json
import math
import tempfile
import unittest
from pathlib import Path
from pal_vhs.params import Params, SPEC, SPECS, PRESETS
from pal_vhs.experience import CURATED, MACROS, help_for, set_macro, macro_position
from pal_vhs.__main__ import build_params
from types import SimpleNamespace


class ExperienceTests(unittest.TestCase):
    def test_every_control_has_meaningful_help(self):
        for spec in SPECS:
            with self.subTest(key=spec['key']):
                self.assertGreater(len(help_for(spec)), 40)

    def test_presets_have_valid_keys_and_unclamped_values(self):
        for name, values in PRESETS.items():
            with self.subTest(preset=name):
                self.assertTrue(values.keys() <= SPEC.keys())
                p = Params(**values)
                for key, value in values.items():
                    self.assertEqual(getattr(p, key), value)

    def test_curated_presets_keep_pal_format(self):
        for name in CURATED:
            p = Params(**PRESETS[name])
            self.assertEqual((p.fm_sync_mhz, p.fm_dev_mhz, p.rf_rate), (3.8, 1., '2x'))
            self.assertFalse(p.bypass_tape)
            self.assertEqual(p.tv_decoder, 'PAL-D')

    def test_easy_controls_are_monotonic_and_do_not_touch_other_families(self):
        for name, (_, _, mapping) in MACROS.items():
            p = Params(tracking=-.35, seed=42)
            before = p.to_dict()
            for amount in (0, 25, 50, 75, 100):
                set_macro(p, name, amount)
                self.assertEqual(macro_position(p, name), amount)
                for key in before.keys() - mapping.keys():
                    self.assertEqual(getattr(p, key), before[key])
                for key, (a, b) in mapping.items():
                    self.assertAlmostEqual(getattr(p, key), a+(b-a)*amount/100)

    def test_easy_damage_survives_json_round_trip(self):
        p = Params(**PRESETS[next(iter(CURATED))])
        for name in MACROS:
            set_macro(p, name, 67)
        p.update(dict(wr_travel=True, tracking=-.4))
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            path = Path(d)/'cassette.json'
            p.save(path)
            self.assertEqual(Params.load(path).to_dict(), p.to_dict())

    def test_bad_files_and_nonfinite_values_are_rejected(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                Params(tape_noise=value)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            path = Path(d)/'bad.json'
            path.write_text('[]')
            with self.assertRaises(ValueError):
                Params.load(path)

    def test_cli_can_select_curated_preset_and_override(self):
        name = 'PAL VHS / LP - long play'
        p = build_params(SimpleNamespace(params=None, preset=name, set=['tracking=-0.25']))
        self.assertEqual(p.tape_speed, 'LP')
        self.assertEqual(p.tracking, -.25)
        self.assertEqual(p.fm_sync_mhz, 3.8)


if __name__ == '__main__':
    unittest.main()
