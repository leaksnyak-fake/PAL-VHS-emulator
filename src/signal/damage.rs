//! Tape mechanics and waveform-domain damage. No decoded RGB overlays.
use super::*;
fn rng(p: &Params, keys: &[u64]) -> Rng {
    let mut seed = vec![p.number("seed") as u64];
    seed.extend_from_slice(keys);
    Rng::new(&seed)
}
fn smoothstep(x: f64) -> f64 {
    let x = x.clamp(0.0, 1.0);
    x * x * (3.0 - 2.0 * x)
}
pub(super) fn profiles(l: usize, fi: usize, frame: u64, p: &Params) -> (Vec<f64>, Vec<f64>) {
    let n = |s| p.number(s);
    let mut tr = vec![0.0; l];
    let mut wr = vec![0.0_f64; l];
    let lf = l as f64;
    let bump = |line: usize, c: f64, half: f64| {
        let d = ((line as f64 - c + lf / 2.0).rem_euclid(lf) - lf / 2.0).abs();
        0.5 - 0.5 * (PI * (1.0 - d / half).clamp(0.0, 1.0)).cos()
    };
    if n("track_band") > 0.0 {
        let t = frame as f64 + 0.5 * fi as f64;
        let mut x = if n("track_accel") > 1e-3 {
            let ph = (t * n("track_speed")).rem_euclid(lf);
            lf * (n("track_accel") * ph / lf).exp_m1() / n("track_accel").exp_m1()
        } else {
            t * n("track_speed")
        };
        x += n("track_wobble") * ((t / 5.0).sin() + 0.5 * (t / 11.3 + 1.0).sin());
        for i in 0..l {
            tr[i] = bump(i, (x + 40.0).rem_euclid(lf), 10.0 + 22.0 * n("track_band"));
        }
    }
    if n("wrinkle") > 0.0 {
        let count = (n("wrinkle_count") as usize).max(1);
        let gap = if n("wrinkle_gap") > 0.0 {
            n("wrinkle_gap")
        } else {
            FIELD_HEIGHT as f64 / count as f64
        };
        for k in 0..count {
            let c = n("wrinkle_pos") * lf
                + k as f64 * gap
                + (frame as f64 + fi as f64 * 0.5) * n("wrinkle_drift");
            for i in 0..l {
                wr[i] = wr[i].max(bump(
                    i,
                    c.rem_euclid(lf),
                    (n("wrinkle_height") / 2.0).max(1.0),
                ));
            }
        }
    }
    (tr, wr)
}
pub(super) fn line_warp(
    tape: &[f64],
    l: usize,
    fi: usize,
    frame: u64,
    p: &Params,
    os: usize,
) -> Vec<f64> {
    let n = |s| p.number(s);
    let (tr, wr) = profiles(l, fi, frame, p);
    let sm: Vec<_> = tr
        .iter()
        .map(|v| n("track_smear") * n("track_band") * v)
        .collect();
    if sm.iter().chain(&wr).all(|v| *v < 0.03) {
        return tape.to_vec();
    }
    let mut r = rng(p, &[frame, fi as u64, 41]);
    let mut ar = |rho: f64| {
        let mut last = 0.0;
        (0..l)
            .map(|_| {
                last = (1.0 - rho * rho).sqrt() * r.normal() + rho * last;
                last
            })
            .collect::<Vec<_>>()
    };
    let z = ar(0.88);
    let offsets = ar(0.6);
    let ramps = ar(0.7);
    let spl = SPL * os;
    let mut out = tape.to_vec();
    let mut lag = 0.0;
    for k in 8..l {
        let speed = (0.07 * sm[k]).max(n("wrinkle_speed_pct") / 100.0 * wr[k]);
        let shift = (3.0 * sm[k]).max(n("wrinkle_shift_us") * wr[k]) * US * os as f64;
        let stretch = 1.0 + (0.9 * sm[k]).max((n("wrinkle_stretch") - 1.0) * wr[k]);
        let weight = sm[k].max(wr[k]);
        if weight > 0.03 {
            lag += 1.0 - 1.0 / stretch;
        } else {
            lag = (lag - 0.5).max(0.0);
        }
        let src = (k as f64 - lag).round().clamp(0.0, (l - 1) as f64) as usize;
        if weight <= 0.03 && src == k {
            continue;
        }
        let a = (1.0 + speed * z[k].clamp(-2.5, 2.5)).clamp(0.3, 2.2);
        let b = offsets[k] * shift;
        let ramp = ramps[k].clamp(-2.0, 2.0)
            * (1.5 * speed + if speed > 0.0 { 0.1 } else { 0.0 }).min(0.8);
        for j in 0..spl {
            let t = j as f64;
            let pos =
                (src * spl) as f64 + b + a * (t + ramp * (t * t / (2.0 * spl as f64) - t / 2.0));
            out[k * spl + j] = interp(tape, pos);
        }
    }
    out
}
pub(super) fn envelope(
    l: usize,
    fi: usize,
    frame: u64,
    p: &Params,
    os: usize,
    r: &mut Rng,
) -> (Vec<f64>, Vec<f64>) {
    let n = |s| p.number(s);
    let size = l * SPL * os;
    let mut env = vec![1.0 - 0.5 * n("tape_wear"); size];
    let mut wr_fac = vec![1.0; l];
    for _ in 0..r.poisson(n("dropout_rate") / 2.0) {
        let li = r.integer(3, l);
        let st = li * SPL + r.integer(0, SPL);
        let len = (r
            .lognormal(n("dropout_len_us").max(1e-9).ln(), 0.5)
            .clamp(1.0, 90.0)
            * US) as usize;
        let a = st * os;
        let end = (a + len * os).min(size);
        if end - a > 8 {
            for (i, w) in smooth_edges(end - a, 15 * os).iter().enumerate() {
                env[a + i] *= 1.0 - n("dropout_depth") * w;
            }
        }
    }
    let (tr, wr) = profiles(l, fi, frame, p);
    let mut factors = vec![1.0; l];
    if n("track_band") > 0.0 {
        for i in 0..l {
            factors[i] *= 1.0 - 0.6 * n("track_band") * tr[i] * r.range(0.6, 1.0);
        }
    }
    let k = n("tracking");
    if k != 0.0 {
        for i in 0..l {
            let y = ((i as f64 - ACTIVE_FIRST as f64) / FIELD_HEIGHT as f64).clamp(0.0, 1.0);
            let u = if k < 0.0 { y } else { 1.0 - y };
            let err = k.abs() * if k < 0.0 { 2.1 } else { 1.5 } * (0.25 + 0.75 * u);
            let severity = smoothstep((err - 0.3) / 0.7) * r.range(0.75, 1.0);
            factors[i] *= 10.0_f64.powf(-1.4 * severity);
        }
    }
    if n("wrinkle") > 0.0 {
        let mut r2 = rng(p, &[frame, fi as u64, 31]);
        for i in 0..l {
            wr_fac[i] = 1.0 - 0.85 * n("wrinkle") * wr[i] * r2.range(0.3, 1.0);
            factors[i] *= wr_fac[i];
        }
    }
    for i in 0..size {
        env[i] *= factors[i / (SPL * os)];
    }
    if p.choice("hs_model") == "RF switch" && n("hs_noise") > 0.0 {
        let start = switch_line(p, l, fi, frame) * SPL as f64 * os as f64;
        for (i, v) in env.iter_mut().enumerate() {
            let t = (i as f64 - start) / (US * os as f64);
            if t >= 0.0 {
                let loss = (t / 0.15).clamp(0.0, 1.0)
                    * (-(t - n("hs_gap_us")).max(0.0) / n("hs_recovery_us").max(1e-9)).exp();
                *v *= 1.0 - n("hs_noise").min(0.999) * loss;
            }
        }
    } else if p.choice("hs_model") == "legacy overlay" && n("hs_noise") > 0.0 {
        let li = l.saturating_sub(n("hs_lines") as usize);
        for (k, g) in [(0, 1.0), (1, 0.35)] {
            let a = (li + k) * SPL * os;
            let len = (14.0 * US * os as f64) as usize;
            let win = smooth_edges(len, 40);
            for j in 0..len {
                if a + j < size {
                    env[a + j] *= 1.0 - (n("hs_noise") * g).min(0.97) * win[j];
                }
            }
        }
    }
    (env, wr_fac)
}
pub(super) fn timebase(l: usize, fi: usize, frame: u64, p: &Params, r: &mut Rng) -> Vec<f64> {
    let n = |s| p.number(s);
    let mut pr = Rng::new(&[n("seed") as u64 + 77]);
    let ph: Vec<_> = (0..4).map(|_| pr.range(0.0, TAU)).collect();
    let mut dsr = rng(p, &[frame, fi as u64, 11]);
    let sksign = if p.boolean("skew_random") {
        dsr.sign()
    } else {
        1.0
    };
    let hssign = if p.boolean("hs_random") {
        dsr.sign()
    } else {
        1.0
    };
    let amp = 0.75 + 0.25 * (TAU * 0.31 * frame as f64 / 25.0 + ph[2]).sin();
    let mut dl = Vec::new();
    for line in 0..l {
        let t = frame as f64 / 25.0 + fi as f64 * 0.02 + line as f64 * 64e-6;
        let jitter = r.normal() * n("tb_jitter_ns");
        let wobble = n("tb_wobble_ns")
            * ((TAU * n("tb_wobble_hz") * t + ph[0]).sin()
                + 0.4 * (TAU * 2.7 * n("tb_wobble_hz") * t + ph[1]).sin());
        dl.push(
            (jitter + wobble) * FS / 1e9
                + sksign
                    * n("tb_skew_us")
                    * US
                    * amp
                    * (-(line as f64 - (ACTIVE_FIRST - 1) as f64).max(0.0) / 7.0).exp(),
        );
    }
    let mut out: Vec<_> = (0..l * SPL)
        .map(|i| interp(&dl, i as f64 / SPL as f64 - 0.5))
        .collect();
    if p.choice("hs_model") != "off" {
        let start = switch_line(p, l, fi, frame) * SPL as f64;
        let shift = hssign
            * n("hs_shift_us")
            * US
            * (1.0
                + n("hs_shift_var")
                    * (ph[3] + TAU * n("hs_shift_rate") * (frame as f64 + 0.5 * fi as f64) / 25.0)
                        .sin());
        let shake = dsr.normals(l, n("hs_jitter_us") * US);
        for (i, v) in out.iter_mut().enumerate() {
            if i as f64 >= start {
                *v += shift + shake[i / SPL];
            }
        }
    }
    out
}
pub(super) fn chroma_glitch(l: usize, fi: usize, frame: u64, p: &Params) -> (Vec<f64>, Vec<f64>) {
    let n = |s| p.number(s);
    let mut phase = vec![0.0; l];
    let mut gain = vec![1.0; l];
    if n("chroma_band") > 0.0 {
        let mut r = rng(p, &[frame / 3, 7773]);
        let b1 = gaussian(&r.normals(l, 1.0), 7.0);
        let b2 = gaussian(&r.normals(l, 1.0), 3.0);
        for i in 0..l {
            phase[i] +=
                n("chroma_band") * 0.30 * (2.8 * b1[i] + 0.5 * 1.6 * b2[i]).clamp(-2.0, 2.0);
            gain[i] *= 1.0
                + n("chroma_band")
                    * 0.20
                    * (0.7 * 2.8 * b1[i] + 0.5 * 1.6 * b2[i]).clamp(-2.0, 2.0);
        }
    }
    if n("cu_glitch") > 0.0 {
        let per = (n("cu_glitch_period") as u64).max(1);
        let len = (n("cu_glitch_len") as usize).max(1);
        let k = frame / per;
        let mut r = rng(p, &[k, 7771]);
        let start = k * per + r.integer(0, (per as usize).saturating_sub(len).max(1)) as u64;
        let t = frame as f64 + 0.5 * fi as f64 - start as f64;
        if t >= 0.0 && t < len as f64 {
            let s = (PI * t / len as f64).sin().powf(0.7);
            let mut rf = rng(p, &[frame / 2, 7772]);
            let bands = gaussian(&rf.normals(l, 1.0), 10.0);
            let cast = r.range(0.5, 1.0) * r.sign();
            for i in 0..l {
                let band = (bands[i] * 5.0).clamp(-1.0, 1.0);
                phase[i] += s
                    * n("cu_glitch")
                    * 0.7
                    * (0.7 * band + cast * (0.5 + 0.5 * (TAU * t / len as f64).sin()))
                        .clamp(-1.0, 1.0);
                gain[i] *= 1.0 + 1.8 * s * n("cu_glitch") * (0.5 + 0.5 * band.abs());
            }
        }
    }
    (phase, gain)
}
pub(super) fn sparse_snow(y: &mut [f64], l: usize, fi: usize, frame: u64, p: &Params) {
    if p.number("snow_sparse") <= 0.0 {
        return;
    }
    let mut r = rng(p, &[frame, fi as u64, 43]);
    let counts: Vec<_> = (0..l)
        .map(|_| r.poisson(p.number("snow_sparse") * 0.5))
        .collect();
    for li in 0..l {
        for _ in 0..counts[li] {
            let len = (r
                .lognormal(p.number("snow_streak_us").max(1e-9).ln(), 0.55)
                .clamp(1.5, 40.0)
                * US) as usize;
            let start = r.integer(ACTIVE_START, SPL - 8);
            let size = len.min(SPL - start);
            let strength = if r.uniform() < 0.8 { 1.0 } else { -0.6 } * r.range(0.5, 1.2);
            for k in 0..size {
                let fade = ((size - k) as f64 / (size as f64 * 0.35).max(1.0)).clamp(0.0, 1.0);
                let env = (k as f64 / (0.25 * US + 1.0)).min(1.0) * (0.5 - 0.5 * (PI * fade).cos());
                y[li * SPL + start + k] += strength * env;
            }
        }
    }
}
fn add_snow_row(
    y: &mut [f64],
    li: usize,
    x_float: f64,
    length: f64,
    strength: f64,
    limit: usize,
    r: &mut Rng,
) {
    let x0 = x_float.floor().max(0.0) as usize;
    if x0 >= limit || li * SPL >= y.len() {
        return;
    }
    let size = (length.ceil().max(8.0) as usize).min(limit - x0);
    if size < 2 {
        return;
    }
    let grain = iir(&r.normals(size, 1.0), 0.35, false);
    let amp = r.range(0.8, 1.0);
    for k in 0..size {
        let t = k as f64 - (x_float - x0 as f64);
        let head = if t < 0.0 {
            0.0
        } else {
            (-t / (0.45 * length.max(1.0))).exp() * (t / (0.3 * US + 1.0)).min(1.0)
        };
        let g = (0.6 + 0.4 * grain[k] / 0.55).clamp(0.0, 1.7);
        y[li * SPL + x0 + k] += strength * 1.7 * head * g * amp;
    }
}
pub(super) fn head_snow(y: &mut [f64], l: usize, fi: usize, frame: u64, p: &Params) {
    let n = |s| p.number(s);
    let mut r = rng(p, &[frame, fi as u64, 71]);
    if p.choice("hs_model") == "legacy overlay" && n("hs_snow") > 0.0 {
        let li0 = l.saturating_sub(n("hs_lines") as usize);
        let span = (ACTIVE_LEN - 8) as f64 / US;
        let fj = r.normal() * n("hs_snow_jitter");
        let nl = n("hs_snow_lines") as usize;
        for k in 0..nl {
            let li = li0 + k;
            if li >= l {
                break;
            }
            let g = 1.0 - 0.7 * k as f64 / nl.saturating_sub(1).max(1) as f64;
            let lj = r.normal() * 0.35 * n("hs_snow_jitter");
            let pos = n("hs_snow_pos") * span
                + (2 * frame + fi as u64) as f64 * n("hs_snow_speed")
                + k as f64 * n("hs_snow_sweep")
                + fj
                + lj;
            let u = pos.abs().rem_euclid(2.0 * span);
            let u = if u > span { 2.0 * span - u } else { u };
            let x = ACTIVE_START as f64 + (u * US) as usize as f64;
            let length =
                (n("hs_snow_us") * r.range(0.7, 1.3) * (1.0 - 0.15 * k as f64)).max(1.5) * US;
            add_snow_row(y, li, x, length, n("hs_snow") * g, SPL, &mut r);
        }
    }
    if p.choice("hs_model") != "RF switch" || n("hs_residual") <= 0.0 || p.boolean("bypass_tape") {
        return;
    }
    let height = n("hs_residual_height") as isize;
    let (first, mut last) = if p.boolean("hs_residual_follow") {
        // Top snow line = first field line touched by the RF head switch, so
        // the snow tracks "switch before vsync" and the faulty-servo excursion.
        let top = (switch_line(p, l, fi, frame).floor() as isize - ACTIVE_FIRST as isize)
            .clamp(0, FIELD_HEIGHT as isize - 1);
        (top, (top + height - 1).min(FIELD_HEIGHT as isize - 1))
    } else {
        let last = (FIELD_HEIGHT as isize - 1).min(
            (HEIGHT as isize - 1 - n("hs_residual_bottom_px") as isize - fi as isize).div_euclid(2),
        );
        ((last - height + 1).max(0), last)
    };
    if n("hs_mask_lines") > 0.0 {
        last = last.min(FIELD_HEIGHT as isize - n("hs_mask_lines") as isize - 1);
    }
    if last < first {
        return;
    }
    let lines = (last - first + 1) as usize;
    let span = (WIDTH as f64 - n("hs_residual_width_px").min(WIDTH as f64)).max(0.0);
    let mut pos = n("hs_residual_x") * span;
    let motion = p.choice("hs_residual_motion");
    if motion == "Drift" || motion == "Drift + jitter" {
        pos += (2 * frame + fi as u64) as f64 * n("hs_residual_speed_px");
    }
    let jitter = motion == "Random jumps" || motion == "Drift + jitter";
    let mut rp = rng(p, &[frame, fi as u64, 174]);
    if jitter {
        pos += rp.normal() * n("hs_residual_jitter_px");
    }
    let line_jit = if jitter {
        rp.normals(lines, 0.35 * n("hs_residual_jitter_px"))
    } else {
        vec![0.0; lines]
    };
    for k in 0..lines {
        let raw = if span == 0.0 {
            0.0
        } else {
            (pos + k as f64 * n("hs_residual_sweep_px") + line_jit[k]).rem_euclid(2.0 * span)
        };
        let x = if raw > span { 2.0 * span - raw } else { raw };
        let x = ACTIVE_START as f64 + x * ACTIVE_LEN as f64 / WIDTH as f64;
        let length = n("hs_residual_width_px") * ACTIVE_LEN as f64 / WIDTH as f64
            * r.range(0.7, 1.3)
            * (1.0 - 0.15 * k as f64);
        let g = 1.0 - 0.7 * k as f64 / lines.saturating_sub(1).max(1) as f64;
        add_snow_row(
            y,
            ACTIVE_FIRST + first as usize + k,
            x,
            length,
            n("hs_residual") * g,
            ACTIVE_START + ACTIVE_LEN,
            &mut r,
        );
    }
}
pub(super) fn tracking_snow(
    y: &mut [f64],
    lwin: &[f64],
    l: usize,
    fi: usize,
    frame: u64,
    p: &Params,
) {
    let n = |s| p.number(s);
    if n("tracking") == 0.0 && n("track_band") <= 0.0 {
        return;
    }
    let mut r = rng(p, &[frame, fi as u64, 41]);
    for li in 0..l {
        let w = lwin[li];
        if w <= 0.0 {
            continue;
        }
        for x in 0..ACTIVE_START {
            let tpl = if x < SYNC_W { -0.3 } else { 0.0 };
            let i = li * SPL + x;
            y[i] += w * (tpl - y[i]);
        }
        for x in ACTIVE_START..SPL {
            y[li * SPL + x] += if n("tracking") < 0.0 { 0.38 } else { 0.04 } * w * w;
        }
        if w <= 0.25 {
            continue;
        }
        if n("snow_grain") > 0.0 {
            let row = &mut y[li * SPL + ACTIVE_START..(li + 1) * SPL];
            let mu = mean(row);
            let dev: Vec<_> = row.iter().map(|v| v - mu).collect();
            let fc = 3.6e6 * 0.2_f64.powf(n("snow_grain"));
            let mut smooth = lowpass(fc, 1, FS).zero_run(&dev);
            let gain = (stddev(&dev) / (stddev(&smooth) + 1e-9)).clamp(1.0, 4.0);
            for v in &mut smooth {
                *v *= gain;
            }
            for i in 0..row.len() {
                row[i] = mu + dev[i] + n("snow_grain") * w * (smooth[i] - dev[i]);
            }
        }
        let rate = if n("tracking") < 0.0 { 3.0 } else { 1.5 } * n("snow_streaks");
        for _ in 0..r.poisson(rate * w) {
            let len = (r
                .lognormal(n("snow_streak_us").max(1e-9).ln(), 0.6)
                .clamp(1.5, 56.0)
                * US) as usize;
            let start = r.integer(ACTIVE_START, SPL - 8);
            let size = len.min(SPL - start);
            let flat = 0.55 + 0.25 * r.uniform();
            let rag = iir(&r.normals(size, 1.0), 0.15, false);
            let sign = if r.uniform() < 0.62 { 1.0 } else { -1.0 };
            let strength = sign * r.range(0.55, 1.3) * (0.4 + w).clamp(0.0, 1.0);
            for k in 0..size {
                let fade =
                    ((size - k) as f64 / (size as f64 * (1.0 - flat)).max(1.0)).clamp(0.0, 1.0);
                let env = (k as f64 / (0.25 * US + 1.0)).min(1.0) * (0.5 - 0.5 * (PI * fade).cos());
                y[li * SPL + start + k] += strength * (0.8 + 0.2 * rag[k]).clamp(0.4, 1.3) * env;
            }
        }
    }
}
struct Travel {
    dup: Vec<f64>,
    white: Vec<f64>,
    top: Vec<f64>,
    colour: Vec<f64>,
}
impl Travel {
    fn new(l: usize) -> Self {
        Self {
            dup: vec![0.0; l],
            white: vec![0.0; l],
            top: vec![-1.0; l],
            colour: vec![0.0; l],
        }
    }
    fn add(&mut self, c: f64, h: f64, hw: f64, flicker: f64, lose: bool, weight: f64, p: &Params) {
        let st = 1.0 + p.number("wr_soft") * 0.5 * h;
        let sb = 1.0 + p.number("wr_soft") * 0.08 * h;
        for i in 0..self.dup.len() {
            let d = i as f64 - c;
            let half = h / 2.0;
            let wk = (if d < 0.0 {
                (half + d) / st
            } else {
                (half - d) / sb
            } + 0.5)
                .clamp(0.0, 1.0)
                * weight;
            let d2 = i as f64 - (c - half + hw / 2.0);
            let white = (if d2 < 0.0 {
                (hw / 2.0 + d2) / st
            } else {
                (hw / 2.0 - d2) / sb
            } + 0.5)
                .clamp(0.0, 1.0)
                * flicker
                * weight;
            if wk > self.dup[i] || (white > self.white[i] && self.top[i] < 0.0) {
                self.top[i] = c - half;
            }
            self.dup[i] = self.dup[i].max(wk);
            self.white[i] = self.white[i].max(white);
            if lose {
                self.colour[i] = self.colour[i].max(wk.max(white));
            }
        }
    }
}
fn travelling(l: usize, fi: usize, frame: u64, p: &Params) -> Travel {
    let n = |s| p.number(s);
    let mut result = Travel::new(l);
    let per = (n("wr_period") as u64).max(10);
    let hmax = n("wr_hmax").max(n("wr_hmin"));
    let count = (n("wr_count") as usize).max(1);
    let speed = n("wr_speed").max(0.5);
    let active = FIELD_HEIGHT as f64;
    let gap = if n("wr_gap") > 0.0 {
        n("wr_gap")
    } else {
        active / count as f64
    };
    let cycle = if count > 1 {
        (count as f64 * gap).max(active + hmax + 4.0)
    } else {
        active + hmax + 4.0
    };
    let hold = if count > 1 { n("wr_hold") } else { 0.0 };
    let acc = n("wr_accel").max(0.0);
    let travel =
        hold + (count as f64 * gap + cycle) / (0.5 * speed) + (active + hmax + 8.0) / (0.5 * speed);
    let k0 = (((frame as f64 - travel) / per as f64).floor() - 1.0).max(0.0) as u64;
    for k in k0..=frame / per {
        let mut r = rng(p, &[k, 6161]);
        let start = k * per + r.integer(0, ((per as f64 * 0.6) as usize).max(1)) as u64;
        let sp = speed * r.range(0.7, 1.3);
        let t = frame as f64 + fi as f64 * 0.5 - start as f64;
        if t < 0.0 {
            continue;
        }
        for i in 0..count {
            let u = t * sp - i as f64 * gap;
            if u < 0.0 {
                continue;
            }
            let last = if count > 1 {
                ((hold * sp - i as f64 * gap) / cycle).floor().max(0.0)
            } else {
                0.0
            };
            let cyc = (u / cycle).floor().min(last);
            let x = u - cyc * cycle;
            let mut ri = rng(p, &[k, i as u64, cyc as u64, 6162]);
            let mut pos = cycle
                * if acc > 1e-3 {
                    (acc * x / cycle).exp_m1() / acc.exp_m1()
                } else {
                    x / cycle
                };
            let tl = x / sp;
            let tw = ri.range(14.0, 40.0);
            let ph1 = ri.range(0.0, TAU);
            let ph2 = ri.range(0.0, TAU);
            pos += n("wr_wobble")
                * ((TAU * tl / tw + ph1).sin() + 0.5 * (TAU * tl / (tw * 2.3) + ph2).sin());
            let h0 = ri.range(n("wr_hmin"), hmax);
            let rise = if n("wr_rise") > 0.0 {
                0.35 + 0.65 * smoothstep(tl / n("wr_rise"))
            } else {
                1.0
            };
            let sk = n("wr_shrink") * ri.range(0.4, 1.4);
            let fall = (1.0 - sk * smoothstep((pos / active - 0.5) / 0.5)).max(0.0);
            let h = h0 * rise * fall;
            if h < 0.6 {
                continue;
            }
            let lose = ri.uniform() < n("wr_chroma_loss");
            let tf = ri.range(5.0, 14.0);
            let f1 = ri.range(0.0, TAU);
            let f2 = ri.range(0.0, TAU);
            let fs = 0.5
                + 0.5
                    * (0.6 * (TAU * (t + 0.5 * fi as f64) / tf + f1).sin()
                        + 0.4 * (TAU * (t + 0.5 * fi as f64) / (tf * 0.37) + f2).sin());
            let jit = rng(p, &[k, i as u64, cyc as u64, 2 * frame + fi as u64, 6163]).uniform();
            let fl = 1.0 - n("wr_flicker") * (0.75 * (1.0 - fs) + 0.25 * jit).clamp(0.0, 1.0);
            let c = ACTIVE_FIRST as f64
                + if p.boolean("wr_full_entry") {
                    h / 2.0
                } else {
                    -h / 2.0
                }
                + pos;
            let hw = if n("wr_white_h") > 0.0 {
                n("wr_white_h") * rise * fall
            } else {
                h
            };
            if c - h / 2.0 <= (ACTIVE_FIRST + FIELD_HEIGHT) as f64 {
                result.add(c, h, hw, fl, lose, 1.0, p);
            }
            let satellites = ri.poisson(1.6 * n("wr_sat")).min(3);
            for _ in 0..satellites {
                let sign = if ri.uniform() < 0.6 { 1.0 } else { -1.0 };
                let offset = sign * ri.range(1.0, 2.2) * h;
                let hs = (h * ri.range(0.25, 0.5)).max(1.5);
                let cs = c + offset;
                if cs - hs / 2.0 <= (ACTIVE_FIRST + FIELD_HEIGHT) as f64 {
                    result.add(cs, hs, hs, fl * ri.range(0.5, 0.9), lose, 0.85, p);
                }
            }
        }
    }
    result.dup[..ACTIVE_FIRST].fill(0.0);
    result.white[..ACTIVE_FIRST].fill(0.0);
    result.colour[..ACTIVE_FIRST].fill(0.0);
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn travelling_crease_schedule_is_random_access_and_protects_vertical_interval() {
        let mut p = Params::default();
        for (key, value) in [("wr_period", 20), ("wr_count", 3), ("wr_hold", 80)] {
            p.set(key, json!(value)).unwrap();
        }
        let a = travelling(313, 0, 48, &p);
        let _ = travelling(312, 1, 129, &p);
        let b = travelling(313, 0, 48, &p);
        assert_eq!(a.dup, b.dup);
        assert_eq!(a.white, b.white);
        assert_eq!(a.colour, b.colour);
        assert!(a.dup[..ACTIVE_FIRST].iter().all(|v| *v == 0.0));
        assert!(a.dup.iter().any(|v| *v > 0.5));
        assert!(a
            .white
            .iter()
            .all(|v| v.is_finite() && *v >= 0.0 && *v <= 1.0));
    }

    #[test]
    fn rf_switch_envelope_is_field_geometry_invariant_across_sample_rates() {
        let mut p = Params::default();
        p.set("dropout_rate", json!(0)).unwrap();
        let (a, _) = envelope(313, 0, 0, &p, 1, &mut rng(&p, &[5]));
        let (b, _) = envelope(313, 0, 0, &p, 2, &mut rng(&p, &[5]));
        assert_eq!(switch_line(&p, 313, 0, 0), 308.5);
        for i in 0..a.len() {
            assert!((a[i] - b[2 * i]).abs() < 1e-12);
        }
        assert!(a[..308 * SPL].iter().all(|v| *v == 1.0));
        assert!(a.iter().any(|v| *v < 0.5));
    }

    #[test]
    fn residual_snow_uses_woven_bottom_coordinate_and_mask() {
        let mut p = Params::default();
        p.set("hs_residual", json!(0.6)).unwrap();
        p.set("hs_residual_motion", json!("Stationary")).unwrap();
        let mut y = vec![0.0; 313 * SPL];
        head_snow(&mut y, 313, 0, 0, &p);
        let hit: Vec<_> = y
            .chunks(SPL)
            .enumerate()
            .filter(|(_, r)| r.iter().any(|x| *x != 0.0))
            .map(|(i, _)| i)
            .collect();
        assert_eq!(hit, vec![ACTIVE_FIRST + 285]);
        p.set("hs_mask_lines", json!(4)).unwrap();
        let mut y = vec![0.0; 313 * SPL];
        head_snow(&mut y, 313, 0, 0, &p);
        assert!(y.iter().all(|v| *v == 0.0));
    }

    #[test]
    fn residual_snow_can_follow_the_head_switch_line() {
        let rows = |p: &Params, l: usize, fi: usize, frame: u64| -> Vec<usize> {
            let mut y = vec![0.0; l * SPL];
            head_snow(&mut y, l, fi, frame, p);
            y.chunks(SPL)
                .enumerate()
                .filter(|(_, r)| r.iter().any(|x| *x != 0.0))
                .map(|(i, _)| i)
                .collect()
        };
        let mut p = Params::default();
        p.set("hs_residual", json!(0.6)).unwrap();
        p.set("hs_residual_motion", json!("Stationary")).unwrap();
        p.set("hs_residual_follow", json!(true)).unwrap();
        // Default advance (6.5 H) puts the switch on line 308.5 -> first line 308,
        // which is also where the fixed bottom gap lands, field 0 and field 1.
        assert_eq!(rows(&p, 313, 0, 0), vec![308]);
        assert_eq!(rows(&p, 312, 1, 0), vec![307]);
        // Moving the switch earlier moves the snow with it; the bottom gap is ignored.
        p.set("hs_advance", json!(10.5)).unwrap();
        p.set("hs_residual_bottom_px", json!(40)).unwrap();
        assert_eq!(rows(&p, 313, 0, 0), vec![304]);
        // Extra lines grow downward from the switch line.
        p.set("hs_residual_height", json!(3)).unwrap();
        assert_eq!(rows(&p, 313, 0, 0), vec![304, 305, 306]);
        // Faulty servo excursion moves the switch line from frame to frame.
        p.set("hs_residual_height", json!(1)).unwrap();
        p.set("hs_servo_lines", json!(20)).unwrap();
        let moved = rows(&p, 313, 0, 7);
        assert_ne!(moved, rows(&p, 313, 0, 0));
        // The black mask still hides snow below it.
        p.set("hs_servo_lines", json!(0)).unwrap();
        p.set("hs_advance", json!(6.5)).unwrap();
        p.set("hs_mask_lines", json!(4)).unwrap();
        assert!(rows(&p, 313, 0, 0).is_empty());
    }
}
pub(super) fn travel_overlay(
    y: &mut [f64],
    l: usize,
    fi: usize,
    frame: u64,
    p: &Params,
) -> Vec<f64> {
    let mut kill = vec![1.0; l * SPL];
    if !p.boolean("wr_travel") {
        return kill;
    }
    let n = |s| p.number(s);
    let t = travelling(l, fi, frame, p);
    if t.dup.iter().chain(&t.white).all(|v| *v <= 0.02) {
        return kill;
    }
    let mut r = rng(p, &[frame, fi as u64, 62]);
    let src = y.to_vec();
    let width = SPL - ACTIVE_START;
    let grey = p.choice("wr_style") == "grey fade";
    let streak = if grey {
        let mut sr = rng(p, &[frame / 3, 6464]);
        gaussian(&sr.normals(width, 1.0), 5.0)
            .iter()
            .map(|v| (1.0 + 0.14 * v * 5.0).clamp(0.7, 1.3))
            .collect::<Vec<_>>()
    } else {
        vec![1.0; width]
    };
    for li in 0..l {
        let wl = t.white[li];
        let wd = t.dup[li];
        if wl <= 0.02 && wd <= 0.02 {
            continue;
        }
        let source = (t.top[li].round() - 1.0).clamp(ACTIVE_FIRST as f64, (l - 1) as f64) as usize;
        if wl <= 0.02 {
            for x in ACTIVE_START..SPL {
                y[li * SPL + x] = src[source * SPL + x] * (1.0 - n("wr_dup_dark") * wd);
            }
            continue;
        }
        let source = if wd > 0.02 { source } else { li };
        let a = 1.0 + n("wr_dup") * r.range(-0.1, 0.7);
        let b = n("wr_dup") * r.range(0.0, 45.0);
        let row = &src[source * SPL + ACTIVE_START..(source + 1) * SPL];
        let cov = if wl < 0.99 {
            wl
        } else if r.uniform() < 0.25 * n("wr_ragged") {
            r.range(0.65, 1.0)
        } else {
            1.0
        };
        let cov = if wl >= 0.99 {
            1.0 - (1.0 - cov) * (0.4 + 0.6 * n("wr_ragged"))
        } else {
            cov.powf(0.5 + 0.5 * (1.0 - n("wr_ragged")))
        };
        let coverage = ((cov * width as f64) as usize).max(1).min(width);
        let x0 = if cov < 0.999 {
            (r.uniform() * (width - coverage) as f64) as usize
        } else {
            0
        };
        let mask = smooth_edges(coverage, 40.min((coverage / 2).max(1)));
        let mut white = n("wr_white") * (wl * 1.3).min(1.0) * r.range(0.85, 1.0);
        let noise = iir(&r.normals(width, 1.0), 0.3, false);
        let mut level: Vec<_> = noise.iter().map(|v| 0.85 + 0.08 * v).collect();
        if grey {
            let mut start = li;
            let mut end = li;
            while start > 0 && t.dup[start - 1] > 0.02 {
                start -= 1;
            }
            while end + 1 < l && t.dup[end + 1] > 0.02 {
                end += 1;
            }
            let q = ((li as f64 - t.top[li]) / (end - start + 1) as f64).clamp(0.0, 1.0);
            for x in 0..width {
                level[x] = n("wr_grey") * (1.0 - q).powf(1.3) * streak[x] + 0.02;
            }
            white = (wl * 1.3).min(1.0) * r.range(0.9, 1.0);
        }
        for x in 0..width {
            let old = interp(row, b + a * x as f64) * (1.0 - n("wr_dup_dark") * wd);
            let m = if x >= x0 && x < x0 + coverage {
                mask[x - x0] * white
            } else {
                0.0
            };
            y[li * SPL + ACTIVE_START + x] = old * (1.0 - m) + level[x] * m;
        }
    }
    for li in 0..l {
        let value =
            (1.0 - (t.white[li] * 1.6).clamp(0.0, 1.0) * n("wr_white")).min(1.0 - t.colour[li]);
        kill[li * SPL + ACTIVE_START..(li + 1) * SPL].fill(value);
    }
    kill
}
