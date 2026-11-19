import unittest
import numpy as np
from pal_vhs import consts as C, experience, pal
from pal_vhs.params import Params,PRESETS
from pal_vhs.headswitch import switch_line,rf_switch_envelope,pal_colour_rotation,apply_deck_profile,DECK_PROFILES
from pal_vhs.headswitch import add_switch_snow, residual_positions
from pal_vhs.dsp import fm_mod,fm_demod
from pal_vhs.vhs import Deck


class HeadSwitchTests(unittest.TestCase):
    def test_drift_plus_jitter_has_both_drift_and_jitter(self):
        p=Params(hs_residual_x=.4,hs_residual_motion='Drift + jitter',hs_residual_speed_px=0,hs_residual_jitter_px=15)
        pos=[residual_positions(p,720,0,i,1,quantize=False)[0] for i in range(40)]
        self.assertGreater(np.std(pos),5)                       # jitter alone moves the snow
        q=Params(hs_residual_x=.4,hs_residual_motion='Drift + jitter',hs_residual_speed_px=0,hs_residual_jitter_px=0)
        self.assertEqual(len({residual_positions(q,720,0,i,1,quantize=False)[0] for i in range(10)}),1)
        d=Params(hs_residual_x=.1,hs_residual_motion='Drift + jitter',hs_residual_speed_px=12,hs_residual_jitter_px=0)
        np.testing.assert_allclose(np.diff([residual_positions(d,720,0,i,1,quantize=False)[0] for i in range(4)]),[24,24,24])
        for i in (0,1,100,99999):
            self.assertTrue(0 <= residual_positions(p,720,0,i,1)[0] <= 711)

    def test_old_forward_back_settings_still_load(self):
        p=Params(hs_residual_motion='Forward/back steps',hs_residual_forward_px=5)
        self.assertEqual(p.hs_residual_motion,'Drift + jitter')

    def test_waveform_snow_has_requested_field_height_and_preserves_sync(self):
        for height in (1,2):
            for fi,L in enumerate(C.FIELD_LINES):
                p=Params(hs_residual=.8,hs_residual_width_px=15,hs_residual_height=height,
                         hs_residual_motion='Stationary',hs_residual_sweep_px=0)
                source=np.full(L*C.SPL,.2)
                out=add_switch_snow(source,p,fi,12).reshape(L,C.SPL)
                hit=np.any(out != .2,axis=1)
                self.assertEqual(hit.sum(),height)
                np.testing.assert_array_equal(out[:,:C.ACTIVE_START],.2)

    def test_waveform_snow_keeps_five_woven_rows_below_band(self):
        p=Params(hs_residual=1,hs_residual_bottom_px=5)
        bottoms=[]
        for fi,L in enumerate(C.FIELD_LINES):
            out=add_switch_snow(np.zeros(L*C.SPL),p,fi,0).reshape(L,C.SPL)
            last=np.where(np.any(out != 0,axis=1))[0].max()-C.ACTIVE_FIRST
            bottoms.append(2*last+fi)
        self.assertEqual(575-max(bottoms),5)

    def test_waveform_is_repeatable_but_breathes_between_fields(self):
        p=Params(hs_residual=1,hs_residual_motion='Stationary')
        source=np.zeros(313*C.SPL)
        a=add_switch_snow(source,p,0,0)
        np.testing.assert_array_equal(a,add_switch_snow(source,p,0,0))
        self.assertFalse(np.array_equal(a,add_switch_snow(source,p,0,1)))
        self.assertEqual(residual_positions(p,720,0,0,1),residual_positions(p,720,0,1,1))

    def test_waveform_bright_head_has_a_soft_decaying_tail(self):
        p=Params(hs_residual=1,hs_residual_width_px=60,hs_residual_motion='Stationary')
        profiles=[]
        for frame in range(40):
            out=add_switch_snow(np.zeros(313*C.SPL),p,0,frame).reshape(313,C.SPL)
            row=out[np.any(out != 0,axis=1)][0]
            x=int(C.ACTIVE_START+p.hs_residual_x*(720-60)*C.ACTIVE_LEN/720)
            profiles.append(row[x:x+90])
        mean=np.mean(profiles,axis=0)
        self.assertGreater(mean[8:25].mean(),mean[55:75].mean()*2)
        self.assertGreater(len(np.unique(mean)),20)

    def test_nominal_width_changes_waveform_duration(self):
        widths=[]
        for width in (8,15,40):
            p=Params(hs_residual=1,hs_residual_width_px=width,hs_residual_motion='Stationary')
            out=add_switch_snow(np.zeros(313*C.SPL),p,0,0)
            widths.append(np.count_nonzero(out))
        self.assertLess(widths[0],widths[1])
        self.assertLess(widths[1],widths[2])

    def test_snow_position_moves_but_is_seek_deterministic(self):
        p=Params(hs_residual=1,hs_residual_motion='Drift + jitter')
        positions=[residual_positions(p,720,0,i,1)[0] for i in range(10)]
        self.assertGreater(len(set(positions)),5)
        self.assertEqual(positions[4],residual_positions(p,720,0,4,1)[0])
        self.assertEqual(p.hs_jitter_us,0)

    def test_drift_sign_and_sweep(self):
        p=Params(hs_residual_x=.5,hs_residual_motion='Drift',hs_residual_speed_px=5,hs_residual_sweep_px=3)
        a=residual_positions(p,720,0,0,2)
        b=residual_positions(p,720,0,1,2)
        self.assertEqual(a[1]-a[0],3)
        self.assertEqual(b[0]-a[0],10)
        p.hs_residual_speed_px=-5
        self.assertEqual(residual_positions(p,720,0,1,1)[0]-a[0],-10)

    def test_moving_snow_reflects_without_width_clipping(self):
        p=Params(hs_residual_motion='Drift + jitter',hs_residual_speed_px=60,hs_residual_jitter_px=150)
        for i in (0,1,99,99999):
            self.assertTrue(all(0 <= x <= 711 for x in residual_positions(p,720,1,i,4)))

    def test_waveform_respects_bypass_off_legacy_and_output_mask(self):
        source=np.full(313*C.SPL,.2)
        for overrides in ({'bypass_tape':True},{'hs_model':'off'},{'hs_model':'legacy overlay'},{'hs_mask_lines':4}):
            p=Params(hs_residual=1,**overrides)
            np.testing.assert_array_equal(add_switch_snow(source,p,0,0),source)

    def test_snow_is_in_waveform_taps_before_tv_decode(self):
        from pal_vhs.pipeline import render_field
        p=Params(hs_residual=0,tape_noise=0,chroma_noise=0,dropout_rate=0,
                 hs_noise=0,hs_phase_deg=0,hs_shift_us=0,tb_jitter_ns=0,tb_wobble_ns=0,tb_skew_us=0)
        field=np.full((288,720,3),40,np.uint8)
        a,ta=render_field(field,0,0,p.to_dict(),True)
        p.hs_residual=.8
        b,tb=render_field(field,0,0,p.to_dict(),True)
        self.assertFalse(np.array_equal(ta['luma_demod'],tb['luma_demod']))
        self.assertFalse(np.array_equal(ta['comp_out'],tb['comp_out']))
        self.assertFalse(np.array_equal(a,b))

    def test_reference_profile_has_small_snow_without_jitter(self):
        p=apply_deck_profile(Params(),'Professional / narrow residual (user reference)')
        self.assertEqual((p.hs_residual_width_px,p.hs_residual_height,p.hs_residual_bottom_px),(9,1,5))
        self.assertEqual(p.hs_jitter_us,0)
        p=apply_deck_profile(p,'Budget 2-head / rough alignment')
        self.assertEqual((p.hs_residual_width_px,p.hs_residual_height),(15,2))

    def test_all_presets_have_zero_headswitch_jitter(self):
        self.assertEqual(Params().hs_jitter_us,0)
        for name,values in PRESETS.items():
            with self.subTest(preset=name):
                p=Params(**values)
                self.assertEqual((p.hs_jitter_us,p.hs_shift_var,p.hs_snow_jitter),(0,0,0))

    def test_pal_head_channel_phase_sequences(self):
        np.testing.assert_array_equal(pal_colour_rotation(8,0),np.zeros(8))
        np.testing.assert_allclose(pal_colour_rotation(8,1),-np.tile(np.arange(4),2)*np.pi/2)
        np.testing.assert_allclose(pal_colour_rotation(8,1,'legacy 90deg'),np.tile(np.arange(4),2)*np.pi/2)

    def test_switch_timing_and_later_switch(self):
        for L in C.FIELD_LINES:
            p=Params()
            self.assertEqual(switch_line(p,L,0,0),L+2-6.5)
            p.hs_advance=5
            self.assertEqual(switch_line(p,L,1,99),L+2-5)

    def test_rf_loss_is_local_at_both_sample_rates(self):
        p=Params(hs_noise=.9,hs_gap_us=5,hs_recovery_us=3)
        for os in (1,2):
            env=rf_switch_envelope(p,313,0,0,os)
            start=switch_line(p,313,0,0)*C.SPL*os
            self.assertTrue(np.all(env[:int(start)]==1))
            self.assertAlmostEqual(env[int(start+2*C.US*os)],.1,places=6)
            self.assertGreater(env[int(start+60*C.US*os)],.9999)

    def test_switch_off_removes_rf_interruption(self):
        self.assertTrue(np.all(rf_switch_envelope(Params(hs_model='off',hs_noise=1),313,0,0,2)==1))

    def test_deck_profile_preserves_tape_and_format(self):
        for name in DECK_PROFILES:
            p=apply_deck_profile(Params(tape_wear=.37,tape_speed='LP',wrinkle=.6,chroma_delay_ns=330),name)
            self.assertEqual((p.tape_wear,p.tape_speed,p.wrinkle,p.chroma_delay_ns),(.37,'LP',.6,330))
            self.assertEqual((p.fm_sync_mhz,p.fm_dev_mhz),(3.8,1))

    def test_nominal_pal_fm_frequencies(self):
        for os in (1,2):
            for volts,target in ((-.3,3.8e6),(.7,4.8e6)):
                f,e=fm_demod(fm_mod(np.full(20000,volts),3.8e6,1e6,C.FS*os),C.FS*os)
                self.assertLess(abs(np.median(f[2000:-2000])-target),10)
                self.assertLess(np.std(f[2000:-2000]),1000)

    def test_phase_jump_changes_carrier_not_amplitude(self):
        x=np.full(20000,.3)
        a=fm_mod(x,3.8e6,1e6,C.FS*2)
        b=fm_mod(x,3.8e6,1e6,C.FS*2,phase_start=10000,phase_jump=np.pi/2)
        np.testing.assert_array_equal(a[:10000],b[:10000])
        self.assertLessEqual(np.max(np.abs(b)),1)
        self.assertFalse(np.array_equal(a[10000:],b[10000:]))

    def test_healthy_switch_has_stable_step_without_shake(self):
        deck=Deck(Params(tb_jitter_ns=0,tb_wobble_ns=0,tb_skew_us=0))
        a=deck.timebase(313,0,0,np.random.default_rng(1))
        b=deck.timebase(313,0,99,np.random.default_rng(99))
        np.testing.assert_array_equal(a,b)
        self.assertEqual(len(np.unique(a)),2)

    def test_swp_black_preserves_sync_burst(self):
        p=Params(hs_mask_lines=4,tape_noise=0,chroma_noise=0,dropout_rate=0,tb_jitter_ns=0,tb_wobble_ns=0)
        comp=pal.encode_field(np.full((288,720,3),.5),0,0,p)
        out=Deck(p).process_field(comp,0,0).reshape(313,C.SPL)
        end=C.ACTIVE_FIRST+C.ACTIVE_LINES
        self.assertTrue(np.all(out[end-4:end,C.ACTIVE_START:C.ACTIVE_START+C.ACTIVE_LEN]==0))
        self.assertLess(out[end-2,:C.SYNC_W].min(),-.15)
        self.assertGreater(out[end-2,C.BURST_START:C.BURST_START+C.BURST_LEN].std(),.01)

    def test_playback_phase_does_not_change_record_fm_scope(self):
        p=Params(tape_noise=0,chroma_noise=0,dropout_rate=0,hs_phase_deg=0)
        comp=pal.encode_field(np.full((288,720,3),.5),0,0,p)
        a={};Deck(p).process_field(comp,0,0,a)
        p.hs_phase_deg=90
        b={};Deck(p).process_field(comp,0,0,b)
        np.testing.assert_array_equal(a['fm'],b['fm'])
        self.assertFalse(np.array_equal(a['tape'],b['tape']))
