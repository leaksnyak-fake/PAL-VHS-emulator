"""Bench: measure the deck on synthetic scope signals and print the numbers a real VHS is judged by.

    python -m pal_vhs.bench                       # default params
    python -m pal_vhs.bench --set tape_speed=LP tape_noise=0.05

Compare the printout with your own scope / RF capture of the machine you want to match, then tune.
Reference values used for the defaults (SP, good tape, PAL):
  FM 3.8 MHz sync -> 4.8 MHz white (1 MHz/V); colour-under 627 kHz at about -20 dB re FM; recorded luma
  spectrum from ~1.3 MHz; head Q network peaked ~4.9-5 MHz; luma -3 dB about 2.5-3 MHz (240 TVL);
  luma S/N ~33 dB unweighted (about 42-45 dB CCIR-weighted); head switch 6-8 lines before vsync;
  chroma at output = nominal relative to burst (saturation 1:1).
"""
import sys
import numpy as np
from scipy import signal
from . import consts as C, pal
from .params import Params, SPEC
from .vhs import Deck
from .dsp import run, lp, bp as _bpf

def mk(p, fi=1, frame=0, luma=None, U=None, V=None):
    """composite field with custom per-line-constant active content. luma: (922,) volts*0.7 scale (0..1)."""
    L = C.FIELD_LINES[fi]
    comp = pal.encode_field(None, fi, frame, p)
    sn, cs, sw = pal.basis(frame, fi)
    a0, a1 = C.ACTIVE_FIRST, C.ACTIVE_FIRST + C.ACTIVE_LINES
    s0, s1 = C.ACTIVE_START, C.ACTIVE_START + C.ACTIVE_LEN
    Y = np.zeros(C.ACTIVE_LEN) if luma is None else luma
    Uu = np.zeros(C.ACTIVE_LEN) if U is None else U
    Vv = np.zeros(C.ACTIVE_LEN) if V is None else V
    comp[a0:a1, s0:s1] += 0.7 * (Y + Uu*sn[a0:a1, s0:s1] + Vv*sw[a0:a1, None]*cs[a0:a1, s0:s1])
    return comp

def play(p, comp, fi=1, frame=0):
    d = Deck(p); t = {}
    out = d.process_field(comp, fi, frame, t)
    return d, out, t

def noise_off(p):
    q = p.copy()
    q.update(dict(tb_jitter_ns=0, tb_wobble_ns=0, tb_skew_us=0, hs_shift_us=0, dropout_rate=0, hs_noise=0, tape_noise=0, chroma_noise=0))
    return q

def line(x, n, a=0, b=C.SPL): return x[n*C.SPL+a:n*C.SPL+b]

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", nargs="*", default=[], metavar="key=value")
    a = ap.parse_args(argv)
    p = Params()
    for kv in a.set:
        k, v = kv.split("=", 1)
        k_ = SPEC[k]["kind"]
        p.set(k, v if k_ == "choice" else (v.lower() in ("1", "true", "yes") if k_ == "bool" else float(v)))
    _run(p)


