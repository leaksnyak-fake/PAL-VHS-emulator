"""Offscreen widget regression checks when all runtime dependencies are installed."""
import importlib.util
import os
import unittest

READY = all(importlib.util.find_spec(m) for m in ('PySide6','scipy','cv2','numpy'))
if READY:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6 import QtWidgets as W
    from pal_vhs.gui import ParamPanel
    from pal_vhs.params import Params, SPECS


@unittest.skipUnless(READY, 'Needs PySide6, SciPy, NumPy and OpenCV')
class WidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = W.QApplication.instance() or W.QApplication([])

    def setUp(self):
        self.p = Params()
        self.panel = ParamPanel(self.p)

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()

    def test_switching_modes_preserves_values(self):
        before = self.p.to_dict()
        self.panel.mode_selector.setCurrentIndex(1)
        self.panel.mode_selector.setCurrentIndex(0)
        self.assertEqual(self.p.to_dict(), before)

    def test_every_advanced_widget_and_number_has_help(self):
        self.assertEqual(len(self.panel.ctl), len(SPECS))
        for w, number in self.panel.ctl.values():
            self.assertTrue(w.toolTip())
            if number:
                self.assertTrue(number.toolTip())

    def test_damage_undo_keeps_unrelated_slider_edits(self):
        self.panel.easy.damage('smear')
        self.panel.easy._macro('colour', 70)
        self.panel.easy.damage('undo')
        self.assertEqual(self.p.track_band, 0)
        self.assertAlmostEqual(self.p.chroma_delay_ns, 455)

    def test_preset_refreshes_both_modes_and_clears_undo(self):
        self.panel.easy.damage('crease')
        self.panel.apply_preset('PAL VHS / LP - long play')
        self.assertEqual(self.panel.easy.speed.currentText(), 'LP')
        self.assertEqual(self.p.tape_speed, 'LP')
        self.assertEqual(self.panel.easy.history, [])

    def test_search_by_key_and_reset(self):
        self.panel.search.setText('tb_jitter_ns')
        shown = [s['key'] for s, label, control in self.panel.rows if not control.isHidden()]
        self.assertEqual(shown, ['tb_jitter_ns'])
        self.panel.search.clear()
        self.assertTrue(all(control.isHidden() == (not self.panel._available(s['key'])) for s, _, control in self.panel.rows))

    def test_deck_button_preserves_tape_condition_and_undoes(self):
        self.p.tape_wear=.4
        self.panel.easy.deck.setCurrentText('Professional / SWP black mask')
        self.panel.easy._apply_deck()
        self.assertEqual(self.p.hs_mask_lines,4)
        self.assertEqual(self.p.tape_wear,.4)
        self.panel.easy.damage('undo')
        self.assertEqual(self.p.hs_mask_lines,0)
        self.assertEqual(self.p.tape_wear,.4)

    def test_legacy_controls_enable_only_in_legacy_mode(self):
        self.assertFalse(self.panel.ctl['hs_snow'][0].isEnabled())
        self.assertTrue(self.panel.ctl['hs_advance'][0].isEnabled())
        self.panel._emit('hs_model','legacy overlay')
        self.assertTrue(self.panel.ctl['hs_snow'][0].isEnabled())
        self.assertFalse(self.panel.ctl['hs_advance'][0].isEnabled())

    def test_current_snow_controls_are_visible_and_editable_in_rf_mode(self):
        self.panel.mode_selector.setCurrentIndex(1)
        self.panel.search.setText('snow')
        rows={s['key']:control for s,label,control in self.panel.rows}
        self.assertTrue(rows['hs_snow'].isHidden())
        self.assertFalse(rows['hs_residual_width_px'].isHidden())
        slider,_=self.panel.ctl['hs_residual_width_px']
        slider.setValue(11)  # minimum 1 + 11 slider steps = 12 pixels
        self.assertEqual(self.p.hs_residual_width_px,12)
        self.assertFalse(rows['hs_residual_jitter_px'].isHidden())
        slider,_=self.panel.ctl['hs_residual_jitter_px']
        slider.setValue(30)
        self.assertEqual(self.p.hs_residual_jitter_px,15.0)
        self.panel._emit('hs_model','legacy overlay')
        self.assertFalse(rows['hs_snow'].isHidden())
        self.assertTrue(rows['hs_residual_width_px'].isHidden())

    def test_easy_snow_toggle_and_strength_update_shared_params(self):
        self.panel.easy.snow_strength.setValue(70)
        self.assertAlmostEqual(self.p.hs_residual,.7)
        self.panel.easy.snow_motion.setChecked(False)
        self.assertEqual(self.p.hs_residual_motion,'Stationary')
        self.panel.easy.snow_motion.setChecked(True)
        self.assertEqual(self.p.hs_residual_motion,'Drift + jitter')
