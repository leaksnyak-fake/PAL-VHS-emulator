"""PAL head change geometry and partial playback profiles; not named-deck calibrations."""
import numpy as np
from scipy import signal
from . import consts as C


def switch_line(p, lines, fi, frame_idx):
    if p.hs_model == 'legacy overlay':
        return float(lines-p.hs_lines)
    excursion = p.hs_servo_lines*np.sin(2*np.pi*.73*(frame_idx/25+fi*.02))
    # Existing line grid: next broad vertical-sync pulse begins at next field +2.
    # This remains a whole-line approximation, not true half-line PAL timing.
    return float(lines+2-p.hs_advance+excursion)


def pal_colour_rotation(lines, fi, model='PAL VHS'):
    n = np.arange(lines)
    if model == 'legacy 90deg':
        return (n % 4)*(np.pi/2)
    # High-side conversion: CU phase = LO phase - input phase.
    return -(n % 4)*(np.pi/2) if fi == 1 else np.zeros(lines)


def rf_switch_envelope(p, lines, fi, frame_idx, oversample):
    size = lines*C.SPL*oversample
    env = np.ones(size)
    if p.hs_model != 'RF switch' or p.hs_noise <= 0:
        return env
    start = switch_line(p,lines,fi,frame_idx)*C.SPL*oversample
    us = (np.arange(size)-start)/(C.US*oversample)
    hit = us >= 0
    t = us[hit]
    loss = np.clip(t/.15,0,1)*np.exp(-np.maximum(t-p.hs_gap_us,0)/p.hs_recovery_us)
    env[hit] = 1-min(p.hs_noise,.999)*loss
    return env