def _run(p):
    res = {}
    # ---- 1. luma step response (clean, no noise)
    pq = noise_off(p)
    Y = np.zeros(C.ACTIVE_LEN); Y[:C.ACTIVE_LEN//2] = 0.0; Y[C.ACTIVE_LEN//2:] = 1.0   # black -> white
    Y = 0.1 + 0.8*Y
    comp = mk(pq, luma=Y)
    d, out, t = play(pq, comp)
    out_c = out
    out = t['luma_demod']
    o = out.reshape(-1, C.SPL)
    ln = o[150]; ref = comp.reshape(-1, C.SPL)[150]
    act = slice(C.ACTIVE_START, C.ACTIVE_START+C.ACTIVE_LEN)
    def risetime(x, lo_v, hi_v):
        seg = x[C.ACTIVE_START+C.ACTIVE_LEN//2-60:C.ACTIVE_START+C.ACTIVE_LEN//2+80]
        a, b = seg[:20].mean(), seg[-20:].mean()
        f = (seg-a)/(b-a)
        i10 = np.argmax(f > 0.1); i90 = np.argmax(f > 0.9)
        over = (seg.max()-b)/(b-a)*100; under = (a-seg.min())/(b-a)*100
        return (i90-i10)/C.US*1000, over, under, a, b
    rt = risetime(ln, 0.1, 0.9)
    print("STEP (VCR out) 10-90%% rise = %.0f ns, overshoot %.1f%%, preshoot %.1f%%, levels %.3f -> %.3f V" % rt)
    rt0 = risetime(ref, 0.1, 0.9)
    print("STEP (encoder in) rise = %.0f ns" % rt0[0])
    # sync + blanking after VCR
    sync_lvl = ln[20:70].mean(); blank = ln[150:182].mean()
    print("sync tip %.3f V, backporch %.3f V  (sync depth %.3f)" % (sync_lvl, blank, blank-sync_lvl))
    # sync edge rise time
    e = ln[0:120]; 
    print("sync fall time 10-90: %.0f ns" % ((np.argmax(e < blank-0.9*(blank-sync_lvl)) - np.argmax(e < blank-0.1*(blank-sync_lvl)))/C.US*1000))

    # ---- 2. luma frequency response (sine bursts at several f), clean
    print("LUMA frequency response (vs 0.5 MHz), playback composite:")
    freqs = [0.5,1,1.5,2,2.5,3,3.5,4,4.5,5]
    amps = []
    tt = np.arange(C.ACTIVE_LEN)/C.FS
    for f in freqs:
        Yb = 0.5 + 0.3*np.sin(2*np.pi*f*1e6*tt)
        c = mk(pq, luma=Yb); d, o2, tt_ = play(pq, c)
        l = tt_['luma_demod'].reshape(-1, C.SPL)[100]; seg = l[C.ACTIVE_START+200:C.ACTIVE_START+700]
        # amplitude via lock-in
        k = np.arange(200, 700)/C.FS
        z = (seg*np.exp(-2j*np.pi*f*1e6*k)).mean()*2
        amps.append(abs(z)/ (0.7*0.3))
    a0 = amps[0]
    print("  " + "  ".join("%.1f:%+.1fdB" % (f, 20*np.log10(a/a0)) for f, a in zip(freqs, amps)))

    # ---- 3. noise: flat grey field with noise on, no timebase etc.
    pn = p.copy(); pn.update(dict(tb_jitter_ns=0, tb_wobble_ns=0, tb_skew_us=0, hs_shift_us=0, dropout_rate=0, hs_noise=0, out_noise=0))
    comp = mk(pn, luma=np.full(C.ACTIVE_LEN, 0.5))
    d, out, t = play(pn, comp)
    out = t['luma_demod']
    o = out.reshape(-1, C.SPL)[40:300, C.ACTIVE_START+50:C.ACTIVE_START+870]
    # remove per-line mean slope
    sig_pp = 0.7
    n_rms = (o - o.mean(axis=1, keepdims=True)).std()
    f, P = signal.welch((o - o.mean()).ravel(), fs=C.FS, nperseg=1024)
    print("NOISE unweighted rms = %.4f V -> SNR(0.7Vpp/rms) = %.1f dB" % (n_rms, 20*np.log10(0.7/n_rms)))
    print("  noise density (rel dB) at 0.5/1/2/3/4/5 MHz:", [round(10*np.log10(P[np.argmin(abs(f-m*1e6))]/P[np.argmin(abs(f-1e6))]),1) for m in (0.5,1,2,3,4,5)])
    # chroma noise: demodulate with simple LP on a no-chroma field => look at 4.43 band energy
    cb = np.abs(np.fft.rfft((o[50]-o[50].mean())*np.hanning(o.shape[1])))
    # ---- 4. RF spectrum
    tape = t['tape']
    fT, PT = signal.welch(tape, fs=2*C.FS, nperseg=8192)
    db = 10*np.log10(PT+1e-20)
    def band(a,b): m=(fT>=a*1e6)&(fT<=b*1e6); return 10*np.log10(PT[m].sum()*(fT[1]-fT[0]))
    print("RF band power (dB, rel FM 3.2-5.6): colour-under 0.4-0.9: %.1f, FM main: %.1f, 1.3-3.2: %.1f, 5.6-8: %.1f" % (band(0.4,0.9)-band(3.2,5.6), 0, band(1.3,3.2)-band(3.2,5.6), band(5.6,8)-band(3.2,5.6)))
    print("tape rms %.3f" % tape.std())

    # ---- 5. colour bars: chroma level at output, burst amplitude, chroma lag vs luma
    Ub = np.zeros(C.ACTIVE_LEN); Vb = np.zeros(C.ACTIVE_LEN)
    Yb = np.full(C.ACTIVE_LEN, 0.5)
    # yellow-ish saturated chroma patch in the middle with a luma step at same place
    mid = C.ACTIVE_LEN//2
    Ub[mid-200:mid+200] = 0.3; Vb[mid-200:mid+200] = 0.2
    c = mk(pq, luma=Yb, U=Ub, V=Vb)
    d, o3, tt3 = play(pq, c)
    ol = o3.reshape(-1, C.SPL)
    cfl = signal.sosfiltfilt(_bpf(C.FSC-0.8e6, C.FSC+0.8e6, 2), o3)
    burst = cfl.reshape(-1, C.SPL)[150, C.BURST_START+8:C.BURST_START+C.BURST_LEN-8]
    print("burst pp at VCR out (band-passed): %.3f V (nominal 0.300)" % (burst.max()-burst.min()))
    cin = c.reshape(-1,C.SPL)[150]; print("burst pp at enc: %.3f" % (cin[C.BURST_START:C.BURST_START+C.BURST_LEN].max()-cin[C.BURST_START:C.BURST_START+C.BURST_LEN].min()))
    chroma_patch_in = np.abs(0.7*np.hypot(0.3,0.2))
    cseg = ol[150, C.ACTIVE_START+mid-100:C.ACTIVE_START+mid+100]
    print("chroma amp out ~ %.3f (in %.3f) ; rel to burst-in: %.2f" % ((cseg.max()-cseg.min())/2, chroma_patch_in, ((cseg.max()-cseg.min())/2)/chroma_patch_in))
    # cu vs FM ratio
    cu = tt3['c_under'] * d.cu_gain; fm_amp = 1.0
    print("colour-under peak in saturated patch: %.3f vs FM carrier 1.0 -> %.1f dB" % (np.abs(cu.reshape(-1,C.SPL)[150, C.ACTIVE_START+mid-100:C.ACTIVE_START+mid+100]).max(), 20*np.log10(np.abs(cu.reshape(-1,C.SPL)[150, C.ACTIVE_START+mid-100:C.ACTIVE_START+mid+100]).max())))
    print("burst colour-under amp: %.3f -> %.1f dB re FM" % (np.abs(cu.reshape(-1,C.SPL)[150, C.BURST_START:C.BURST_START+C.BURST_LEN]).max(), 20*np.log10(np.abs(cu.reshape(-1,C.SPL)[150, C.BURST_START:C.BURST_START+C.BURST_LEN]).max())))
    # chroma edge response: lock-in demod of output around patch edge
    t_ = np.arange(C.SPL)
    sn, cs, sw = pal.basis(0, 1)
    x = ol[150]
    U_o = signal.sosfiltfilt(lp(0.5e6, 4), x*2*sn[150])
    edge_i = C.ACTIVE_START+mid-200
    seg = U_o[edge_i-150:edge_i+150]
    a, b = seg[:20].mean(), seg[-20:].mean()
    print("chroma edge 10-90 (demod LP 0.5MHz measuring itself, so approx): %.0f ns, 50%% pt lag vs luma-edge ideal: %.0f ns" % ((np.argmax((seg-a)/(b-a)>0.9)-np.argmax((seg-a)/(b-a)>0.1))/C.US*1000, (np.argmax((seg-a)/(b-a)>0.5)-150)/C.US*1000))


if __name__ == "__main__":
    main()
