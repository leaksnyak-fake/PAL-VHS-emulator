"""PAL composite encoder and a CRT-TV style decoder.

Encoder : RGB field -> Y/U/V -> band limit -> composite (sync, blanking, swinging burst,
          quadrature-modulated subcarrier with the PAL V-switch), 313/312 lines per field.
Decoder : sync slicer + AFC (horizontal lock), DC clamp / AGC, chroma trap, burst-locked
          quadrature demodulator, PAL-D delay-line averaging, YUV -> RGB.
"""
from __future__ import annotations
import numpy as np
import cv2
from scipy import signal
from . import consts as C
from .dsp import lp, bp, notch, run, run_chain, smooth_edges

TWO_PI = 2 * np.pi
_BASIS = {}


def basis(frame_idx, fi):
    """sin/cos of the subcarrier for every sample of a field + PAL V-switch sign per line.
    The pattern repeats every 4 frames (8 fields) like real PAL."""
    key = (frame_idx % 4, fi)
    b = _BASIS.get(key)
    if b is None:
        L = C.FIELD_LINES[fi]
        g0 = (frame_idx % 4) * C.LINES_FRAME + (0 if fi == 0 else C.FIELD_LINES[0])
        lines = g0 + np.arange(L)
        n = np.arange(C.SPL)
        cyc = (C.CPL * lines[:, None] + C.CPL * n[None, :] / C.SPL) % 1.0
        ph = TWO_PI * cyc
        sw = np.where(lines % 2 == 0, 1.0, -1.0)
        b = (np.sin(ph), np.cos(ph), sw)
        _BASIS[key] = b
    return b


def _smooth(x, sigma=1.4, pad=64):
    r = int(4 * sigma) + 1
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    xp = np.concatenate([np.zeros(pad), x, np.zeros(pad)])
    return np.convolve(xp, k, mode="same")[pad:pad + len(x)]


def _templates():
    def pulses(spans):
        a = np.zeros(C.SPL)
        for s, w in spans:
            a[s:s + w] = 1
        return a
    half = C.SPL // 2
    shapes = (pulses([(0, C.SYNC_W)]),
              pulses([(0, C.EQ_W), (half, C.EQ_W)]),
              pulses([(0, C.BROAD_W), (half, C.BROAD_W)]))
    return [C.SYNC_LEVEL * _smooth(s) for s in shapes]


_TPL = _templates()
_BURST_ENV = smooth_edges(C.BURST_LEN, 6)


def line_types(L):
    t = np.zeros(L, int)
    t[0:2] = 1
    t[2:5] = 2
    t[5:7] = 1
    return t


def prepare_rgb(rgb, p):
    x = (rgb - 0.5) * p.in_contrast + 0.5 + p.in_brightness
    return np.clip(x, 0.0, 1.0)


def encode_field(rgb, fi, frame_idx, p):
    """rgb: (288,720,3) float 0..1 or None (blank). Returns composite (L, SPL) in volts."""
    L = C.FIELD_LINES[fi]
    sn, cs, sw = basis(frame_idx, fi)
    comp = np.zeros((L, C.SPL))
    types = line_types(L)
    for ti in range(3):
        comp[types == ti] += _TPL[ti]
    b0, b1 = C.BURST_START, C.BURST_START + C.BURST_LEN
    comp[7:, b0:b1] += (C.BURST_AMP * _BURST_ENV[None, :] *
                        (-sn[7:, b0:b1] + sw[7:, None] * cs[7:, b0:b1]))
    if rgb is not None:
        rgb = prepare_rgb(rgb, p)
        R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        Y = 0.299 * R + 0.587 * G + 0.114 * B
        U = 0.493 * (B - Y) * p.in_saturation
        V = 0.877 * (R - Y) * p.in_saturation
        st = np.stack([Y, U, V], -1).astype(np.float32)
        st = cv2.resize(st, (C.ACTIVE_LEN, C.ACTIVE_LINES), interpolation=cv2.INTER_CUBIC)
        Y2, U2, V2 = (st[..., 0].astype(np.float64), st[..., 1].astype(np.float64),
                      st[..., 2].astype(np.float64))
        Y2 = signal.sosfiltfilt(lp(p.enc_luma_bw * 1e6, 4), Y2, axis=1)
        U2 = signal.sosfiltfilt(lp(p.enc_chroma_bw * 1e6, 4), U2, axis=1)
        V2 = signal.sosfiltfilt(lp(p.enc_chroma_bw * 1e6, 4), V2, axis=1)
        a0, a1 = C.ACTIVE_FIRST, C.ACTIVE_FIRST + C.ACTIVE_LINES
        s0, s1 = C.ACTIVE_START, C.ACTIVE_START + C.ACTIVE_LEN
        comp[a0:a1, s0:s1] += 0.7 * (Y2 + U2 * sn[a0:a1, s0:s1] +
                                     V2 * sw[a0:a1, None] * cs[a0:a1, s0:s1])
    return comp