def add_switch_snow(yv, p, fi, frame_idx):
    """Original-style snow on the played-back luma waveform, before TV decode.

    The original attack/decay, correlated grain, length breathing and line fade
    are retained. Existing pixel controls set a nominal time scale/position, not
    a hard RGB rectangle: TV/output filters produce the visible soft tail.
    """
    if p.hs_residual <= 0 or p.bypass_tape or p.hs_model != 'RF switch':
        return yv
    L = len(yv)//C.SPL
    last = min(C.ACTIVE_LINES-1,(C.FRAME_H-1-p.hs_residual_bottom_px-fi)//2)
    first = max(0,last-p.hs_residual_height+1)
    if p.hs_mask_lines > 0:
        last = min(last,C.ACTIVE_LINES-p.hs_mask_lines-1)
    if last < first:
        return yv
    rng = np.random.default_rng([p.seed,frame_idx,fi,71])
    out = yv.reshape(L,C.SPL).copy()
    starts = residual_positions(p,C.FRAME_W,fi,frame_idx,last-first+1,quantize=False)
    for k,x in enumerate(starts):
        g = 1-.7*k/max(len(starts)-1,1)
        x_float = C.ACTIVE_START+x*C.ACTIVE_LEN/C.FRAME_W
        x0 = int(np.floor(x_float))
        length = p.hs_residual_width_px*C.ACTIVE_LEN/C.FRAME_W*rng.uniform(.7,1.3)*(1-.15*k)
        n = min(max(8,int(np.ceil(length))),C.ACTIVE_START+C.ACTIVE_LEN-x0)
        if n < 2:
            continue
        t = np.arange(n,dtype=float)-(x_float-x0)
        t_positive = np.maximum(t,0)
        head = np.exp(-t_positive/(.45*length))*np.minimum(1,t_positive/(.3*C.US+1))
        head[t < 0] = 0
        grain = .6+.4*signal.lfilter([.35],[1,-.65],rng.normal(0,1,n))/.55
        li = C.ACTIVE_FIRST+first+k
        out[li,x0:x0+n] += p.hs_residual*g*1.7*head*np.clip(grain,0,1.7)*rng.uniform(.8,1)
    return out.reshape(-1)


def residual_positions(p, width, fi, frame_idx, lines, quantize=True):
    """Per-line starts, reflected at both edges, with a separate position RNG."""
    span = max(0,width-min(width,p.hs_residual_width_px))
    if span == 0:
        return [0]*lines
    pos = p.hs_residual_x*span
    if p.hs_residual_motion in ('Drift','Drift + jitter'):
        pos += (2*frame_idx+fi)*p.hs_residual_speed_px
    if p.hs_residual_motion in ('Random jumps','Drift + jitter'):
        rng = np.random.default_rng([p.seed,frame_idx,fi,174])
        pos += rng.normal(0,p.hs_residual_jitter_px)
        line_jit = rng.normal(0,.35*p.hs_residual_jitter_px,lines)       # smaller independent jitter per snow line
    else:
        line_jit = np.zeros(lines)
    starts=[]
    for k in range(lines):
        x = (pos+k*p.hs_residual_sweep_px+line_jit[k]) % (2*span)
        position = x if x <= span else 2*span-x
        starts.append(int(np.floor(position+.5)) if quantize else position)
    return starts


DECK_BASE = dict(hs_model='RF switch', hs_advance=6.5, hs_jitter_us=0,
                 hs_shift_var=0, hs_random=False, hs_snow=0,
                 hs_snow_jitter=0, hs_servo_lines=0, hs_mask_lines=0,
                 cu_phase_model='PAL VHS', hs_residual=0,
                 hs_residual_width_px=9, hs_residual_height=1,
                 hs_residual_bottom_px=5, hs_residual_x=.12,
                 hs_residual_motion='Drift + jitter', hs_residual_speed_px=12,
                 hs_residual_jitter_px=10, hs_residual_sweep_px=3)

DECK_PROFILES = {
    'Budget 2-head / rough alignment': (
        'Budget playback with rough alignment: earlier switching, a short RF interruption, stable bottom displacement and a 15-pixel residual. Two heads alone do not cause these defects.',
        dict(hs_advance=8,hs_noise=.8,hs_gap_us=1.0,hs_recovery_us=.3,
             hs_phase_deg=40,hs_shift_us=4,tv_afc=.25,doc=False,
             hs_residual=.9,hs_residual_width_px=15,hs_residual_height=2)),
    'Domestic 2-head / aligned': (
        'Aligned SP playback: nominal 6.5 H switching, brief carrier loss and a small stable bottom offset.',
        dict(hs_noise=.65,hs_gap_us=5,hs_recovery_us=5,
             hs_phase_deg=50,hs_shift_us=1,tv_afc=.35,doc=True,
             hs_residual=.7,hs_residual_width_px=12,hs_residual_height=2)),
    'Domestic 4-head / aligned': (
        'A well-adjusted consumer deck with a smaller modeled head mismatch. Four heads do not guarantee better SP switching than two.',
        dict(hs_noise=.4,hs_gap_us=2.5,hs_recovery_us=3,
             hs_phase_deg=30,hs_shift_us=.5,tv_afc=.5,doc=True,
             hs_residual=.6,hs_residual_width_px=10)),
    'High-end 6+ head S-VHS deck / VHS playback': (
        'Standard VHS tape on an S-VHS-capable deck with idealized horizontal correction. Extra heads may be for audio or erase; this does not change the tape to S-VHS.',
        dict(hs_noise=.18,hs_gap_us=.8,hs_recovery_us=1.2,
             hs_phase_deg=12,hs_shift_us=.15,tv_afc=1,doc=True,
             hs_residual=.45,hs_residual_width_px=9)),
    'Professional / narrow residual (user reference)': (
        'Original-style soft waveform streak: nominal 9-pixel width, 1 line per field, five woven-frame rows above the bottom. Correlated grain, a bright head and fading tail; horizontal motion with zero image-line jitter. Not a measured universal VCR specification.',
        dict(hs_noise=.18,hs_gap_us=.8,hs_recovery_us=1.2,
             hs_phase_deg=12,hs_shift_us=.15,tv_afc=1,doc=True,
             hs_residual=.6,hs_residual_width_px=9,hs_residual_height=1)),
    'Professional / later switch (+1.5 H)': (
        'Atlas-inspired later switching: 1.5 H later than this model nominal. Less disturbance enters active video. Generic PAL approximation, not a named JVC or NTSC capture calibration.',
        dict(hs_advance=5,hs_noise=.12,hs_gap_us=.4,hs_recovery_us=.8,
             hs_phase_deg=8,hs_shift_us=.1,tv_afc=1,doc=True)),
    'Professional / SWP black mask': (
        'Output black mask on the last four active field lines. Hides picture detail while RF switching still occurs; separate from TBC and later switching.',
        dict(hs_noise=.18,hs_gap_us=.8,hs_recovery_us=1.2,
             hs_phase_deg=12,hs_shift_us=.15,hs_mask_lines=4,tv_afc=1,doc=True)),
    'Fault demonstration / recorded servo error': (
        'Explicit recorded-servo fault: vertical movement of the switching boundary. Not normal cheap-deck behaviour. Horizontal head-switch line jitter remains zero.',
        dict(hs_servo_lines=35,hs_noise=.98,hs_gap_us=35,hs_recovery_us=20,
             hs_phase_deg=120,hs_shift_us=4,tv_afc=.25,doc=False)),
}


def apply_deck_profile(params,name):
    """Update playback only; preserve recording format and tape damage."""
    return params.update(DECK_BASE).update(DECK_PROFILES[name][1])
