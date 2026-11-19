"""VHS (PAL) record -> tape -> playback model, working on the real sampled composite waveform.

RECORD
  composite --+-- low-pass + 4.43 MHz trap ----> luma --> pre-emphasis --> white/dark clip
              |                                          --> FM (3.8 MHz sync tip .. 4.8 MHz white)
              +-- band-pass 4.43 MHz +-0.9 MHz -> chroma --> heterodyne down to 626.95 kHz
                                                              (colour-under, per-line phase rotation)
  FM luma + colour-under are summed onto the tape (RF at 2x oversampling).
TAPE / HEAD
  RF level changes (wear, dropouts, tracking band, head switch), head bandwidth, additive noise.
PLAYBACK
  high-pass -> limiter/discriminator FM demod -> de-emphasis -> low-pass -> detail boost
  low-pass 1.2 MHz -> dropout compensator -> burst ACC -> heterodyne back up to 4.43 MHz
  time-base errors (line jitter, wobble, flagging, head-switch shift) displace luma and chroma-under
  output stage: cable low-pass, reflection, noise -> RCA composite.
"""
from __future__ import annotations
import numpy as np
from scipy import signal
from scipy.special import expit
from scipy.ndimage import gaussian_filter1d, maximum_filter1d
from . import consts as C
from .pal import basis, _BURST_ENV
from .headswitch import switch_line, pal_colour_rotation, rf_switch_envelope, add_switch_snow
from .dsp import (lp, hp, bp, notch, shelf, peak, run, run_chain, fm_mod, fm_demod, displace,
                  smooth_edges)

SPEEDS = {"SP": (1.0, 1.0, 1.0), "LP": (0.92, 1.25, 0.95), "EP": (0.82, 1.6, 0.9)}