# ------------------------------------------------------------------ decoder
_DET_LP = lp(1.2e6, 2)
_WIN_PRE, _WIN_LEN = 240, 760     # sync search window: -13.5 us .. +23 us around the nominal edge


def _detect_edges(comp, L):
    """Sync-leading-edge positions (float, stream samples) for field lines 8..L-1.
    Adaptive slicer: threshold half way between blanking level and sync tip."""
    d = run(_DET_LP, comp)
    N = len(d)
    n = np.arange(8, L)
    pos = (n * C.SPL - _WIN_PRE)[:, None] + np.arange(_WIN_LEN)[None, :]
    W = d[pos]
    blank0 = np.median(W[:, _WIN_PRE + 150:_WIN_PRE + 182].mean(axis=1))
    tip_amp = np.median(blank0 - W.min(axis=1))
    thr = blank0 - 0.5 * tip_amp
    below = W < thr
    k = below.argmax(axis=1)
    ok = below.any(axis=1) & (k > 0)
    k = np.maximum(k, 1)
    r = np.arange(len(n))
    a, b = W[r, k - 1], W[r, k]
    with np.errstate(divide="ignore", invalid="ignore"):
        frac = np.where(np.abs(a - b) > 1e-9, (a - thr) / (a - b), 0.0)
    edge = n * C.SPL - _WIN_PRE + (k - 1) + np.clip(frac, 0, 1)
    edge = np.where(ok, edge, np.nan)
    # per-line blanking (back-porch) level measured at the *found* edge -> DC clamp follows shifts
    e = np.where(np.isnan(edge), n * C.SPL, edge)
    bi = np.clip(np.rint(e[:, None] + 150 + np.arange(32)[None, :]).astype(int), 0, N - 1)
    blank = d[bi].mean(axis=1)
    return n, edge, blank, tip_amp


def _calibrate_c0():
    """Constant offset of the slicer on an ideal signal (filter delay) so ideal -> 0."""
    from .params import Params
    L = C.FIELD_LINES[1]
    comp = encode_field(None, 1, 0, Params())
    n, edge, _, _ = _detect_edges(comp.reshape(-1), L)
    return float(np.nanmean(edge - n * C.SPL))


_C0 = None


def _gd(sos, f_hz):
    b, a = signal.sos2tf(sos)
    _, g = signal.group_delay((b, a), w=[TWO_PI * f_hz / C.FS])
    return float(g[0])


def _ffill(x, default):
    x = x.copy()
    last = default
    for i in range(len(x)):
        if np.isnan(x[i]):
            x[i] = last
        else:
            last = x[i]
    return x


def _iir(x, alpha):
    zi = [(1 - alpha) * x[0]]
    return signal.lfilter([alpha], [1, -(1 - alpha)], x, zi=zi)[0]


