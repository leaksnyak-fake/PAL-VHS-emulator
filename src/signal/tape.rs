use super::pal::Basis;
use super::*;
pub(super) struct Deck {
    pub os: usize,
    pub fs: f64,
    nm: f64,
    cu_gain: f64,
    ysep: Vec<Filter>,
    cbp: Filter,
    pre: Filter,
    cu_rec: Filter,
    head: Filter,
    peak: Filter,
    lhp: Filter,
    dem: Filter,
    alias: Option<Filter>,
    env: Filter,
    cu_play: Filter,
    de: Filter,
    play_y: Filter,
    sharp: Filter,
    cup: Filter,
    cnoise: Filter,
    cdoc: Filter,
    calibration: [(f64, isize, f64); 2],
    // Colour-under carrier is independent of frame/content. Cache exactly the
    // same f64 phase expression used by the original signal processing path.
    cu_phase: [Vec<f64>; 2],
}
impl Deck {
    pub fn new(p: &Params) -> Self {
        let n = |s| p.number(s);
        let (bw, nm, cm) = match p.choice("tape_speed") {
            "LP" => (0.92_f64, 1.25, 0.95),
            "EP" => (0.82, 1.6, 0.9),
            _ => (1.0, 1.0, 1.0),
        };
        let os = if p.choice("rf_rate") == "2x" { 2 } else { 1 };
        let fs = FS * os as f64;
        let mut d = Self {
            os,
            fs,
            nm,
            cu_gain: 10.0_f64.powf(n("cu_level_db") / 20.0) / 0.15,
            ysep: vec![
                lowpass(n("rec_luma_bw") * 1e6 * bw, 3, FS),
                notch(FSC, 2.0, FS),
            ],
            cbp: bandpass(
                FSC - n("chroma_rec_bw") * 1e6,
                FSC + n("chroma_rec_bw") * 1e6,
                2,
                FS,
            ),
            pre: shelf(0.7e6, n("preemph_db"), FS, false),
            cu_rec: lowpass(1.4e6 * cm, 3, FS),
            head: lowpass(n("head_bw") * 1e6 * bw.sqrt(), 3, fs),
            peak: peak(n("head_peak_mhz") * 1e6, n("head_peak_db"), 1.2, fs),
            lhp: highpass(1.4e6, 2, fs),
            dem: lowpass(4.4e6, 3, fs),
            alias: if os == 2 {
                Some(lowpass(7.0e6, 4, fs))
            } else {
                None
            },
            env: lowpass(1.2e6, 2, fs),
            cu_play: lowpass(FCU + n("chroma_play_bw") * 1e6 * cm, 3, fs),
            de: shelf(0.7e6, n("preemph_db"), FS, true),
            play_y: lowpass(n("play_luma_bw") * 1e6 * bw, 3, FS),
            sharp: lowpass(1e6, 1, FS),
            cup: bandpass(FSC - 1.1e6, FSC + 1.1e6, 2, FS),
            cnoise: lowpass(FCU + n("chroma_play_bw") * 1e6, 3, FS),
            cdoc: lowpass(1.2e6, 3, FS),
            calibration: [(1.0, 0, 0.0); 2],
            cu_phase: std::array::from_fn(|fi| (0..field_lines(fi) * SPL)
                .map(|i| TAU * (FSC + FCU) * i as f64 / FS + rotation(i / SPL, fi, p))
                .collect()),
        };
        for fi in 0..2 {
            d.calibration[fi] = d.calibrate(fi, p);
        }
        d
    }
    fn up(&self, x: &[f64]) -> Vec<f64> {
        if self.os == 2 {
            upsample2(x)
        } else {
            x.to_vec()
        }
    }
    fn down(&self, x: &[f64]) -> Vec<f64> {
        x.iter().step_by(self.os).copied().collect()
    }
    fn demod_luma(&self, rf: &[f64], p: &Params, clicks: bool) -> (Vec<f64>, Vec<f64>) {
        let (f, env) = fm_demod(&self.lhp.run(rf), self.fs);
        let mut v: Vec<_> = f
            .iter()
            .map(|f| (f - p.number("fm_sync_mhz") * 1e6) / (p.number("fm_dev_mhz") * 1e6) - 0.3)
            .collect();
        if clicks {
            let big: Vec<_> = v
                .iter()
                .map(|x| if x.abs() > 2.5 { *x } else { 0.0 })
                .collect();
            let tails = iir(&big, 1.0 - (-1.0 / (1.3e-6 * self.fs)).exp(), false);
            for (x, t) in v.iter_mut().zip(tails) {
                *x += 1.2 * t;
            }
        }
        v = self.dem.run(&v);
        if let Some(f) = &self.alias {
            v = f.run(&v);
        }
        v = self.play_y.run(&self.de.run(&self.down(&v)));
        (v, env)
    }
    fn calibrate(&self, fi: usize, p: &Params) -> (f64, isize, f64) {
        let count = 6 * SPL;
        let car: Vec<_> = (0..count)
            .map(|i| (TAU * FSC * i as f64 / FS + 0.3).cos())
            .collect();
        let lo: Vec<_> = (0..count)
            .map(|i| 2.0 * (TAU * (FSC + FCU) * i as f64 / FS + rotation(i / SPL, fi, p)).cos())
            .collect();
        let chroma = |x: &[f64]| {
            let cb = self.cbp.run(x);
            let cu = self
                .cu_rec
                .run(&cb.iter().zip(&lo).map(|(x, l)| x * l).collect::<Vec<_>>());
            let mut rf = self.up(&cu);
            for x in &mut rf {
                *x *= self.cu_gain;
            }
            rf = self.peak.run(&self.head.run(&rf));
            let mut cp = self.down(&self.cu_play.run(&rf));
            for x in &mut cp {
                *x /= self.cu_gain;
            }
            let out = self
                .cup
                .run(&cp.iter().zip(&lo).map(|(x, l)| x * l).collect::<Vec<_>>());
            (cp, out)
        };
        let burst = smooth_edges(BURST_LEN, 6);
        let mut xb = vec![0.0; count];
        for line in 0..6 {
            for (i, w) in burst.iter().enumerate() {
                let j = line * SPL + BURST_START + i;
                xb[j] = 0.15 * w * car[j];
            }
        }
        let (cp, cout) = chroma(&xb);
        let a = 5 * SPL + BURST_START - 30;
        let end = 5 * SPL + BURST_START + BURST_LEN + 90;
        let centroid = |x: &[f64]| {
            let z = analytic_exact(x);
            let mut sum = 0.0;
            let mut energy = 0.0;
            for i in a..end {
                let e = z[i].norm_sqr();
                sum += i as f64 * e;
                energy += e;
            }
            sum / energy.max(1e-30)
        };
        let cin = centroid(&xb);
        let dc = (centroid(&cp) - cin).round() as isize;
        let cd = centroid(&cout) - cin;
        let start = (5 * SPL + BURST_START + 4) as isize + dc;
        let endb = (5 * SPL + BURST_START + BURST_LEN - 4) as isize + dc;
        let rms = |x: &[f64]| (x.iter().map(|v| v * v).sum::<f64>() / x.len() as f64).sqrt();
        let (cp_s, _) = chroma(&car.iter().map(|x| 0.15 * x).collect::<Vec<_>>());
        let loss = rms(&cp[start.max(0) as usize..endb.min(count as isize) as usize])
            / rms(&cp_s[5 * SPL + SPL / 2 - 150..5 * SPL + SPL / 2 + 150]);
        let step: Vec<_> = (0..count)
            .map(|i| 0.5 / (1.0 + (-((i as f64 - (5 * SPL + 500) as f64) / 2.0)).exp()))
            .collect();
        let mut y = self.pre.run(&chain(&self.ysep, &step));
        for x in &mut y {
            *x = x.clamp(p.number("dark_clip"), p.number("white_clip"));
        }
        let rf = fm_mod(
            &self.up(&y),
            p.number("fm_sync_mhz") * 1e6,
            p.number("fm_dev_mhz") * 1e6,
            self.fs,
            None,
        );
        let rf = self.peak.run(&self.head.run(&rf));
        let (v, _) = self.demod_luma(&rf, p, false);
        let edge = |x: &[f64]| {
            let base = 5 * SPL + 400;
            let mut numerator = 0.0;
            let mut denominator = 0.0;
            for i in 0..249 {
                let delta = x[base + i + 1] - x[base + i];
                numerator += i as f64 * delta;
                denominator += delta;
            }
            numerator / denominator
        };
        (loss.max(1e-4), dc, cd - (edge(&v) - edge(&step)))
    }
    pub fn process(
        &self,
        x: &[f64],
        fi: usize,
        frame: u64,
        p: &Params,
        b: &Basis,
        mut taps: Option<&mut BTreeMap<String, Vec<f64>>>,
    ) -> Vec<f64> {
        let n = |s| p.number(s);
        let l = field_lines(fi);
        let count = l * SPL;
        let mut rng = Rng::new(&[n("seed") as u64, frame, fi as u64, 5]);
        let (loss, dc, align) = self.calibration[fi];
        let cdel = n("chroma_delay_ns") * FS / 1e9 - align;
        let mut y = self.pre.run(&chain(&self.ysep, x));
        for v in &mut y {
            *v = v.clamp(n("dark_clip"), n("white_clip"));
        }
        let y2 = self.up(&y);
        let fm = fm_mod(
            &y2,
            n("fm_sync_mhz") * 1e6,
            n("fm_dev_mhz") * 1e6,
            self.fs,
            None,
        );
        let cb = self.cbp.run(x);
        let phase = &self.cu_phase[fi];
        let cu = self.cu_rec.run(
            &cb.iter()
                .zip(phase)
                .map(|(v, ph)| v * 2.0 * ph.cos())
                .collect::<Vec<_>>(),
        );
        let cu2 = self.up(&cu);
        let mut tape: Vec<_> = fm
            .iter()
            .zip(cu2)
            .map(|(f, c)| f + c * self.cu_gain)
            .collect();
        if p.choice("hs_model") == "RF switch" && n("hs_phase_deg") > 0.0 {
            let start = (switch_line(p, l, fi, frame) * SPL as f64 * self.os as f64)
                .round()
                .max(0.0) as usize;
            let switched = fm_mod(
                &y2,
                n("fm_sync_mhz") * 1e6,
                n("fm_dev_mhz") * 1e6,
                self.fs,
                Some((
                    start,
                    n("hs_phase_deg").to_radians() * if fi == 0 { 1.0 } else { -1.0 },
                )),
            );
            for i in 0..tape.len() {
                tape[i] += switched[i] - fm[i];
            }
        }
        tape = damage::line_warp(&tape, l, fi, frame, p, self.os);
        let (env, wr_fac) = damage::envelope(l, fi, frame, p, self.os, &mut rng);
        let wn = rng.normals(
            tape.len(),
            n("tape_noise") * self.nm * (self.os as f64 / 2.0).sqrt(),
        );
        let tilt = highpass(6e6, 1, self.fs);
        let gain = tilt.response(4.3e6, self.fs).norm();
        let noise = tilt.zero_run(&wn);
        let rf = self.peak.run(
            &self.head.run(
                &tape
                    .iter()
                    .zip(&env)
                    .zip(noise)
                    .map(|((t, e), noise)| t * e + noise / gain)
                    .collect::<Vec<_>>(),
            ),
        );
        let (mut yv, envd) = self.demod_luma(&rf, p, true);
        if n("sharpen") > 0.0 {
            let smooth = self.sharp.run(&yv);
            for (i, v) in yv.iter_mut().enumerate() {
                *v += n("sharpen") * 0.5 * (2.0 * (*v - smooth[i])).tanh();
            }
        }
        let mut cp = self.down(&self.cu_play.run(&rf));
        for v in &mut cp {
            *v /= self.cu_gain;
        }
        if n("chroma_noise") > 0.0 {
            let noise = self
                .cnoise
                .run(&rng.normals(count, n("chroma_noise") * 2.7));
            for (v, n) in cp.iter_mut().zip(noise) {
                *v += n;
            }
        }
        let ybase = yv.clone();
        let cbase = cp.clone();
        let envl = self.down(&self.env.run(&envd));
        let threshold = median(&envl) * 0.5;
        let mut bad = vec![false; count];
        for i in 0..count {
            if envl[i] < threshold {
                for v in &mut bad[i.saturating_sub(11)..(i + 13).min(count)] {
                    *v = true;
                }
            }
        }
        let mut lwin = vec![0.0; l];
        for li in 0..l {
            let lw = mean(&env[li * SPL * self.os..(li + 1) * SPL * self.os])
                / (1.0 - 0.5 * n("tape_wear"))
                / wr_fac[li].max(0.05);
            lwin[li] = ((0.6 - lw) / 0.45).clamp(0.0, 1.0);
        }
        if p.boolean("doc") {
            let old = yv.clone();
            for i in 0..count {
                if bad[i] {
                    if lwin[i / SPL] < 0.6 {
                        yv[i] = old[(i + count - SPL) % count];
                    }
                    cp[i] = 0.0;
                }
            }
        }
        damage::sparse_snow(&mut yv, l, fi, frame, p);
        damage::head_snow(&mut yv, l, fi, frame, p);
        let (_, wr) = damage::profiles(l, fi, frame, p);
        if n("wrinkle") > 0.0 {
            for i in 0..count {
                let m = (wr[i / SPL] * 2.0).clamp(0.0, 1.0);
                yv[i] = yv[i] * (1.0 - m) + ybase[i] * m;
                cp[i] = cp[i] * (1.0 - m) + cbase[i] * m;
            }
        }
        let wr_kill = damage::travel_overlay(&mut yv, l, fi, frame, p);
        damage::tracking_snow(&mut yv, &lwin, l, fi, frame, p);
        if p.boolean("acc") {
            let mut gain = Vec::new();
            for li in 0..l {
                let a = (li * SPL + BURST_START + 4) as isize + dc;
                let end = (li * SPL + BURST_START + BURST_LEN - 4) as isize + dc;
                let slice = &cp[a.clamp(0, count as isize - 1) as usize
                    ..end.clamp(1, count as isize) as usize];
                let rms =
                    (slice.iter().map(|v| v * v).sum::<f64>() / slice.len().max(1) as f64).sqrt();
                gain.push((0.15 / 2.0_f64.sqrt() * loss / rms.max(1e-5)).clamp(0.2, 5.0));
            }
            let med = median(&gain[7..]);
            for g in &mut gain[..7] {
                *g = med;
            }
            for g in &mut gain {
                *g *= ((4.0 - *g) / 1.5).clamp(0.0, 1.0);
            }
            let gain = iir(&gain, 0.5, true);
            let a = BURST_START as isize + dc - 3;
            let end = BURST_START as isize + dc + BURST_LEN as isize + 3;
            let win = smooth_edges((end - a) as usize, 8);
            for i in 0..count {
                cp[i] *= gain[i / SPL];
                let k = (i % SPL) as isize - a;
                if k >= 0 && (k as usize) < win.len() {
                    cp[i] *= 1.0 + (1.0 / loss - 1.0) * win[k as usize];
                }
            }
        }
        for i in 0..count {
            cp[i] *= n("chroma_gain") * wr_kill[i];
        }
        let d = damage::timebase(l, fi, frame, p, &mut rng);
        yv = displace(&yv, &d);
        let cd: Vec<_> = d.iter().map(|x| x + cdel).collect();
        cp = displace(&cp, &cd);
        let lo: Vec<_> = phase
            .iter()
            .map(|v| v + n("lo_phase_err").to_radians())
            .collect();
        let first_cout = self.cup.run(
            &cp.iter()
                .zip(&lo)
                .map(|(x, ph)| x * 2.0 * ph.cos())
                .collect::<Vec<_>>(),
        );
        let eps = self.burst_phase(&first_cout, &cd, b, p, l);
        let (gl_ph, gl_gain) = damage::chroma_glitch(l, fi, frame, p);
        let a = BURST_START as isize + dc - 4;
        let end = BURST_START as isize + dc + BURST_LEN as isize + 4;
        let mut cout = self.cup.run(
            &(0..count)
                .map(|i| {
                    let picture = if ((i % SPL) as isize) >= a && ((i % SPL) as isize) < end {
                        0.0
                    } else {
                        1.0
                    };
                    cp[i]
                        * (1.0 + (gl_gain[i / SPL] - 1.0) * picture)
                        * 2.0
                        * (lo[i] - eps[i / SPL] + gl_ph[i / SPL] * picture).cos()
                })
                .collect::<Vec<_>>(),
        );
        if p.boolean("doc") && bad.iter().any(|v| *v) {
            let bd = displace(
                &bad.iter()
                    .map(|v| if *v { 1.0 } else { 0.0 })
                    .collect::<Vec<_>>(),
                &cd,
            );
            cout = self.doc_chroma(&cout, &bd, b);
        }
        let mut out: Vec<_> = yv.iter().zip(&cout).map(|(y, c)| y + c).collect();
        if p.choice("hs_model") != "off" && n("hs_mask_lines") > 0.0 {
            let end = ACTIVE_FIRST + FIELD_HEIGHT;
            let start = end.saturating_sub(n("hs_mask_lines") as usize);
            for li in start..end {
                out[li * SPL + ACTIVE_START..li * SPL + ACTIVE_START + ACTIVE_LEN].fill(0.0);
            }
        }
        if let Some(t) = taps.as_mut() {
            for (k, v) in [
                ("rec_luma", y),
                ("fm", fm),
                ("tape", rf),
                ("c_under", cu),
                ("luma_demod", yv),
                ("c_play", cp),
                ("c_out", cout),
                ("rf_env", env),
            ] {
                t.insert(k.into(), v);
            }
        }
        out
    }
    fn burst_phase(&self, cout: &[f64], d: &[f64], b: &Basis, p: &Params, l: usize) -> Vec<f64> {
        let mut e = Vec::new();
        for li in 7..l {
            let mut x = 0.0;
            let mut y = 0.0;
            for k in BURST_START + 6..BURST_START + BURST_LEN - 6 {
                let pos = ((li * SPL + k) as f64 + d[li * SPL])
                    .round()
                    .clamp(0.0, (cout.len() - 1) as f64) as usize;
                x += cout[pos] * 2.0 * b.sin[pos];
                y += cout[pos] * 2.0 * b.cos[pos];
            }
            let reference = if b.switch[li] > 0.0 {
                135.0_f64.to_radians()
            } else {
                225.0_f64.to_radians()
            };
            e.push((y.atan2(x) - reference + PI).rem_euclid(TAU) - PI);
        }
        let med = e
            .iter()
            .map(|v| v.sin())
            .sum::<f64>()
            .atan2(e.iter().map(|v| v.cos()).sum::<f64>());
        let dyns = iir(
            &e.iter()
                .map(|v| (v - med + PI).rem_euclid(TAU) - PI)
                .collect::<Vec<_>>(),
            p.number("apc_speed"),
            false,
        );
        let mut out = vec![med + dyns[0]; l];
        for (i, v) in dyns.iter().enumerate() {
            out[i + 7] = med + v;
        }
        out
    }
    fn doc_chroma(&self, cout: &[f64], bad: &[f64], b: &Basis) -> Vec<f64> {
        let len = cout.len();
        let mut u = self.cdoc.run(
            &(0..len)
                .map(|i| cout[i] * 2.0 * b.sin[i])
                .collect::<Vec<_>>(),
        );
        let mut v = self.cdoc.run(
            &(0..len)
                .map(|i| cout[i] * 2.0 * b.cos[i])
                .collect::<Vec<_>>(),
        );
        for i in 0..len {
            v[i] *= b.switch[i / SPL];
        }
        let mut todo: Vec<_> = bad.iter().map(|v| *v > 0.3).collect();
        for _ in 0..4 {
            let old = todo.clone();
            let uu = u.clone();
            let vv = v.clone();
            for i in 0..len {
                let prev = (i + len - SPL) % len;
                if old[i] && !old[prev] {
                    u[i] = uu[prev];
                    v[i] = vv[prev];
                    todo[i] = false;
                }
            }
        }
        (0..len)
            .map(|i| {
                if bad[i] > 0.3 && !todo[i] {
                    u[i] * b.sin[i] + v[i] * b.switch[i / SPL] * b.cos[i]
                } else {
                    cout[i]
                }
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn calibration_matches_reference_burst_loss_and_chroma_luma_alignment() {
        let mut p = Params::default();
        p.set("rf_rate", json!("1x")).unwrap();
        let deck = Deck::new(&p);
        for (actual, expected) in deck.calibration.into_iter().zip([
            (0.9355650969538386, 14, 11.783193933048494),
            (0.9420571821173658, 16, 13.74530405720401),
        ]) {
            assert!(
                (actual.0 - expected.0).abs() < 1e-9,
                "burst loss {:?} != {:?}",
                actual,
                expected
            );
            assert_eq!(actual.1, expected.1);
            assert!(
                (actual.2 - expected.2).abs() < 1e-6,
                "chroma alignment {:?} != {:?}",
                actual,
                expected
            );
        }
    }
}