class Deck:
    def __init__(self, p):
        self.p = p
        self.bwm, self.nm, self.cm = SPEEDS[p.tape_speed]
        self.os = 2 if p.rf_rate == "2x" else 1          # RF-section sample rate = os * FS
        FS2 = self.fs_rf = self.os * C.FS
        # record
        self.f_ysep = [lp(p.rec_luma_bw * 1e6 * self.bwm, 3), notch(C.FSC, 2.0)]
        self.f_cbp = bp(C.FSC - p.chroma_rec_bw * 1e6, C.FSC + p.chroma_rec_bw * 1e6, 2)
        self.f_pre = shelf(0.7e6, p.preemph_db)
        self.f_cu_rec = lp(1.4e6 * self.cm, 3)
        # tape / playback RF (2x rate)
        self.f_head = lp(p.head_bw * 1e6 * self.bwm ** 0.5, 3, FS2)
        self.f_peak = peak(p.head_peak_mhz * 1e6, p.head_peak_db, 1.2, FS2)
        self.cu_gain = 10 ** (p.cu_level_db / 20.0) / C.BURST_AMP   # unit = burst at 0.15 (old model)
        self.f_lhp = hp(1.4e6, 2, FS2)       # recorded FM spectrum starts ~1.3 MHz
        self.f_dem = lp(4.4e6, 3, FS2)
        self.f_alias = lp(7.0e6, 4, FS2) if self.os == 2 else None   # anti-alias before the 2:1 decimation
        self.f_env = lp(1.2e6, 2, FS2)
        self.f_cu_play = lp(C.FCU + p.chroma_play_bw * 1e6 * self.cm, 3, FS2)
        # playback baseband
        self.f_de = shelf(0.7e6, p.preemph_db, inverse=True)
        self.f_play_y = lp(p.play_luma_bw * 1e6 * self.bwm, 3)
        self.f_sharp = lp(1.0e6, 1)
        self.f_cup = bp(C.FSC - 1.1e6, C.FSC + 1.1e6, 2)
        self.f_cnoise = lp(C.FCU + p.chroma_play_bw * 1e6, 3)
        self.f_out = lp(p.out_bw * 1e6, 2)
        self.f_cdoc = lp(1.2e6, 3)
        self.calibration = {}
        for fi in (0,1):
            self._calibrate(fi)
            self.calibration[fi] = (self.burst_loss,self.dc,self.align)
        self.burst_loss,self.dc,self.align = self.calibration[0]
        self.cdel = p.chroma_delay_ns * C.FS / 1e9 - self.align   # samples; 0 ns = chroma aligned with luma

    def _up(self, x):
        return signal.resample_poly(x, 2, 1) if self.os == 2 else x

    def _calibrate(self, fi=0):
        """Measure the deck's own filter chains once (a few lines of test signal, milliseconds):
        burst_loss : burst-window rms / steady chroma rms. At 627 kHz the 2.3 us burst is only ~1.4 cycles
                     long, so the colour-under filters shave it. The ACC regulates on that shaved burst, so
                     without this the saturated chroma came out ~1.3x too strong.
        dc         : delay (samples) the burst has at the colour-under output -> ACC / gate windows follow it.
        align      : how much later the chroma arrives than the luma through the whole deck (samples).
                     Subtracted so that chroma_delay_ns = 0 really means chroma aligned with luma."""
        p = self.p
        L = 6
        n = np.arange(L * C.SPL)
        t = n / C.FS
        car = np.cos(TWO_PI * C.FSC * t + 0.3)
        line_rot = np.repeat(pal_colour_rotation(L,fi,p.cu_phase_model), C.SPL)
        lo = 2 * np.cos(TWO_PI * (C.FSC + C.FCU) * t + line_rot)
        b0, b1 = C.BURST_START, C.BURST_START + C.BURST_LEN

        def chroma(x):
            cb = run(self.f_cbp, x)
            cu = run(self.f_cu_rec, cb * lo)
            rf = self._up(cu) * self.cu_gain
            rf = run(self.f_head, rf)
            if self.f_peak is not None:
                rf = run(self.f_peak, rf)
            cp = run(self.f_cu_play, rf)[::self.os] / self.cu_gain
            cout = run(self.f_cup, cp * 2 * np.cos(TWO_PI * (C.FSC + C.FCU) * t + line_rot))
            return cp, cout

        def centroid(x, a, b):
            e = np.abs(signal.hilbert(x))[a:b] ** 2
            return float((np.arange(a, b) * e).sum() / e.sum())

        xb = np.zeros(L * C.SPL)
        for k in range(L):
            xb[k * C.SPL + b0:k * C.SPL + b1] = C.BURST_AMP * _BURST_ENV
        xb = xb * car
        cp_b, cout_b = chroma(xb)
        a0, a1 = (L - 1) * C.SPL + b0 - 30, (L - 1) * C.SPL + b1 + 90
        c_in = centroid(xb, a0, a1)
        self.dc = int(round(centroid(cp_b, a0, a1) - c_in))
        c_delay = centroid(cout_b, a0, a1) - c_in

        ln = (L - 1) * C.SPL
        yb = cp_b[ln + b0 + self.dc + 4:ln + b1 + self.dc - 4]
        cp_s, _ = chroma(C.BURST_AMP * car)
        ys = cp_s[ln + C.SPL // 2 - 150:ln + C.SPL // 2 + 150]
        self.burst_loss = float(np.sqrt((yb ** 2).mean()) / np.sqrt((ys ** 2).mean()))

        # luma path: smooth 0 -> 0.5 V edge through the real record -> FM -> tape -> demod -> playback chain
        e0 = ln + 500
        step = 0.5 * expit((n - e0) / 2.0)
        y = run(self.f_pre, run_chain(self.f_ysep, step))
        y = np.clip(y, p.dark_clip, p.white_clip)
        rf = fm_mod(self._up(y), p.fm_sync_mhz * 1e6, p.fm_dev_mhz * 1e6, self.fs_rf)
        rf = run(self.f_head, rf)
        if self.f_peak is not None:
            rf = run(self.f_peak, rf)
        f_inst, _ = fm_demod(run(self.f_lhp, rf), self.fs_rf)
        v = (f_inst - p.fm_sync_mhz * 1e6) / (p.fm_dev_mhz * 1e6) - 0.3
        v = run(self.f_alias, run(self.f_dem, v))[::self.os]
        v = run(self.f_play_y, run(self.f_de, v))

        def edge_c(x):
            d = np.diff(x[ln + 400:ln + 650])
            return float((np.arange(len(d)) * d).sum() / d.sum())
        y_delay = edge_c(v) - edge_c(step)
        self.align = c_delay - y_delay

    # ------------------------------------------------------------ mechanics
    def timebase(self, L, fi, frame_idx, rng):
        """Per-sample time displacement (in samples, + = later) of the played-back field."""
        p = self.p
        n = np.arange(L)
        t = frame_idx / 25.0 + fi * 0.02 + n * 64e-6
        ph = np.random.default_rng(p.seed + 77).uniform(0, TWO_PI, 4)
        dl = rng.normal(0, p.tb_jitter_ns, L)
        w = p.tb_wobble_ns
        dl = dl + w * (np.sin(TWO_PI * p.tb_wobble_hz * t + ph[0]) +
                       0.4 * np.sin(TWO_PI * 2.7 * p.tb_wobble_hz * t + ph[1]))
        dl = dl * (C.FS / 1e9)                                     # ns -> samples
        amp = 0.75 + 0.25 * np.sin(TWO_PI * 0.31 * (frame_idx / 25.0) + ph[2])
        dsr = np.random.default_rng([p.seed, frame_idx, fi, 11])
        sk_sign = dsr.choice([-1.0, 1.0]) if p.skew_random else 1.0
        hs_sign = dsr.choice([-1.0, 1.0]) if p.hs_random else 1.0
        dl = dl + sk_sign * p.tb_skew_us * C.US * amp * np.exp(-np.maximum(n - (C.ACTIVE_FIRST - 1), 0) / 7.0)
        grid = np.arange(L*C.SPL)
        displacement = np.interp(grid,(n+.5)*C.SPL,dl)
        if p.hs_model != "off":
            hs0 = switch_line(p,L,fi,frame_idx)
            shift = hs_sign*p.hs_shift_us*C.US*(1+p.hs_shift_var*np.sin(
                ph[3]+TWO_PI*p.hs_shift_rate*(frame_idx+.5*fi)/25))
            displacement += np.where(grid >= hs0*C.SPL,shift,0)
            if p.hs_jitter_us > 0:
                shake = dsr.normal(0,p.hs_jitter_us*C.US,L)
                displacement += np.where(grid >= hs0*C.SPL,np.repeat(shake,C.SPL),0)
        return displacement

    def _profiles(self, L, fi, frame_idx):
        """Per-line (0..1) strength of the tracking band and of the wrinkle, drifting with the frame number."""
        p = self.p
        n = np.arange(L)
        tr, wr = np.zeros(L), np.zeros(L)

        def bump(c, half):
            d = np.abs(((n - c + L / 2) % L) - L / 2)
            return 0.5 - 0.5 * np.cos(np.pi * np.clip(1 - d / half, 0, 1))
        if p.track_band > 0:
            t_ = frame_idx + 0.5 * fi
            if p.track_accel > 1e-3:      # slow at the top, faster near the bottom, same average speed over a pass
                ph_ = (t_ * p.track_speed) % L
                x_ = L * np.expm1(p.track_accel * ph_ / L) / np.expm1(p.track_accel)
            else:
                x_ = t_ * p.track_speed
            x_ += p.track_wobble * (np.sin(t_ / 5.0) + 0.5 * np.sin(t_ / 11.3 + 1.0))
            tr = bump((x_ + 40.0) % L, 10 + 22 * p.track_band)
        if p.wrinkle > 0:
            cnt = max(int(p.wrinkle_count), 1)
            gap = p.wrinkle_gap if p.wrinkle_gap > 0 else float(C.ACTIVE_LINES) / cnt
            for i in range(cnt):                           # several creases at once, `gap` lines apart
                c0 = p.wrinkle_pos * L + i * gap + frame_idx * p.wrinkle_drift + fi * p.wrinkle_drift * 0.5
                wr = np.maximum(wr, bump(c0 % L, max(p.wrinkle_height / 2.0, 1.0)))
        return tr, wr

    @staticmethod
    def _band_h(wd, li):
        """Number of consecutive duplicated lines around line li (the band's height in lines)."""
        a = b = li
        while a > 0 and wd[a - 1] > 0.02:
            a -= 1
        while b < len(wd) - 1 and wd[b + 1] > 0.02:
            b += 1
        return b - a + 1

    def _cu_glitch(self, L, fi, frame_idx):
        """Per-line colour-under phase offset (rad) and gain. Two parts: a slow soft banding (chroma_band) and
        episodes of lost colour lock (cu_glitch). Through the PAL-D decoder a carrier phase error mostly shows
        as saturation loss, so the visible result is bands of faded / over-saturated colour."""
        p = self.p
        ph, gain = np.zeros(L), np.ones(L)
        alt = 1.0   # a constant carrier phase error: PAL-D turns it into saturation loss; alternating it only gives stripes
        if p.chroma_band > 0:
            rb = np.random.default_rng([p.seed, frame_idx // 3, 7773])
            b1 = gaussian_filter1d(rb.normal(0, 1, L), 7.0) * 2.8
            b2 = gaussian_filter1d(rb.normal(0, 1, L), 3.0) * 1.6
            ph = ph + alt * p.chroma_band * 0.30 * np.clip(b1 + 0.5 * b2, -2, 2)
            gain = gain * (1.0 + p.chroma_band * 0.20 * np.clip(0.7 * b1 + 0.5 * b2, -2, 2))
        if p.cu_glitch > 0:
            per, ln = int(p.cu_glitch_period), int(p.cu_glitch_len)
            k = frame_idx // per
            r = np.random.default_rng([p.seed, k, 7771])
            start = k * per + int(r.integers(0, max(1, per - ln)))
            t = frame_idx + 0.5 * fi - start
            if 0 <= t < ln:
                s = np.sin(np.pi * t / ln) ** 0.7                            # ramps in and out
                rf = np.random.default_rng([p.seed, frame_idx // 2, 7772])
                bands = np.clip(gaussian_filter1d(rf.normal(0, 1, L), 10.0) * 5.0, -1, 1)
                cast = r.uniform(0.5, 1.0) * (1 if r.random() < 0.5 else -1)
                ph = ph + s * p.cu_glitch * 0.7 * np.clip(0.7 * bands + cast * (0.5 + 0.5 * np.sin(2 * np.pi * t / ln)), -1, 1)   # |phase| <= ~63 deg: fades colour, never inverts it
                gain = gain * (1.0 + 1.8 * s * p.cu_glitch * (0.5 + 0.5 * np.abs(bands)))
        return ph, gain

    @staticmethod
    def _band_h(wd, li):
        """Number of consecutive duplicated lines around line li (the band's height in lines)."""
        a = b = li
        while a > 0 and wd[a - 1] > 0.02:
            a -= 1
        while b < len(wd) - 1 and wd[b + 1] > 0.02:
            b += 1
        return b - a + 1

    @staticmethod
    def _ss(x):
        x = np.clip(x, 0.0, 1.0)
        return x * x * (3.0 - 2.0 * x)

    def wrinkle_travel(self, L, fi, frame_idx):
        """Travelling creases that run down the picture, modelled on how real ones move (measured on a capture of
        damaged SP tape):
          * the speed is not constant: slow at the top, up to ~1.5-2x faster near the bottom (wr_accel), plus a slow
            wobble (wr_wobble);
          * a crease starts thin and thickens over wr_rise frames, stays the same height, then thins out again over
            the lower part of the picture and can vanish (wr_shrink);
          * the top edge fades in softly, the bottom edge ends sharply (wr_soft);
          * thin satellite creases travel with the main one (wr_sat);
          * the white part's flicker is smooth in time, not independent noise every field.
        Returns (dup, white, top, colour_loss): per-line weight of the line duplication, of the white part, the
        first line of the band each line belongs to (-1 = none) and the weight of colour loss. With wr_count N > 1
        an event is a train of N bands that replace each other (wr_hold frames). The schedule depends only on
        (seed, event, band, cycle), so any frame can be rendered on its own."""
        p = self.p
        n = np.arange(L, dtype=float)
        w, ww, top, cl = np.zeros(L), np.zeros(L), np.full(L, -1.0), np.zeros(L)
        per = max(int(p.wr_period), 10)
        hmax = max(p.wr_hmax, p.wr_hmin)
        cnt = max(int(p.wr_count), 1)
        spd = max(p.wr_speed, 0.5)
        A = float(C.ACTIVE_LINES)
        g = p.wr_gap if p.wr_gap > 0 else A / cnt
        Lc = max(cnt * g, A + hmax + 4) if cnt > 1 else A + hmax + 4              # one slot's cycle length (lines)
        hold = float(p.wr_hold) if cnt > 1 else 0.0
        acc = max(float(p.wr_accel), 0.0)
        travel = hold + (cnt * g + Lc) / (0.5 * spd) + (A + hmax + 8) / (0.5 * spd)
        k0 = max(0, int((frame_idx - travel) // per) - 1)

        def add(c, h, hw, hw_off, fl, lose_col, wgt=1.0):
            nonlocal w, ww, top, cl
            st = 1.0 + p.wr_soft * 0.5 * h                                      # soft top edge
            sb = 1.0 + p.wr_soft * 0.08 * h                                     # crisp bottom edge
            d = n - c
            half = h / 2.0
            wk = np.clip(np.where(d < 0, (half + d) / st, (half - d) / sb) + 0.5, 0.0, 1.0) * wgt
            d2 = n - (c - half + hw / 2.0 + hw_off)
            wwk = np.clip(np.where(d2 < 0, (hw / 2.0 + d2) / st, (hw / 2.0 - d2) / sb) + 0.5, 0.0, 1.0) * fl * wgt
            sel = wk > w
            top[sel] = c - half
            sel2 = (wwk > ww) & (top < 0)
            top[sel2] = c - half
            w = np.maximum(w, wk)
            ww = np.maximum(ww, wwk)
            if lose_col:
                cl = np.maximum(cl, np.maximum(wk, wwk))

        for k in range(k0, frame_idx // per + 1):
            r = np.random.default_rng([p.seed, k, 6161])
            start0 = k * per + int(r.integers(0, max(1, int(per * 0.6))))
            sp = spd * r.uniform(0.7, 1.3)
            t = frame_idx + 0.5 * fi - start0                                    # field time in frames
            if t < 0:
                continue
            for i in range(cnt):
                u = t * sp - i * g                                               # distance run by this slot
                if u < 0:
                    continue
                last = max(0.0, (hold * sp - i * g) // Lc) if cnt > 1 else 0.0  # last cycle that may start
                cyc = min(float(u // Lc), last)
                x = u - cyc * Lc                                                 # linear distance within the cycle
                ri = np.random.default_rng([p.seed, k, i, int(cyc), 6162])
                # analog position: slow start, faster toward the bottom, normalised to the same total travel
                pos = Lc * (np.expm1(acc * x / Lc) / np.expm1(acc) if acc > 1e-3 else x / Lc)
                tl = x / sp                                                      # frames since the band entered
                Tw = ri.uniform(14.0, 40.0)
                ph1, ph2 = ri.uniform(0, 2 * np.pi, 2)
                pos += p.wr_wobble * (np.sin(2 * np.pi * tl / Tw + ph1) + 0.5 * np.sin(2 * np.pi * tl / (Tw * 2.3) + ph2))
                h0 = ri.uniform(p.wr_hmin, hmax)
                rise = 0.35 + 0.65 * self._ss(tl / p.wr_rise) if p.wr_rise > 0 else 1.0
                s_k = p.wr_shrink * ri.uniform(0.4, 1.4)
                fall = max(0.0, 1.0 - s_k * self._ss((pos / A - 0.5) / 0.5))      # constant, then thins near the bottom
                h = h0 * rise * fall
                if h < 0.6:
                    continue
                lose_col = ri.random() < p.wr_chroma_loss
                Tf = ri.uniform(5.0, 14.0)
                f1, f2 = ri.uniform(0, 2 * np.pi, 2)
                fs = 0.5 + 0.5 * (0.6 * np.sin(2 * np.pi * (t + 0.5 * fi) / Tf + f1) + 0.4 * np.sin(2 * np.pi * (t + 0.5 * fi) / (Tf * 0.37) + f2))
                jit = np.random.default_rng([p.seed, k, i, int(cyc), int(2 * frame_idx + fi), 6163]).random()
                fl = 1.0 - p.wr_flicker * np.clip(0.75 * (1.0 - fs) + 0.25 * jit, 0.0, 1.0)
                c = C.ACTIVE_FIRST + (h / 2 if p.wr_full_entry else -h / 2) + pos
                hw = (p.wr_white_h * rise * fall if p.wr_white_h > 0 else h)
                hw = min(hw, h) if p.wr_white_h <= 0 else hw
                if c - h / 2 <= C.ACTIVE_FIRST + C.ACTIVE_LINES:
                    add(c, h, hw, 0.0, fl, lose_col)
                # thin satellites that move with the main crease
                for _ in range(min(3, int(ri.poisson(1.6 * p.wr_sat)))):
                    off = (1 if ri.random() < 0.6 else -1) * ri.uniform(1.0, 2.2) * h
                    hs = max(h * ri.uniform(0.25, 0.5), 1.5)
                    cs = c + off
                    if cs - hs / 2 <= C.ACTIVE_FIRST + C.ACTIVE_LINES:
                        add(cs, hs, hs, 0.0, fl * ri.uniform(0.5, 0.9), lose_col, 0.85)
        w[:C.ACTIVE_FIRST] = 0.0                                                # never touch sync / blanking lines
        ww[:C.ACTIVE_FIRST] = 0.0
        cl[:C.ACTIVE_FIRST] = 0.0
        return w, ww, top, cl

    NOISE_TILT_MHZ = 6.0

    def _tilt_noise(self, wn):
        """Head/tape noise is not white: the head differentiates, so it rises with frequency (and the 5 MHz
        resonance adds to it). First-order high-pass tilt, normalised to unchanged level at the 4.3 MHz
        carrier. Its main visible effect is the demodulator's average frequency when the carrier is lost:
        the snow comes out bright grey instead of black."""
        if not self.NOISE_TILT_MHZ:
            return wn
        b, a = signal.butter(1, self.NOISE_TILT_MHZ * 1e6, "high", fs=self.fs_rf)
        g = abs(signal.freqz(b, a, [4.3e6], fs=self.fs_rf)[1][0])
        return signal.lfilter(b, a, wn) / g

    def _click_tails(self, v2):
        """FM clicks (carrier lost for an instant -> the phase slips 2*pi) are 1 V*us pulses, far outside the
        picture range. The deck's video stages smear them over a few us: a bright (or black) head followed by
        a fading tail -> the long white/black dashes of tracking 'snow'. Only |v| > 2.5 V is touched, so
        normal video never sees this."""
        big = np.where(np.abs(v2) > 2.5, v2, 0.0)
        if not big.any():
            return v2
        a = np.exp(-1.0 / (self.CLICK_TAU_US * 1e-6 * self.fs_rf))
        return v2 + self.CLICK_GAIN * signal.lfilter([1 - a], [1, -a], big)

    CLICK_TAU_US = 1.3
    CLICK_GAIN = 1.2

    def _tracking_severity(self, L, fi, frame_idx, rng):
        """0..1 per line: how far the head is off the track. The head-to-track error grows from one end of
        the picture to the other (tape-path tilt), and the knob moves where it is smallest: knob < 0 keeps the
        top tracked and loses the bottom first, knob > 0 the opposite. Full snow at |knob| -> 1."""
        k = float(self.p.tracking)
        y = np.clip((np.arange(L) - C.ACTIVE_FIRST) / float(C.ACTIVE_LINES), 0.0, 1.0)
        u = y if k < 0 else 1.0 - y                          # 1 at the badly tracked end
        err = abs(k) * (2.1 if k < 0 else 1.5) * (0.25 + 0.75 * u)
        sev = np.clip((err - 0.3) / 0.7, 0.0, 1.0)
        sev = sev * sev * (3 - 2 * sev)                      # smoothstep: soft edge, not a hard band
        return np.clip(sev * rng.uniform(0.75, 1.0, L), 0.0, 1.0)

    def line_warp(self, tape, L, fi, frame_idx):
        """Tape-speed disturbance (tracking band smear, wrinkle). Each affected line is re-read from the tape
        stream at its own speed a (1 = nominal), start offset b and source line r:
            out_line[k](n) = tape( r[k]*SPL + b[k] + a[k]*n )
        a != 1 stretches/compresses the line AND scales every frequency on it, so the FM carrier moves
        (a > 1: carrier up -> white, a < 1: down -> black) and the 627 kHz colour-under leaves its filter
        (chroma lost). r[k] repeating gives duplicated lines; the head catches up afterwards by skipping."""
        p = self.p
        tr, wr = self._profiles(L, fi, frame_idx)
        sm = p.track_smear * p.track_band * tr
        if max(sm.max(), wr.max()) < 0.03:
            return tape
        rng = np.random.default_rng([p.seed, frame_idx, fi, 41])
        os_ = self.os
        SPLo = C.SPL * os_
        speed = np.maximum(0.07 * sm, p.wrinkle_speed_pct / 100.0 * wr)
        shift = np.maximum(3.0 * sm, p.wrinkle_shift_us * wr) * C.US * os_
        stretch = 1.0 + np.maximum(0.9 * sm, (p.wrinkle_stretch - 1.0) * wr)
        def ar(rho):                                                     # unit-variance AR(1): neighbouring lines agree
            return signal.lfilter([np.sqrt(1 - rho * rho)], [1, -rho], rng.normal(0, 1, L))
        z = ar(0.88)
        a = np.clip(1.0 + speed * np.clip(z, -2.5, 2.5), 0.3, 2.2)
        b = ar(0.6) * shift
        ramp = np.clip(ar(0.7), -2, 2) * np.minimum(1.5 * speed + 0.1 * (speed > 0), 0.8)
        w = np.maximum(sm, wr)
        lag, r = 0.0, np.arange(L, dtype=float)
        for k in range(8, L):                                            # keep the vertical interval stable
            if w[k] > 0.03:
                lag += 1.0 - 1.0 / stretch[k]
            else:
                lag = max(0.0, lag - 0.5)                                 # head skips lines to catch up
            r[k] = k - lag
        ri = np.clip(np.rint(r), 0, L - 1).astype(int)
        hit = np.nonzero(((w > 0.03) | (ri != np.arange(L))) & (np.arange(L) >= 8))[0]
        out = tape.copy()
        grid = np.arange(len(tape), dtype=float)
        nn = np.arange(SPLo, dtype=float)
        for k in hit:
            # speed drifts along the line (ramp) -> brightness/stretch changes along a streak
            tau = ri[k] * SPLo + b[k] + a[k] * (nn + ramp[k] * (nn * nn / (2.0 * SPLo) - nn / 2.0))
            out[k * SPLo:(k + 1) * SPLo] = np.interp(tau, grid, tape, left=tape[0], right=tape[-1])
        return out

    def rf_envelope(self, L, fi, frame_idx, rng):
        """RF level of the tape signal at the 2x rate (1.0 = nominal)."""
        p = self.p
        os_ = self.os
        N2 = L * C.SPL * os_
        env = np.full(N2, 1.0 - 0.5 * p.tape_wear)
        self._wr_fac = np.ones(L)
        # dropouts
        ev = rng.poisson(p.dropout_rate / 2.0)
        for _ in range(ev):
            li = rng.integers(3, L)
            st = li * C.SPL + rng.integers(0, C.SPL)
            ln = int(np.clip(rng.lognormal(np.log(p.dropout_len_us), 0.5), 1, 90) * C.US)
            a, b = st * os_, min(st * os_ + ln * os_, N2)
            if b - a > 8:
                env[a:b] *= 1 - p.dropout_depth * smooth_edges(b - a, 15 * os_)
        # tracking-noise band drifting through the picture
        tr, wr = self._profiles(L, fi, frame_idx)
        if p.track_band > 0:
            prof = tr * rng.uniform(0.6, 1.0, L)
            env *= np.repeat(1 - 0.6 * p.track_band * prof, C.SPL * os_)
        if p.tracking != 0:                                 # manual tracking misadjustment
            env *= np.repeat(10.0 ** (-1.4 * self._tracking_severity(L, fi, frame_idx, rng)), C.SPL * os_)   # dB-wise head loss, to ~-28 dB
        if p.wrinkle > 0:                                   # head lift inside the crease
            r2 = np.random.default_rng([p.seed, frame_idx, fi, 31])
            self._wr_fac = 1 - 0.85 * p.wrinkle * wr * r2.uniform(0.3, 1.0, L)
            env *= np.repeat(self._wr_fac, C.SPL * os_)
        # head-switch noise burst at the start of the switching line and a little after
        if p.hs_model == "RF switch":
            env *= rf_switch_envelope(p,L,fi,frame_idx,os_)
        elif p.hs_model == "legacy overlay" and p.hs_noise > 0:
            li = L - p.hs_lines
            for k, g in ((0, 1.0), (1, 0.35)):
                a = (li + k) * C.SPL * os_
                ln = int(14 * C.US * os_)
                env[a:a + ln] *= 1 - min(p.hs_noise * g, 0.97) * smooth_edges(ln, 40)
        return env

    def burst_phase(self, cout, dc, fi, frame_idx, L):
        """Per-line phase error (rad) of the up-converted burst vs the PAL reference,
        smoothed by the APC loop. Static offset is removed completely, fast errors only partly."""
        sn, cs, sw = basis(frame_idx, fi)
        fs_, fc_ = sn.reshape(-1), cs.reshape(-1)
        N = len(cout)
        n = np.arange(7, L)
        k = np.arange(C.BURST_START + 6, C.BURST_START + C.BURST_LEN - 6)
        pos = np.rint(n[:, None] * C.SPL + k[None, :] + dc[n * C.SPL][:, None]).astype(int)
        pos = np.clip(pos, 0, N - 1)
        x = (cout[pos] * 2 * fs_[pos]).mean(axis=1)
        y = (cout[pos] * 2 * fc_[pos]).mean(axis=1)
        ref = np.where(sw[n] > 0, np.deg2rad(135.0), np.deg2rad(225.0))
        e = np.angle((x + 1j * y) * np.exp(-1j * ref))
        med = np.angle(np.mean(np.exp(1j * e)))
        dyn = np.angle(np.exp(1j * (e - med)))
        a = self.p.apc_speed
        dyn_s = signal.lfilter([a], [1, -(1 - a)], dyn, zi=[(1 - a) * 0.0])[0]
        full = np.empty(L)
        full[7:] = med + dyn_s
        full[:7] = full[7]
        return full

    def doc_chroma(self, cout, bad, fi, frame_idx):
        """Replace chroma inside `bad` with the colour of the nearest good line above.
        The line above is demodulated to U and (sign-corrected) V, then modulated again onto
        this line's subcarrier phase and V-switch sign, so hue and saturation are preserved."""
        sn, cs, sw = basis(frame_idx, fi)
        fs_, fc_ = sn.reshape(-1), cs.reshape(-1)
        s_line = np.repeat(sw, C.SPL)
        U = run(self.f_cdoc, cout * 2 * fs_)
        V = run(self.f_cdoc, cout * 2 * fc_) * s_line
        todo = bad.copy()
        for _ in range(4):                       # dropouts spanning several lines
            if not todo.any():
                break
            take = todo & ~np.roll(todo, C.SPL)
            U = np.where(take, np.roll(U, C.SPL), U)
            V = np.where(take, np.roll(V, C.SPL), V)
            todo &= ~take
        fix = bad & ~todo
        return np.where(fix, U * fs_ + V * s_line * fc_, cout)

    # ------------------------------------------------------------ the tape path
    def process_field(self, comp, fi, frame_idx, taps=None):
        """comp: (L, SPL) composite from the encoder. Returns played-back composite stream."""
        p = self.p
        L = comp.shape[0]
        self.burst_loss,self.dc,self.align = self.calibration[fi]
        self.cdel = p.chroma_delay_ns*C.FS/1e9-self.align
        N = L * C.SPL
        rng = np.random.default_rng([p.seed, frame_idx, fi, 5])
        x = comp.reshape(-1)
        t = np.arange(N) / C.FS
        line_rot = np.repeat(pal_colour_rotation(L,fi,p.cu_phase_model), C.SPL)

        # ===================== RECORD =====================
        y = run_chain(self.f_ysep, x)
        y = run(self.f_pre, y)
        y = np.clip(y, p.dark_clip, p.white_clip)
        y2 = self._up(y)
        fm = fm_mod(y2,p.fm_sync_mhz*1e6,p.fm_dev_mhz*1e6,self.fs_rf)

        cb = run(self.f_cbp, x)
        lo = 2 * np.cos(TWO_PI * (C.FSC + C.FCU) * t + line_rot)
        cu = run(self.f_cu_rec, cb * lo)                      # colour-under @ 626.95 kHz
        cu2 = self._up(cu) * self.cu_gain

        tape = fm + cu2                                       # what the heads put on the tape
        # Playback head mismatch affects the off-tape carrier, not the record-FM
        # scope tap. Keep colour-under phase separate from luminance FM phase.
        if p.hs_model == "RF switch" and p.hs_phase_deg > 0:
            start = switch_line(p,L,fi,frame_idx)*C.SPL*self.os
            switched_fm = fm_mod(y2,p.fm_sync_mhz*1e6,p.fm_dev_mhz*1e6,self.fs_rf,
                                phase_start=start,
                                phase_jump=np.deg2rad(p.hs_phase_deg)*(1 if fi == 0 else -1))
            tape += switched_fm-fm
        tape = self.line_warp(tape, L, fi, frame_idx)          # tape-speed disturbance (tracking / wrinkle)

        # ===================== TAPE / HEAD =====================
        env = self.rf_envelope(L, fi, frame_idx, rng)
        rf = tape * env
        wn = rng.normal(0, p.tape_noise * self.nm * np.sqrt(self.os / 2.0), len(rf))      # same density at either rate
        rf = rf + self._tilt_noise(wn)
        rf = run(self.f_head, rf)
        if self.f_peak is not None:
            rf = run(self.f_peak, rf)

        # ===================== PLAYBACK: luma =====================
        lum_rf = run(self.f_lhp, rf)
        f_inst, envd = fm_demod(lum_rf, self.fs_rf)
        v2 = (f_inst - p.fm_sync_mhz * 1e6) / (p.fm_dev_mhz * 1e6) - 0.3
        v2 = self._click_tails(v2)
        v2 = run(self.f_dem, v2)
        v2 = run(self.f_alias, v2)
        yv = v2[::self.os]
        yv = run(self.f_de, yv)
        yv = run(self.f_play_y, yv)
        if p.sharpen > 0:
            hf = yv - run(self.f_sharp, yv)
            yv = yv + p.sharpen * 0.5 * np.tanh(2.0 * hf) * 1.0

        # ===================== PLAYBACK: colour-under =====================
        cp = run(self.f_cu_play, rf)[::self.os] / self.cu_gain      # colour-under amp makes up the record level
        if p.chroma_noise > 0:
            cp = cp + run(self.f_cnoise, rng.normal(0, p.chroma_noise * 2.7, N))

        yv_base, cp_base = yv.copy(), cp.copy()                  # state before the overlay effects (wrinkle layer)
        # dropout compensator: envelope below 50 % -> previous line (luma), mute chroma
        envl = run(self.f_env, envd)[::self.os]
        med = np.median(envl)
        bad = maximum_filter1d((envl < 0.5 * med).astype(np.uint8), 24) > 0
        # lines that are bad over most of their length are not patched (nothing useful to copy from)
        lw = env.reshape(L, -1).mean(axis=1) / (1.0 - 0.5 * p.tape_wear) / np.maximum(self._wr_fac, 0.05)   # wrinkle head-lift is not tracking loss
        lwin = np.clip((0.6 - lw) / 0.45, 0.0, 1.0)             # per-line "lost the RF" weight
        if p.doc and bad.any():
            part = np.repeat(lwin < 0.6, C.SPL)
            yv = np.where(bad & part, np.roll(yv, C.SPL), yv)
            cp = np.where(bad, 0.0, cp)
        # frame-wide sparse streaks: a weak tape drops the carrier briefly on ANY line, not only inside a
        # tracking band. Same streak shape as above, independent per field line.
        if p.snow_sparse > 0:
            y2d = yv.reshape(L, C.SPL).copy()
            sr = np.random.default_rng([p.seed, frame_idx, fi, 43])
            cnt = sr.poisson(p.snow_sparse * 0.5, L)
            for li in np.nonzero(cnt)[0]:
                for _ in range(cnt[li]):
                    ln = int(np.clip(sr.lognormal(np.log(p.snow_streak_us), 0.55), 1.5, 40.0) * C.US)
                    a = int(sr.integers(C.ACTIVE_START, C.SPL - 8))
                    n_ = min(ln, C.SPL - a)
                    k = np.arange(n_, dtype=float)
                    fade = np.clip((n_ - k) / max(n_ * 0.35, 1.0), 0.0, 1.0)
                    env_ = np.minimum(1.0, k / (0.25 * C.US + 1.0)) * (0.5 - 0.5 * np.cos(np.pi * fade))
                    y2d[li, a:a + n_] += (1.0 if sr.random() < 0.8 else -0.6) * sr.uniform(0.5, 1.2) * env_
            yv = y2d.reshape(-1)

        # ---- head-switch snow: when the heads change over, the demodulator loses the carrier for a moment and
        # re-locks; a bright burst starts at the left edge of the switching line and fades out toward the right.
        # The next lines start a little further right, so the snow flicks across the bottom of the picture.
        if p.hs_model == "legacy overlay" and p.hs_snow > 0:
            y2d = yv.reshape(L, C.SPL)
            hr = np.random.default_rng([p.seed, frame_idx, fi, 71])
            li0 = L - p.hs_lines
            span_us = (C.ACTIVE_LEN - 8) / C.US
            fj = hr.normal(0.0, p.hs_snow_jitter)
            nl = int(p.hs_snow_lines)
            for k in range(nl):
                g = 1.0 - 0.7 * k / max(nl - 1, 1)                      # strength fades over the lines
                li = li0 + k
                if li >= L:
                    break
                # position of the burst: a base point, a random jump common to the whole field (the burst moves as a
                # unit, left or right, differently every field) and a smaller random scatter per line = jitter
                lj = hr.normal(0.0, 0.35 * p.hs_snow_jitter)
                pos_us = (p.hs_snow_pos * span_us + (2 * frame_idx + fi) * p.hs_snow_speed
                          + k * p.hs_snow_sweep + fj + lj)
                u = abs(pos_us) % (2.0 * span_us)
                u = 2.0 * span_us - u if u > span_us else u              # reflect at both picture edges
                x0 = C.ACTIVE_START + int(u * C.US)
                ln = int(max(1.5, p.hs_snow_us * hr.uniform(0.7, 1.3) * (1.0 - 0.15 * k)) * C.US)
                n_ = min(ln, C.SPL - x0)
                if n_ < 8:
                    continue
                xk = np.arange(n_, dtype=float)
                head = np.exp(-xk / (0.45 * ln)) * np.minimum(1.0, xk / (0.3 * C.US + 1.0))   # bright left, fading right
                grain = 0.6 + 0.4 * signal.lfilter([0.35], [1, -0.65], hr.normal(0, 1, n_)) / 0.55
                y2d[li, x0:x0 + n_] += p.hs_snow * g * 1.7 * head * np.clip(grain, 0.0, 1.7) * hr.uniform(0.8, 1.0)
            yv = y2d.reshape(-1)

        # Restore the original smooth, correlated waveform snow for RF mode too.
        # This enters luma before timebase/output/TV filters, never decoded RGB.
        yv = add_switch_snow(yv,p,fi,frame_idx)

        # ---- LAYER ORDER (bottom -> top): everything above, then tape wrinkles, then tracking noise.
        # The usual (stretch/skip) wrinkle lives in the tape signal, so the later overlays (dropout compensator,
        # snow streaks, head-switch snow) are taken back inside its lines: the wrinkle stays on top of them.
        _, wr_l = self._profiles(L, fi, frame_idx)
        if p.wrinkle > 0 and wr_l.max() > 0.03:
            m_l = np.repeat(np.clip(wr_l * 2.0, 0.0, 1.0), C.SPL)
            yv = yv * (1.0 - m_l) + yv_base * m_l
            cp = cp * (1.0 - m_l) + cp_base * m_l

        # ---- travelling tape wrinkle: a creased band runs down the picture; the head rides over the crease,
        # re-reads / stretches the same lines and loses the carrier balance -> duplicated lines that go
        # solid white, ragged at the edges, with the colour gone.
        wr_ck = None
        if p.wr_travel:
            wd, wt, topl, cl = self.wrinkle_travel(L, fi, frame_idx)
            if max(wd.max(), wt.max()) > 0.02:
                rr = np.random.default_rng([p.seed, frame_idx, fi, 62])
                y2d = yv.reshape(L, C.SPL).copy()
                src = y2d.copy()
                AS = C.ACTIVE_START
                if p.wr_style == "grey fade":       # vertical streaks: column-wise brightness, changing slowly
                    sr_ = np.random.default_rng([p.seed, frame_idx // 3, 6464])
                    streak = np.clip(1.0 + 0.14 * gaussian_filter1d(sr_.normal(0, 1, C.SPL - AS), 5.0) * 5.0, 0.7, 1.3)
                W_ = C.SPL - AS
                xs_ = np.arange(W_, dtype=float)
                for li in np.nonzero((wt > 0.02) | (wd > 0.02))[0]:
                    wl = wt[li]
                    if wl <= 0.02:                      # repeated but not white: copy the line above the band
                        sr = int(np.clip(round(topl[li]) - 1, C.ACTIVE_FIRST, L - 1))
                        y2d[li, AS:] = src[sr, AS:] * (1.0 - p.wr_dup_dark * wd[li])
                        continue
                    rel = li - topl[li]
                    # the head stalls on the crease: the line just above the band is re-read for the WHOLE band
                    # height, i.e. that one line is stretched vertically over every line of the band, with no
                    # horizontal jitter (wr_dup only adds an optional small horizontal tear)
                    sr = int(np.clip(round(topl[li]) - 1, C.ACTIVE_FIRST, L - 1)) if wd[li] > 0.02 else li
                    a = 1.0 + p.wr_dup * rr.uniform(-0.1, 0.7)
                    b = p.wr_dup * rr.uniform(0.0, 45.0)
                    row = np.interp(b + a * xs_, xs_, src[sr, AS:]) * (1.0 - p.wr_dup_dark * wd[li])
                    # ragged coverage: edge lines (and the odd inner line) are only partly white
                    cov = wl if wl < 0.99 else (rr.uniform(0.65, 1.0) if rr.random() < 0.25 * p.wr_ragged else 1.0)
                    cov = 1.0 - (1.0 - cov) * (0.4 + 0.6 * p.wr_ragged) if wl >= 0.99 else cov ** (0.5 + 0.5 * (1.0 - p.wr_ragged))
                    n_cov = max(int(cov * W_), 1)
                    x0 = int(rr.uniform(0.0, 1.0) * (W_ - n_cov)) if cov < 0.999 else 0
                    m = np.zeros(W_)
                    ramp = min(40, max(n_cov // 2, 1))
                    m[x0:x0 + n_cov] = smooth_edges(n_cov, ramp)
                    wh = p.wr_white * min(1.0, wl * 1.3) * rr.uniform(0.85, 1.0)
                    level = 0.85 + 0.08 * signal.lfilter([0.3], [1, -0.7], rr.normal(0, 1, W_))   # over-white, clips
                    if p.wr_style == "grey fade":
                        hband = max(self._band_h(wd, li), 1)
                        q = min(max((li - topl[li]) / hband, 0.0), 1.0)
                        level = p.wr_grey * (1.0 - q) ** 1.3 * streak + 0.02
                        wh = min(1.0, wl * 1.3) * rr.uniform(0.9, 1.0)
                    y2d[li, AS:] = row * (1.0 - m * wh) + level * (m * wh)
                yv = y2d.reshape(-1)
                wr_ck = np.ones((L, C.SPL))
                wr_ck[:, C.ACTIVE_START:] = np.minimum(1.0 - np.clip(wt * 1.6, 0.0, 1.0) * p.wr_white, 1.0 - cl)[:, None]

        if (p.tracking != 0 or p.track_band > 0) and lwin.any():
            # VCR sync/blanking regeneration: the deck's sync separator keeps the picture locked even when
            # the RF is lost, so snow sits on clean sync + blanking (TV clamp stays correct)
            tpl = np.zeros(C.SPL)
            tpl[:C.SYNC_W] = C.SYNC_LEVEL
            tpl[C.SYNC_W:C.ACTIVE_START] = 0.0
            tpl[C.ACTIVE_START - 6:C.ACTIVE_START] = np.linspace(0.0, 0.0, 6)
            y2d = yv.reshape(L, C.SPL).copy()
            y2d[:, :C.ACTIVE_START] += lwin[:, None] * (tpl[None, :C.ACTIVE_START] - y2d[:, :C.ACTIVE_START])
            # FM noise with no carrier piles up at high frequencies -> the discriminator output sits grey/bright
            y2d[:, C.ACTIVE_START:] += ((0.38 if p.tracking < 0 else 0.04) * lwin ** 2)[:, None]
            dr = np.random.default_rng([p.seed, frame_idx, fi, 41])
            lost = np.nonzero(lwin > 0.25)[0]
            # coarse grain: the player's video filters smear the demodulator noise horizontally, so real snow
            # is made of stretched flecks, not single-pixel salt and pepper. Std is restored after smoothing.
            if p.snow_grain > 0 and lost.size:
                fc = 3.6e6 * (0.2 ** p.snow_grain)                    # grain cutoff: 3.6 MHz .. 0.7 MHz
                bq, aq = signal.butter(1, fc / (C.FS / 2))
                seg = y2d[lost, C.ACTIVE_START:]
                mu = seg.mean(axis=1, keepdims=True)
                dev = seg - mu
                sm = signal.lfilter(bq, aq, dev, axis=1)
                sm *= np.clip(dev.std(axis=1, keepdims=True) / (sm.std(axis=1, keepdims=True) + 1e-9), 1.0, 4.0)
                w = (p.snow_grain * lwin[lost])[:, None]
                y2d[lost, C.ACTIVE_START:] = mu + dev + w * (sm - dev)
            # long white/black streaks: the carrier drops out for a while, the discriminator output is pushed
            # to an extreme and held (bright head, flat body, soft end). One streak lives on ONE field line only:
            # neighbouring lines of this field, and the other field, draw their own streaks independently.
            rate = (3.0 if p.tracking < 0 else 1.5) * p.snow_streaks
            for li in lost:
                for _ in range(dr.poisson(rate * lwin[li])):
                    ln = int(np.clip(dr.lognormal(np.log(p.snow_streak_us), 0.6), 1.5, 56.0) * C.US)
                    a = int(dr.integers(C.ACTIVE_START, C.SPL - 8))
                    n_ = min(ln, C.SPL - a)
                    k = np.arange(n_, dtype=float)
                    flat = 0.55 + 0.25 * dr.random()                  # fraction of the streak held at full level
                    fade = np.clip((n_ - k) / max(n_ * (1 - flat), 1.0), 0.0, 1.0)
                    env_ = np.minimum(1.0, k / (0.25 * C.US + 1.0)) * (0.5 - 0.5 * np.cos(np.pi * fade))
                    rag = 0.8 + 0.2 * signal.lfilter([0.15], [1, -0.85], dr.normal(0, 1, n_))   # ragged top
                    sgn = 1.0 if dr.random() < 0.62 else -1.0
                    y2d[li, a:a + n_] += sgn * dr.uniform(0.55, 1.3) * np.clip(rag, 0.4, 1.3) * env_ \
                        * np.clip(0.4 + lwin[li], 0.0, 1.0)
            yv = y2d.reshape(-1)

        # ACC from the colour-under burst
        if p.acc:
            bw = cp.reshape(L, C.SPL)[:, C.BURST_START + self.dc + 4:C.BURST_START + self.dc + C.BURST_LEN - 4]
            rms = np.sqrt((bw ** 2).mean(axis=1))
            valid = rms > 1e-5
            g = (C.BURST_AMP / np.sqrt(2) * self.burst_loss) / np.maximum(rms, 1e-5)
            g = np.clip(g, 0.2, 5.0)
            g[:7] = np.median(g[7:]) if valid[7:].any() else 1.0
            # colour killer: burst far below nominal (tracking loss, wrinkle) -> chroma muted instead of
            # the ACC amplifying noise into rainbow speckle
            kill = np.clip((4.0 - g) / 1.5, 0.0, 1.0)
            g = g * kill
            g = signal.lfilter([0.5], [1, -0.5], g, zi=[0.5 * g[0]])[0]
            cp = cp * np.repeat(g, C.SPL)
            # burst re-insertion gate: restore the burst's nominal level so the TV's burst-referenced
            # chroma gain sees chroma and burst in their true ratio
            gate = np.ones(C.SPL)
            a, b = C.BURST_START + self.dc - 3, C.BURST_START + self.dc + C.BURST_LEN + 3
            gate[a:b] = 1.0 + (1.0 / self.burst_loss - 1.0) * smooth_edges(b - a, 8)
            cp = cp * np.tile(gate, L)
        cp = cp * p.chroma_gain
        if wr_ck is not None:                                    # colour is lost inside the wrinkle band
            cp = cp * wr_ck.reshape(-1)

        # ===================== time-base errors =====================
        d = self.timebase(L, fi, frame_idx, rng)
        yv = displace(yv, d)
        cp = displace(cp, d + self.cdel)

        # ===================== up-convert chroma, mix =====================
        lo_ph = TWO_PI * (C.FSC + C.FCU) * t + line_rot + np.deg2rad(p.lo_phase_err)
        cout = run(self.f_cup, cp * 2 * np.cos(lo_ph))
        # APC: phase-lock the up-converter to the burst (static phase + slow tracking)
        eps = self.burst_phase(cout, d + self.cdel, fi, frame_idx, L)
        gl_ph, gl_gain = self._cu_glitch(L, fi, frame_idx)
        # the glitch hits the picture chroma, not the burst: the TV decoder references its phase and gain to the burst,
        # so a phase/gain error on the burst itself would be cancelled and nothing would show
        bm = np.ones(C.SPL)
        b0, b1 = C.BURST_START + self.dc - 4, C.BURST_START + self.dc + C.BURST_LEN + 4
        bm[b0:b1] = 0.0
        bm = np.tile(bm, L)
        cout = run(self.f_cup, cp * (1.0 + (np.repeat(gl_gain, C.SPL) - 1.0) * bm) * 2
                   * np.cos(lo_ph - np.repeat(eps, C.SPL) + np.repeat(gl_ph, C.SPL) * bm))
        if p.doc and bad.any():
            # chroma side of the DOC: re-modulate the previous line's colour for this line
            bad_c = displace(bad.astype(np.float64), d + self.cdel) > 0.3
            cout = self.doc_chroma(cout, bad_c, fi, frame_idx)
        out = yv + cout
        if p.hs_model != "off" and p.hs_mask_lines > 0:
            end = C.ACTIVE_FIRST+C.ACTIVE_LINES
            out = out.reshape(L,C.SPL).copy()
            out[end-p.hs_mask_lines:end,C.ACTIVE_START:C.ACTIVE_START+C.ACTIVE_LEN] = 0
            out = out.reshape(-1)

        if taps is not None:
            taps.update(comp_in=x, rec_luma=y, fm=fm, tape=rf, c_under=cu, luma_demod=yv,
                        c_play=cp, c_out=cout, rf_env=env)
        return out

    # ------------------------------------------------------------ RCA output stage
    def output_stage(self, stream, fi, frame_idx):
        p = self.p
        rng = np.random.default_rng([p.seed, frame_idx, fi, 9])
        x = run(self.f_out, stream) * p.out_gain
        if p.ghost > 0:
            dn = int(round(p.ghost_ns * C.FS / 1e9))
            x = x + p.ghost * np.concatenate([np.full(dn, x[0]), x[:-dn]])
        if p.out_noise > 0:
            x = x + rng.normal(0, p.out_noise, len(x))
        return np.clip(x, -0.6, 1.6)


TWO_PI = 2 * np.pi
