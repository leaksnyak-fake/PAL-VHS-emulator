use super::*;
pub(super) struct Basis {
    pub sin: Vec<f64>,
    pub cos: Vec<f64>,
    pub switch: Vec<f64>,
}
impl Basis {
    pub fn new(frame: u64, fi: usize) -> Self {
        let l = field_lines(fi);
        let first = (frame % 4) * 625 + if fi == 0 { 0 } else { 313 };
        let mut sin = Vec::with_capacity(l * SPL);
        let mut cos = Vec::with_capacity(l * SPL);
        let mut switch = Vec::new();
        for line in 0..l {
            let global = first + line as u64;
            switch.push(if global % 2 == 0 { 1.0 } else { -1.0 });
            for n in 0..SPL {
                let ph = TAU * ((CPL * global as f64 + CPL * n as f64 / SPL as f64) % 1.0);
                sin.push(ph.sin());
                cos.push(ph.cos());
            }
        }
        Self { sin, cos, switch }
    }
}
fn template(kind: usize) -> Vec<f64> {
    let mut raw = vec![0.0; SPL];
    let spans = match kind {
        1 => vec![(0, 42), (567, 42)],
        2 => vec![(0, 484), (567, 484)],
        _ => vec![(0, SYNC_W)],
    };
    for (s, w) in spans {
        for v in &mut raw[s..s + w] {
            *v = -0.3;
        }
    }
    let r = 6;
    let kernel: Vec<_> = (-r..=r)
        .map(|i| (-0.5 * (i as f64 / 1.4).powi(2)).exp())
        .collect();
    let sum: f64 = kernel.iter().sum();
    (0..SPL)
        .map(|i| {
            kernel
                .iter()
                .enumerate()
                .map(|(j, k)| {
                    let p = i as isize + j as isize - r as isize;
                    if p >= 0 && (p as usize) < SPL {
                        raw[p as usize] * k / sum
                    } else {
                        0.0
                    }
                })
                .sum()
        })
        .collect()
}
fn cubic(t: f64) -> f64 {
    let x = t.abs();
    let a = -0.75;
    if x <= 1.0 {
        (a + 2.0) * x * x * x - (a + 3.0) * x * x + 1.0
    } else if x < 2.0 {
        a * x * x * x - 5.0 * a * x * x + 8.0 * a * x - 4.0 * a
    } else {
        0.0
    }
}
pub(super) fn encode(rgb: Option<&[u8]>, fi: usize, p: &Params, b: &Basis) -> Vec<f64> {
    let l = field_lines(fi);
    let mut comp = vec![0.0; l * SPL];
    static TEMPLATES: std::sync::OnceLock<[Vec<f64>; 3]> = std::sync::OnceLock::new();
    static BURST: std::sync::OnceLock<Vec<f64>> = std::sync::OnceLock::new();
    let tpl = TEMPLATES.get_or_init(|| [template(0), template(1), template(2)]);
    let burst = BURST.get_or_init(|| smooth_edges(BURST_LEN, 6));
    for line in 0..l {
        let kind = if line < 2 || (5..7).contains(&line) {
            1
        } else if line < 5 {
            2
        } else {
            0
        };
        comp[line * SPL..(line + 1) * SPL].copy_from_slice(&tpl[kind]);
        if line >= 7 {
            for (k, w) in burst.iter().enumerate() {
                let i = line * SPL + BURST_START + k;
                comp[i] += 0.15 * w * (-b.sin[i] + b.switch[line] * b.cos[i]);
            }
        }
    }
    if let Some(rgb) = rgb {
        let fy = lowpass(p.number("enc_luma_bw") * 1e6, 4, FS);
        let fc = lowpass(p.number("enc_chroma_bw") * 1e6, 4, FS);
        for line in 0..FIELD_HEIGHT {
            let mut row = vec![[0.0; 3]; WIDTH];
            for (x, v) in row.iter_mut().enumerate() {
                let i = (line * WIDTH + x) * 3;
                let mut c = [0.0; 3];
                for k in 0..3 {
                    c[k] = ((rgb[i + k] as f64 / 255.0 - 0.5) * p.number("in_contrast")
                        + 0.5
                        + p.number("in_brightness"))
                    .clamp(0.0, 1.0);
                }
                let y = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2];
                *v = [
                    y,
                    0.493 * (c[2] - y) * p.number("in_saturation"),
                    0.877 * (c[0] - y) * p.number("in_saturation"),
                ];
            }
            let mut channels = [
                vec![0.0; ACTIVE_LEN],
                vec![0.0; ACTIVE_LEN],
                vec![0.0; ACTIVE_LEN],
            ];
            for x in 0..ACTIVE_LEN {
                let q = (x as f64 + 0.5) * WIDTH as f64 / ACTIVE_LEN as f64 - 0.5;
                let base = q.floor() as isize;
                for j in -1..=2 {
                    let ix = (base + j).clamp(0, WIDTH as isize - 1) as usize;
                    let w = cubic(q - (base + j) as f64);
                    for c in 0..3 {
                        channels[c][x] += row[ix][c] * w;
                    }
                }
            }
            channels[0] = fy.filtfilt(&channels[0]);
            channels[1] = fc.filtfilt(&channels[1]);
            channels[2] = fc.filtfilt(&channels[2]);
            for x in 0..ACTIVE_LEN {
                let i = (line + ACTIVE_FIRST) * SPL + ACTIVE_START + x;
                comp[i] += 0.7
                    * (channels[0][x]
                        + channels[1][x] * b.sin[i]
                        + channels[2][x] * b.switch[line + ACTIVE_FIRST] * b.cos[i]);
            }
        }
    }
    comp
}
fn detect(stream: &[f64], l: usize) -> (Vec<f64>, Vec<f64>, f64) {
    let d = lowpass(1.2e6, 2, FS).run(stream);
    let blank0 = median(
        &(8..l)
            .map(|n| mean(&d[n * SPL + 150..n * SPL + 182]))
            .collect::<Vec<_>>(),
    );
    let tip = median(
        &(8..l)
            .map(|n| {
                blank0
                    - d[n * SPL - 240..n * SPL + 520]
                        .iter()
                        .copied()
                        .fold(f64::INFINITY, f64::min)
            })
            .collect::<Vec<_>>(),
    );
    let threshold = blank0 - 0.5 * tip;
    let mut edges = Vec::new();
    let mut blank = Vec::new();
    for n in 8..l {
        let start = n * SPL - 240;
        let window = &d[start..start + 760];
        let k = window.iter().position(|v| *v < threshold);
        let edge = if let Some(k) = k.filter(|k| *k > 0) {
            let a = window[k - 1];
            let bb = window[k];
            let frac = if (a - bb).abs() > 1e-9 {
                ((a - threshold) / (a - bb)).clamp(0.0, 1.0)
            } else {
                0.0
            };
            (start + k - 1) as f64 + frac
        } else {
            f64::NAN
        };
        edges.push(edge);
        let base = if edge.is_nan() {
            (n * SPL) as f64
        } else {
            edge
        };
        blank.push(
            (0..32)
                .map(|i| {
                    d[(base + 150.0 + i as f64)
                        .round()
                        .clamp(0.0, (d.len() - 1) as f64) as usize]
                })
                .sum::<f64>()
                / 32.0,
        );
    }
    (edges, blank, tip)
}
pub(super) struct Decoder {
    c0: f64,
}
impl Decoder {
    pub fn new(p: &Params, b: &Basis) -> Self {
        let x = encode(None, 1, p, b);
        let (e, _, _) = detect(&x, 312);
        Self {
            c0: e
                .iter()
                .enumerate()
                .filter(|(_, x)| x.is_finite())
                .map(|(i, x)| x - ((i + 8) * SPL) as f64)
                .sum::<f64>()
                / e.iter().filter(|x| x.is_finite()).count() as f64,
        }
    }
    pub fn decode(&self, stream: &[f64], fi: usize, p: &Params, b: &Basis) -> Vec<u8> {
        let l = field_lines(fi);
        let (edge, blank, tip) = detect(stream, l);
        let mut last = 0.0;
        let dev: Vec<_> = edge
            .iter()
            .enumerate()
            .map(|(i, e)| {
                if e.is_finite() {
                    last = e - ((i + 8) * SPL) as f64 - self.c0;
                }
                last
            })
            .collect();
        let afc = iir(&dev, p.number("tv_afc"), false);
        let agc = 0.3 / tip.max(0.05);
        let yf = [
            lowpass(p.number("tv_luma_bw") * 1e6, 3, FS),
            notch(FSC, 2.5, FS),
        ];
        let ys = chain(&yf, stream);
        let dy = yf.iter().map(|f| f.group_delay(0.5e6, FS)).sum::<f64>();
        let cb = bandpass(FSC - 1.4e6, FSC + 1.4e6, 2, FS);
        let cl = lowpass(p.number("tv_chroma_bw") * 1e6, 3, FS);
        let c = cb.run(stream);
        let us = cl.run(
            &c.iter()
                .zip(&b.sin)
                .map(|(c, s)| c * 2.0 * s)
                .collect::<Vec<_>>(),
        );
        let vs = cl.run(
            &c.iter()
                .zip(&b.cos)
                .map(|(c, s)| c * 2.0 * s)
                .collect::<Vec<_>>(),
        );
        let dc = cb.group_delay(FSC, FS) + cl.group_delay(0.05e6, FS);
        let mut bursts = Vec::new();
        let mut vote = 0.0;
        for n in 8..l {
            let base = (n * SPL + BURST_START) as f64 + afc[n - 8] + dc;
            let bx = (6..BURST_LEN - 6)
                .map(|k| interp(&us, base + k as f64))
                .sum::<f64>()
                / 28.0;
            let by = (6..BURST_LEN - 6)
                .map(|k| interp(&vs, base + k as f64))
                .sum::<f64>()
                / 28.0;
            vote += if by > 0.0 { 1.0 } else { -1.0 } * if n % 2 == 0 { 1.0 } else { -1.0 };
            bursts.push((bx, by));
        }
        let s0 = if vote >= 0.0 { 1.0 } else { -1.0 };
        let mut phases = Vec::new();
        let mut amps = Vec::new();
        let mut prev = 0.0;
        for (i, (x, y)) in bursts.iter().enumerate() {
            let sign = s0 * if i % 2 == 0 { 1.0 } else { -1.0 };
            let reference = if sign > 0.0 {
                135.0_f64.to_radians()
            } else {
                225.0_f64.to_radians()
            };
            let mut e = (y.atan2(*x) - reference + PI).rem_euclid(TAU) - PI;
            if i > 0 {
                e = prev + (e - prev + PI).rem_euclid(TAU) - PI;
            }
            prev = e;
            phases.push(e);
            amps.push((x * x + y * y).sqrt() / 2.0_f64.sqrt());
        }
        let eps = iir(&phases, p.number("tv_apc"), true);
        let smooth_amp = iir(&amps, p.number("tv_apc"), true);
        let kill = median(&amps) < 0.03;
        let mut yuv = vec![[0.0; 3]; FIELD_HEIGHT * ACTIVE_LEN];
        for line in 0..FIELD_HEIGHT {
            let n = line + ACTIVE_FIRST;
            let j = n - 8;
            let e = eps[j];
            let gain = (0.15 / smooth_amp[j].max(1e-4)).clamp(0.3, 3.0)
                * ((smooth_amp[j] / 0.15 - 0.25) / 0.2).clamp(0.0, 1.0)
                / 0.7;
            let sign = s0 * if n % 2 == 0 { 1.0 } else { -1.0 };
            for x in 0..ACTIVE_LEN {
                let base = (n * SPL + ACTIVE_START + x) as f64 + afc[j];
                let y = (interp(&ys, base + dy) - blank[j]) * agc / 0.7;
                let u = interp(&us, base + dc);
                let v = interp(&vs, base + dc);
                yuv[line * ACTIVE_LEN + x] = [
                    y,
                    if kill {
                        0.0
                    } else {
                        (u * e.cos() + v * e.sin()) * gain
                    },
                    if kill {
                        0.0
                    } else {
                        (-u * e.sin() + v * e.cos()) * gain * sign
                    },
                ];
            }
        }
        if p.choice("tv_decoder") == "PAL-D" {
            for line in (1..FIELD_HEIGHT).rev() {
                for x in 0..ACTIVE_LEN {
                    for c in 1..3 {
                        yuv[line * ACTIVE_LEN + x][c] = 0.5
                            * (yuv[line * ACTIVE_LEN + x][c] + yuv[(line - 1) * ACTIVE_LEN + x][c]);
                    }
                }
            }
        }
        let hue = p.number("tv_hue").to_radians();
        let sat = p.number("tv_saturation");
        let contrast = p.number("tv_contrast");
        let bright = p.number("tv_brightness");
        for pixel in &mut yuv {
            let [y, u, v] = *pixel;
            let uu = (u * hue.cos() - v * hue.sin()) * sat;
            let vv = (u * hue.sin() + v * hue.cos()) * sat;
            *pixel = [y + 1.140 * vv, y - 0.395 * uu - 0.581 * vv, y + 2.032 * uu];
            for c in pixel {
                *c = (*c - 0.5) * contrast + 0.5 + bright;
            }
        }
        let ratio = ACTIVE_LEN as f64 / WIDTH as f64;
        let mut out = vec![0; WIDTH * FIELD_HEIGHT * 3];
        for line in 0..FIELD_HEIGHT {
            for x in 0..WIDTH {
                let a = x as f64 * ratio;
                let end = (x + 1) as f64 * ratio;
                let mut val = [0.0; 3];
                for k in a.floor() as usize..end.ceil() as usize {
                    let weight = (end.min((k + 1) as f64) - a.max(k as f64)) / ratio;
                    for c in 0..3 {
                        val[c] += yuv[line * ACTIVE_LEN + k.min(ACTIVE_LEN - 1)][c] * weight;
                    }
                }
                for c in 0..3 {
                    out[(line * WIDTH + x) * 3 + c] = (val[c].clamp(0.0, 1.0) * 255.0 + 0.5) as u8;
                }
            }
        }
        out
    }
}
