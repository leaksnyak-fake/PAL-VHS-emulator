//! Double precision waveform DSP. SOS filters use matched constant initial states.
use num_complex::Complex64 as C;
use rustfft::FftPlanner;
use std::cell::RefCell;
use std::f64::consts::{PI, TAU};

#[derive(Clone, Debug)]
pub struct Filter(pub Vec<[f64; 6]>);
impl Filter {
    pub fn run(&self, x: &[f64]) -> Vec<f64> {
        self.process(x, true)
    }
    pub fn zero_run(&self, x: &[f64]) -> Vec<f64> {
        self.process(x, false)
    }
    fn process(&self, x: &[f64], matched: bool) -> Vec<f64> {
        let mut y = x.to_vec();
        if x.is_empty() {
            return y;
        }
        for s in &self.0 {
            let [b0, b1, b2, _, a1, a2] = *s;
            let v = if matched { y[0] } else { 0.0 };
            let out = v * (b0 + b1 + b2) / (1.0 + a1 + a2);
            let (mut z1, mut z2) = (out - b0 * v, b2 * v - a2 * out);
            for u in &mut y {
                let input = *u;
                *u = b0 * input + z1;
                z1 = b1 * input - a1 * (*u) + z2;
                z2 = b2 * input - a2 * (*u);
            }
        }
        y
    }
    pub fn response(&self, f: f64, fs: f64) -> C {
        let z = C::from_polar(1.0, -TAU * f / fs);
        self.0.iter().fold(C::new(1.0, 0.0), |h, s| {
            h * (s[0] + s[1] * z + s[2] * z * z) / (1.0 + s[4] * z + s[5] * z * z)
        })
    }
    pub fn group_delay(&self, f: f64, fs: f64) -> f64 {
        // -d arg(H)/dw, evaluated analytically for each SOS. Finite phase
        // differences lose precision in the chroma/luma alignment calibration.
        let z = C::from_polar(1.0, -TAU * f / fs);
        self.0
            .iter()
            .map(|s| {
                let numerator = s[0] + s[1] * z + s[2] * z * z;
                let denominator = 1.0 + s[4] * z + s[5] * z * z;
                ((s[1] * z + 2.0 * s[2] * z * z) / numerator
                    - (s[4] * z + 2.0 * s[5] * z * z) / denominator)
                    .re
            })
            .sum()
    }
    pub fn filtfilt(&self, x: &[f64]) -> Vec<f64> {
        if x.len() < 2 {
            return x.to_vec();
        }
        let ntaps = 2 * self.0.len() + 1
            - self
                .0
                .iter()
                .filter(|s| s[2] == 0.0)
                .count()
                .min(self.0.iter().filter(|s| s[5] == 0.0).count());
        let edge = (3 * ntaps).min(x.len() - 1);
        let mut xp = Vec::with_capacity(x.len() + 2 * edge);
        for i in (1..=edge).rev() {
            xp.push(2.0 * x[0] - x[i]);
        }
        xp.extend_from_slice(x);
        for i in 1..=edge {
            xp.push(2.0 * x[x.len() - 1] - x[x.len() - 1 - i]);
        }
        let mut y = self.run(&xp);
        y.reverse();
        y = self.run(&y);
        y.reverse();
        y[edge..edge + x.len()].to_vec()
    }
}
fn biquad(b: [f64; 3], a: [f64; 3]) -> Filter {
    Filter(vec![[
        b[0] / a[0],
        b[1] / a[0],
        b[2] / a[0],
        1.0,
        a[1] / a[0],
        a[2] / a[0],
    ]])
}
fn butter_poles(n: usize) -> Vec<C> {
    (0..n)
        .map(|k| C::from_polar(1.0, PI * (2 * k + n + 1) as f64 / (2 * n) as f64))
        .collect()
}
fn from_roots(mut poles: Vec<C>, zeros: Vec<f64>, norm: f64, fs: f64) -> Filter {
    poles.sort_by(|a, b| a.norm().total_cmp(&b.norm()));
    let mut ss = Vec::new();
    let mut zi = 0;
    while !poles.is_empty() {
        let p = poles.remove(0);
        let q = if p.im.abs() > 1e-8 {
            let j = poles
                .iter()
                .enumerate()
                .min_by(|(_, a), (_, b)| {
                    (**a - p.conj()).norm().total_cmp(&(**b - p.conj()).norm())
                })
                .unwrap()
                .0;
            Some(poles.remove(j))
        } else if let Some(j) = poles.iter().position(|q| q.im.abs() < 1e-8) {
            Some(poles.remove(j))
        } else {
            None
        };
        let z = zeros[zi];
        zi += 1;
        if let Some(q) = q {
            let z2 = zeros[zi];
            zi += 1;
            ss.push([1.0, -z - z2, z * z2, 1.0, -(p + q).re, (p * q).re]);
        } else {
            ss.push([1.0, -z, 0.0, 1.0, -p.re, 0.0]);
        }
    }
    let mut f = Filter(ss);
    let gain = 1.0 / f.response(norm, fs).norm();
    for b in &mut f.0[0][0..3] {
        *b *= gain;
    }
    f
}
pub fn lowpass(fc: f64, n: usize, fs: f64) -> Filter {
    let wc = 2.0 * fs * (PI * fc.min(fs * 0.49).max(1.0) / fs).tan();
    let poles = butter_poles(n)
        .iter()
        .map(|p| {
            let s = p * wc;
            (2.0 * fs + s) / (2.0 * fs - s)
        })
        .collect();
    from_roots(poles, vec![-1.0; n], 0.0, fs)
}
pub fn highpass(fc: f64, n: usize, fs: f64) -> Filter {
    let wc = 2.0 * fs * (PI * fc.min(fs * 0.49).max(1.0) / fs).tan();
    let poles = butter_poles(n)
        .iter()
        .map(|p| {
            let s = wc / p;
            (2.0 * fs + s) / (2.0 * fs - s)
        })
        .collect();
    from_roots(poles, vec![1.0; n], fs / 2.0, fs)
}
pub fn bandpass(f1: f64, f2: f64, n: usize, fs: f64) -> Filter {
    let w1 = 2.0 * fs * (PI * f1.max(1.0) / fs).tan();
    let w2 = 2.0 * fs * (PI * f2.min(fs * 0.49) / fs).tan();
    let bw = w2 - w1;
    let w0 = (w1 * w2).sqrt();
    let mut poles = Vec::new();
    for p in butter_poles(n) {
        let a = p * bw / 2.0;
        let root = (a * a - w0 * w0).sqrt();
        for s in [a + root, a - root] {
            poles.push((2.0 * fs + s) / (2.0 * fs - s));
        }
    }
    // Pair a zero at DC with a zero at Nyquist in every section.
    let zeros = (0..2 * n)
        .map(|i| if i % 2 == 0 { 1.0 } else { -1.0 })
        .collect();
    from_roots(poles, zeros, fs / PI * (w0 / (2.0 * fs)).atan(), fs)
}
pub fn notch(fc: f64, q: f64, fs: f64) -> Filter {
    let w = TAU * fc / fs;
    let beta = (w / q / 2.0).tan();
    let g = 1.0 / (1.0 + beta);
    biquad(
        [g, -2.0 * g * w.cos(), g],
        [1.0, -2.0 * g * w.cos(), 2.0 * g - 1.0],
    )
}
pub fn shelf(fz: f64, db: f64, fs: f64, inverse: bool) -> Filter {
    let wz = TAU * fz;
    let wp = wz * 10.0_f64.powf(db / 20.0);
    let (num, den) = if inverse {
        (1.0 / wp, 1.0 / wz)
    } else {
        (1.0 / wz, 1.0 / wp)
    };
    biquad(
        [1.0 + 2.0 * fs * num, 1.0 - 2.0 * fs * num, 0.0],
        [1.0 + 2.0 * fs * den, 1.0 - 2.0 * fs * den, 0.0],
    )
}
pub fn peak(fc: f64, db: f64, q: f64, fs: f64) -> Filter {
    let a = 10.0_f64.powf(db / 40.0);
    let w = TAU * fc / fs;
    let al = w.sin() / (2.0 * q);
    biquad(
        [1.0 + al * a, -2.0 * w.cos(), 1.0 - al * a],
        [1.0 + al / a, -2.0 * w.cos(), 1.0 - al / a],
    )
}
pub fn chain(filters: &[Filter], x: &[f64]) -> Vec<f64> {
    filters.iter().fold(x.to_vec(), |y, f| f.run(&y))
}
pub fn interp(x: &[f64], pos: f64) -> f64 {
    let p = pos.clamp(0.0, (x.len() - 1) as f64);
    let i = p as usize;
    let t = p - i as f64;
    x[i] * (1.0 - t) + x[(i + 1).min(x.len() - 1)] * t
}
pub fn displace(x: &[f64], d: &[f64]) -> Vec<f64> {
    x.iter()
        .enumerate()
        .map(|(i, _)| interp(x, i as f64 - d[i]))
        .collect()
}
pub fn fm_mod(x: &[f64], sync: f64, dev: f64, fs: f64, jump: Option<(usize, f64)>) -> Vec<f64> {
    let mut phase = 0.0;
    x.iter()
        .enumerate()
        .map(|(i, v)| {
            phase += sync + (v + 0.3) * dev;
            let ph = phase * (TAU / fs) + jump.filter(|(j, _)| i >= *j).map_or(0.0, |(_, p)| p);
            ph.cos()
        })
        .collect()
}
fn fast_len(mut n: usize) -> usize {
    loop {
        let mut m = n;
        for p in [2, 3, 5, 7, 11] {
            while m % p == 0 {
                m /= p;
            }
        }
        if m == 1 {
            return n;
        }
        n += 1;
    }
}
pub fn analytic(x: &[f64]) -> Vec<C> {
    analytic_with_len(x, fast_len(x.len().max(1)))
}
/// Hilbert transform without padding, used by the deck's burst centroid calibration.
pub fn analytic_exact(x: &[f64]) -> Vec<C> {
    analytic_with_len(x, x.len())
}
// rustfft keeps planned algorithms and twiddle tables in FftPlanner.
// Retain a planner per thread rather than regenerating plans every field.
thread_local! {
    static FFT_PLANNER: RefCell<FftPlanner<f64>> = RefCell::new(FftPlanner::new());
}
fn analytic_with_len(x: &[f64], n: usize) -> Vec<C> {
    if x.is_empty() {
        return Vec::new();
    }
    let mut z = vec![C::new(0.0, 0.0); n];
    for (i, v) in x.iter().enumerate() {
        z[i].re = *v;
    }
    let (forward, inverse) = FFT_PLANNER.with(|planner| {
        let mut planner = planner.borrow_mut();
        (planner.plan_fft_forward(n), planner.plan_fft_inverse(n))
    });
    forward.process(&mut z);
    for (i, v) in z.iter_mut().enumerate().skip(1) {
        if i < (n + 1) / 2 {
            *v *= 2.0;
        } else if !(n % 2 == 0 && i == n / 2) {
            *v = C::new(0.0, 0.0);
        }
    }
    inverse.process(&mut z);
    z.truncate(x.len());
    for v in &mut z {
        *v /= n as f64;
    }
    z
}
pub fn fm_demod(x: &[f64], fs: f64) -> (Vec<f64>, Vec<f64>) {
    let z = analytic(x);
    let mut f = vec![0.0; x.len()];
    for i in 1..z.len() {
        f[i] = (z[i] * z[i - 1].conj()).arg() * fs / TAU;
    }
    if f.len() > 1 {
        f[0] = f[1];
    }
    (f, z.iter().map(|v| v.norm()).collect())
}
pub fn smooth_edges(n: usize, edge: usize) -> Vec<f64> {
    let mut w = vec![1.0; n];
    if n < 2 {
        return w;
    }
    let e = edge.max(1).min(n / 2);
    for i in 0..e {
        let v = if e == 1 {
            0.0
        } else {
            0.5 - 0.5 * (PI * i as f64 / (e - 1) as f64).cos()
        };
        w[i] = v;
        w[n - 1 - i] = v;
    }
    w
}
pub fn iir(x: &[f64], alpha: f64, matched: bool) -> Vec<f64> {
    let mut state = if matched {
        *x.first().unwrap_or(&0.0)
    } else {
        0.0
    };
    x.iter()
        .map(|v| {
            state = alpha * v + (1.0 - alpha) * state;
            state
        })
        .collect()
}
pub fn median(x: &[f64]) -> f64 {
    let mut v = x.to_vec();
    v.sort_by(f64::total_cmp);
    let n = v.len();
    if n == 0 {
        0.0
    } else if n % 2 == 0 {
        (v[n / 2] + v[n / 2 - 1]) / 2.0
    } else {
        v[n / 2]
    }
}
pub fn mean(x: &[f64]) -> f64 {
    x.iter().sum::<f64>() / x.len().max(1) as f64
}
pub fn stddev(x: &[f64]) -> f64 {
    let m = mean(x);
    (x.iter().map(|v| (v - m).powi(2)).sum::<f64>() / x.len().max(1) as f64).sqrt()
}
pub fn gaussian(x: &[f64], sigma: f64) -> Vec<f64> {
    let r = (4.0 * sigma + 0.5) as isize;
    let weights: Vec<_> = (-r..=r)
        .map(|k| (-0.5 * (k as f64 / sigma).powi(2)).exp())
        .collect();
    let sum: f64 = weights.iter().sum();
    (0..x.len())
        .map(|i| {
            weights
                .iter()
                .enumerate()
                .map(|(k, w)| {
                    let n = x.len() as isize;
                    let mut j = i as isize + k as isize - r;
                    while j < 0 || j >= n {
                        j = if j < 0 { -j - 1 } else { 2 * n - j - 1 };
                    }
                    x[j as usize] * w / sum
                })
                .sum()
        })
        .collect()
}
fn bessel0(x: f64) -> f64 {
    let mut s = 1.0;
    let mut term = 1.0;
    for k in 1..30 {
        term *= x * x / (4.0 * (k * k) as f64);
        s += term;
    }
    s
}
/// scipy resample_poly(x,2,1) default 41-tap Kaiser (beta=5) FIR.
pub fn upsample2(x: &[f64]) -> Vec<f64> {
    let mut h = Vec::new();
    for k in -20i32..=20 {
        let t = k as f64;
        let sinc = if k == 0 {
            0.5
        } else {
            (PI * t * 0.5).sin() / (PI * t)
        };
        h.push(sinc * bessel0(5.0 * (1.0 - (t / 20.0).powi(2)).sqrt()) / bessel0(5.0));
    }
    let sum: f64 = h.iter().sum();
    for v in &mut h {
        *v *= 2.0 / sum;
    }
    (0..2 * x.len())
        .map(|j| {
            let mut s = 0.0;
            for (k, w) in h.iter().enumerate() {
                let q = j as isize + k as isize - 20;
                if q >= 0 && q % 2 == 0 && (q as usize) / 2 < x.len() {
                    s += x[q as usize / 2] * w;
                }
            }
            s
        })
        .collect()
}