def decode_field(stream, fi, frame_idx, p):
    """stream: composite field (L*SPL,) -> RGB float32 (288, 720, 3) in 0..1."""
    global _C0
    if _C0 is None:
        _C0 = _calibrate_c0()
    L = C.FIELD_LINES[fi]
    sn, cs, sw = basis(frame_idx, fi)
    stream = np.asarray(stream, dtype=np.float64)
    N = len(stream)

    # ---- horizontal sync: slicer + AFC
    n, edge, blank, tip_amp = _detect_edges(stream, L)
    dev = _ffill(edge - n * C.SPL - _C0, 0.0)
    afc = signal.lfilter([p.tv_afc], [1, -(1 - p.tv_afc)], dev)   # where the TV scans from (free-running start)
    agc = 0.3 / max(tip_amp, 0.05)                  # luma AGC from sync depth

    # ---- luma path (chroma trap + bandwidth)
    ysos = [lp(p.tv_luma_bw * 1e6, 3), notch(C.FSC, 2.5)]
    Ys = run_chain(ysos, stream)
    dly_y = sum(_gd(s, 0.5e6) for s in ysos)

    # ---- chroma path: band-pass, quadrature demod, chroma low-pass
    cb = bp(C.FSC - 1.4e6, C.FSC + 1.4e6, 2)
    cl = lp(p.tv_chroma_bw * 1e6, 3)
    flat_s, flat_c = sn.reshape(-1), cs.reshape(-1)
    Cb = run(cb, stream)
    Us = run(cl, Cb * 2 * flat_s)                   # = U cos e - sV sin e
    Vs = run(cl, Cb * 2 * flat_c)                   # = U sin e + sV cos e
    dly_c = _gd(cb, C.FSC) + _gd(cl, 0.05e6)

    grid = np.arange(N, dtype=np.float64)
    # ---- burst measurement (per line)
    bk = np.arange(6, C.BURST_LEN - 6)
    bpos = (n * C.SPL + afc)[:, None] + C.BURST_START + bk[None, :] + dly_c
    bx = np.interp(bpos.ravel(), grid, Us).reshape(bpos.shape).mean(axis=1)
    by = np.interp(bpos.ravel(), grid, Vs).reshape(bpos.shape).mean(axis=1)
    z = bx + 1j * by
    s_est = np.where(by > 0, 1.0, -1.0)
    s0 = 1.0 if np.sum(s_est * (-1.0) ** n) >= 0 else -1.0
    s_line = s0 * (-1.0) ** n
    ref = np.where(s_line > 0, np.deg2rad(135.0), np.deg2rad(225.0))
    eps = np.unwrap(np.angle(z * np.exp(-1j * ref)))
    A = np.abs(z) / np.sqrt(2)
    eps_s = _iir(eps, p.tv_apc)
    A_s = _iir(A, p.tv_apc)
    gain_c = np.clip(C.BURST_AMP / np.maximum(A_s, 1e-4), 0.3, 3.0)
    # per-line colour killer: burst below ~40 % of nominal -> that line is decoded without colour
    gain_c = gain_c * np.clip((A_s / C.BURST_AMP - 0.25) / 0.2, 0.0, 1.0)
    kill = np.median(A) < 0.03                      # colour killer (whole field)

    # ---- picture sampling positions (active lines)
    a0 = C.ACTIVE_FIRST - 8
    sl = slice(a0, a0 + C.ACTIVE_LINES)
    k = np.arange(C.ACTIVE_LEN)
    base = (n[sl] * C.SPL + afc[sl])[:, None] + C.ACTIVE_START + k[None, :]
    shp = base.shape
    Y = np.interp((base + dly_y).ravel(), grid, Ys).reshape(shp)
    Up = np.interp((base + dly_c).ravel(), grid, Us).reshape(shp)
    Vp = np.interp((base + dly_c).ravel(), grid, Vs).reshape(shp)

    bl = blank[sl][:, None]
    Y = (Y - bl) * agc / 0.7

    e = eps_s[sl][:, None]
    g = gain_c[sl][:, None] / 0.7
    U = (Up * np.cos(e) + Vp * np.sin(e)) * g
    sV = (-Up * np.sin(e) + Vp * np.cos(e)) * g
    V = sV * s_line[sl][:, None]
    if kill:
        U = V = np.zeros_like(U)
    if p.tv_decoder == "PAL-D":                     # delay-line: average with previous line
        Up_, Vp_ = np.roll(U, 1, axis=0), np.roll(V, 1, axis=0)
        # previous (blanking) line for the first picture line: reuse the same line
        Up_[0], Vp_[0] = U[0], V[0]
        U, V = 0.5 * (U + Up_), 0.5 * (V + Vp_)
    h = np.deg2rad(p.tv_hue)
    U, V = (U * np.cos(h) - V * np.sin(h)) * p.tv_saturation, \
           (U * np.sin(h) + V * np.cos(h)) * p.tv_saturation

    R = Y + 1.140 * V
    G = Y - 0.395 * U - 0.581 * V
    B = Y + 2.032 * U
    rgb = np.stack([R, G, B], -1).astype(np.float32)
    rgb = (rgb - 0.5) * p.tv_contrast + 0.5 + p.tv_brightness
    rgb = cv2.resize(rgb, (C.FRAME_W, C.ACTIVE_LINES), interpolation=cv2.INTER_AREA)
    return np.clip(rgb, 0.0, 1.0)


def weave(f1, f2):
    """Two (288,720,3) fields -> interlaced (576,720,3) frame, top field first."""
    out = np.empty((C.FRAME_H, C.FRAME_W, 3), dtype=f1.dtype)
    out[0::2] = f1
    out[1::2] = f2
    return out
