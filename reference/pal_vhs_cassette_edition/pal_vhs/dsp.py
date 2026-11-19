"""Small DSP toolbox: causal analog-style filters (Butterworth / shelves), FM modulator and
demodulator, and the time-displacement operator that models time-base errors."""
from __future__ import annotations
import numpy as np
from scipy import signal, fft as sfft
from .consts import FS


def lp(fc_hz, order=3, fs=FS):
    return signal.butter(order, min(fc_hz / (fs / 2), 0.98), "low", output="sos")


def hp(fc_hz, order=2, fs=FS):
    return signal.butter(order, fc_hz / (fs / 2), "high", output="sos")


def bp(f1_hz, f2_hz, order=2, fs=FS):
    nyq = fs / 2
    return signal.butter(order, [f1_hz / nyq, min(f2_hz / nyq, 0.98)], "band", output="sos")


def notch(f0_hz, q=3.0, fs=FS):
    b, a = signal.iirnotch(f0_hz / (fs / 2), q)
    return signal.tf2sos(b, a)


def shelf(fz_hz, gain_db, fs=FS, inverse=False):
    """First-order emphasis shelf: H(s) = (1 + s/wz) / (1 + s/wp), HF gain = gain_db."""
    g = 10 ** (gain_db / 20.0)
    wz = 2 * np.pi * fz_hz
    wp = wz * g
    num, den = [1 / wz, 1.0], [1 / wp, 1.0]
    if inverse:
        num, den = den, num
    b, a = signal.bilinear(num, den, fs)
    return signal.tf2sos(b, a)


def peak(f0_hz, gain_db, q=1.2, fs=FS):
    """RBJ peaking EQ biquad (head/preamp resonance). gain_db = boost at f0."""
    if abs(gain_db) < 1e-6:
        return None
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0_hz / fs
    al = np.sin(w0) / (2 * q)
    b = [1 + al * A, -2 * np.cos(w0), 1 - al * A]
    a = [1 + al / A, -2 * np.cos(w0), 1 - al / A]
    return signal.tf2sos(b, a)


def run(sos, x):
    """Causal filter with the initial state matched to the first sample (no start-up thump)."""
    if sos is None:
        return x
    zi = signal.sosfilt_zi(sos) * x[0]
    return signal.sosfilt(sos, x, zi=zi)[0]


def run_chain(sos_list, x):
    for s in sos_list:
        x = run(s, x)
    return x


def delay_samples(x, n):
    """Integer delay (positive = later) with edge replication."""
    n = int(round(n))
    if n == 0:
        return x
    if n > 0:
        return np.concatenate([np.full(n, x[0]), x[:-n]])
    return np.concatenate([x[-n:], np.full(-n, x[-1])])


def displace(x, d):
    """out[i] = x(i - d[i]); d in samples (positive = delayed). Linear interpolation."""
    n = len(x)
    idx = np.arange(n, dtype=np.float64) - d
    return np.interp(idx, np.arange(n), x)


def fm_mod(v, f_sync, dev_per_v, fs, phase_start=None, phase_jump=0.0):
    """v: volts (sync tip = -0.3). Returns unit-amplitude FM carrier."""
    f = f_sync + (v + 0.3) * dev_per_v
    ph = np.cumsum(f) * (2 * np.pi / fs)
    if phase_start is not None and phase_jump:
        ph[max(0,int(round(phase_start))):] += phase_jump
    return np.cos(ph)


def analytic(x):
    n = len(x)
    nf = sfft.next_fast_len(n)
    z = signal.hilbert(np.asarray(x, np.float64), N=nf)      # f64 preserves RF phase-difference precision
    return z[:n]


def fm_demod(s, fs):
    """Ideal limiter + phase-difference discriminator. Returns (inst. frequency Hz, envelope)."""
    z = analytic(s)
    d = z[1:] * np.conj(z[:-1])
    f = np.empty(len(s))
    f[1:] = np.angle(d) * (fs / (2 * np.pi))
    f[0] = f[1]
    return f, np.abs(z)


def smooth_edges(mask_len, edge):
    """Raised-cosine window of length mask_len with `edge` samples ramps."""
    w = np.ones(mask_len)
    e = max(1, min(edge, mask_len // 2))
    r = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, e))
    w[:e] = r
    w[-e:] = r[::-1]
    return w