/// Native randomness v1: SplitMix64 uniform, Box-Muller normal, Knuth Poisson.
/// Seed tuples isolate each effect and permit exact random-access rendering.
pub struct Rng {
    state: u64,
    spare: Option<f64>,
}
impl Rng {
    pub fn new(keys: &[u64]) -> Self {
        let mut r = Self {
            state: 0x50414c5648530001,
            spare: None,
        };
        for k in keys {
            r.state ^= k.wrapping_mul(0x9e3779b97f4a7c15);
            r.next();
        }
        r
    }
    fn next(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9e3779b97f4a7c15);
        let mut z = self.state;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d049bb133111eb);
        z ^ (z >> 31)
    }
    pub fn uniform(&mut self) -> f64 {
        ((self.next() >> 11) as f64 + 0.5) / 9007199254740992.0
    }
    pub fn range(&mut self, a: f64, b: f64) -> f64 {
        a + (b - a) * self.uniform()
    }
    pub fn integer(&mut self, a: usize, b: usize) -> usize {
        a + (self.uniform() * (b.saturating_sub(a)) as f64) as usize
    }
    pub fn normal(&mut self) -> f64 {
        if let Some(v) = self.spare.take() {
            return v;
        }
        let r = (-2.0 * self.uniform().ln()).sqrt();
        let t = TAU * self.uniform();
        self.spare = Some(r * t.sin());
        r * t.cos()
    }
    pub fn normals(&mut self, n: usize, sd: f64) -> Vec<f64> {
        (0..n).map(|_| self.normal() * sd).collect()
    }
    pub fn poisson(&mut self, lambda: f64) -> usize {
        if lambda <= 0.0 {
            return 0;
        }
        if lambda > 30.0 {
            // Independent Poisson counts add exactly; splitting avoids exp underflow.
            let chunks = (lambda / 30.0) as usize;
            return (0..chunks).map(|_| self.poisson(30.0)).sum::<usize>()
                + self.poisson(lambda - chunks as f64 * 30.0);
        }
        let lim = (-lambda).exp();
        let mut p = 1.0;
        let mut k = 0;
        loop {
            p *= self.uniform();
            if p <= lim {
                return k;
            }
            k += 1;
        }
    }
    pub fn sign(&mut self) -> f64 {
        if self.uniform() < 0.5 {
            -1.0
        } else {
            1.0
        }
    }
    pub fn lognormal(&mut self, mu: f64, sd: f64) -> f64 {
        (mu + sd * self.normal()).exp()
    }
}
