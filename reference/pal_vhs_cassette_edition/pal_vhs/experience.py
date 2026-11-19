"""Non-Qt easy controls, documented presets, and parameter help.

Easy controls edit only their own parameter families. Switching modes never resets
parameters. Values are physical-model approximations, not named-deck calibrations.
"""
from .params import Params, PRESETS, SPEC
from .headswitch import DECK_PROFILES, apply_deck_profile

REFERENCE = dict(tape_speed="SP", rf_rate="2x", fm_sync_mhz=3.8,
                 fm_dev_mhz=1.0, cu_level_db=-20.0, rec_luma_bw=3.4,
                 play_luma_bw=3.6, chroma_delay_ns=0, tape_noise=0.025,
                 chroma_noise=0.008, tb_jitter_ns=15, tb_wobble_ns=40,
                 tb_skew_us=0.2, hs_shift_us=1.0, hs_jitter_us=0.0,
                 hs_model="RF switch", hs_shift_var=0, hs_snow_jitter=0,
                 hs_snow=0, hs_noise=0.2, dropout_rate=0.5,
                 track_band=0, tracking=0, wrinkle=0, wr_travel=False)

CURATED = {
    "PAL VHS / SP - fresh cassette": (
        "Everyday / model-based", "Restrained SP recording: soft colour detail, fine RF noise, occasional dropout. No deliberate tape damage.", {}),
    "PAL VHS / SP - home recording": (
        "Everyday / model-based", "Used SP cassette with mild line movement and colour lag. A plausible home recording, not a measured camera profile.",
        dict(tape_noise=0.035, chroma_noise=0.014, chroma_delay_ns=100, tb_jitter_ns=30,
             tb_wobble_ns=100, tb_skew_us=0.5, dropout_rate=1.5, tape_wear=0.05)),
    "PAL VHS / LP - long play": (
        "Everyday / model-based", "LP uses the existing speed model: reduced bandwidth and increased noise. Adds modest wear, without tracking failure.",
        dict(tape_speed="LP", tape_noise=0.04, chroma_noise=0.018, chroma_delay_ns=140,
             tb_jitter_ns=40, tb_wobble_ns=150, dropout_rate=2, tape_wear=0.08)),
    "PAL VHS / SP - worn rental": (
        "Damaged / illustrative", "Worn cassette with RF loss, short streaks and occasional creases. Damage amounts are artistic estimates.",
        dict(tape_noise=0.05, tape_wear=0.22, dropout_rate=5, snow_sparse=0.4,
             chroma_noise=0.024, tb_jitter_ns=65, tb_wobble_ns=220,
             wrinkle=0.2, wrinkle_height=10, wrinkle_speed_pct=5, wrinkle_shift_us=2)),
    "PAL VHS / SP - tracking failure": (
        "Damaged / illustrative", "Misadjusted tracking with a travelling smear band. Use the signed tracking slider to move noise toward the top or bottom.",
        dict(tracking=-0.4, track_band=0.4, track_smear=0.65, tape_wear=0.15)),
    "PAL VHS / SP - creased cassette": (
        "Damaged / illustrative", "Local speed error and repeated scan lines plus travelling white crease bands. This is damaged tape, not normal VHS texture.",
        dict(wrinkle=0.5, wrinkle_height=20, wrinkle_speed_pct=10,
             wrinkle_shift_us=4, wr_travel=True, wr_white=0.5, wr_period=100)),
    "PAL VHS / SP - blank tape damage (reference)": (
        "Damaged / illustrative", "Approximation of SP tape damage on a blank blue tape (1nicboy comparison video): grey-to-black fading crease band moving down, soft colour banding, occasional colour-lock loss and a tracking noise band. Matched by eye on a flat blue picture.",
        dict(wr_travel=True, wr_style="grey fade", wr_period=400, wr_hmin=14, wr_hmax=16, wr_speed=2.2, wr_accel=0.8,
             wr_wobble=1.2, wr_rise=25, wr_shrink=0.8, wr_soft=0.6, wr_sat=0.6,
             wr_flicker=0.0, wr_chroma_loss=1.0, wr_ragged=0.3, wr_grey=0.45, track_accel=0.5, track_wobble=1.0,
             chroma_band=0.6, cu_glitch=1.0, cu_glitch_period=300, cu_glitch_len=20,
             track_band=0.5, track_speed=2.7, track_smear=0.2, tape_wear=0.1)),
    "PAL VHS / SP - stable playback": (
        "Everyday / idealized correction", "Clean SP with idealized horizontal correction. Retains VHS bandwidth and colour-under; does not simulate a particular hardware TBC.",
        dict(tv_afc=1, tb_jitter_ns=5, tb_wobble_ns=0, tb_skew_us=0,
             hs_shift_us=0, hs_jitter_us=0, hs_snow=0, hs_noise=0, hs_phase_deg=0)),
}

PRESET_INFO = {}
for values in PRESETS.values():
    values.update(hs_jitter_us=0,hs_shift_var=0,hs_snow_jitter=0,hs_model="legacy overlay")
for name,(description,offsets) in DECK_PROFILES.items():
    p = apply_deck_profile(Params().update(REFERENCE),name)
    CURATED["Deck / "+name] = ("Playback deck / informed approximation",description,p.to_dict())
for name, (category, description, offsets) in CURATED.items():
    PRESETS[name] = dict(REFERENCE)
    PRESETS[name].update(offsets)
    PRESET_INFO[name] = (category, description)


# Maps a 0..100 experience control to named signal parameters. Endpoint zero
# removes that family of damage, not the basic VHS bandwidth/colour-under model.
MACROS = {
    "wear": ("Tape wear", "Fresh cassette → worn tape: RF loss, fine noise and more dropouts.",
             {"tape_wear": (0, .4), "tape_noise": (.02, .08), "dropout_rate": (0, 8), "chroma_noise": (.006, .035)}),
    "colour": ("Colour bleed", "Aligned colour → soft colour spilling to the right of bright edges.",
               {"chroma_delay_ns": (0, 650), "chroma_play_bw": (.65, .25)}),
    "unstable": ("Picture wobble", "Steady picture → shaky vertical edges and top flagging. TV horizontal lock can hide some movement.",
                 {"tb_jitter_ns": (0, 140), "tb_wobble_ns": (0, 650), "tb_skew_us": (0, 5)}),
    "smear": ("Tracking smears", "Adds a moving mistracking band with stretched/repeated lines and colour loss.",
              {"track_band": (0, .8), "track_smear": (0, 1)}),
    "crease": ("Tape creases", "Adds local tape speed errors, duplicated lines and horizontal tears.",
               {"wrinkle": (0, .85), "wrinkle_height": (4, 40)}),
}


def set_macro(params, name, amount):
    t = max(0, min(100, amount)) / 100
    for key, (a, b) in MACROS[name][2].items():
        params.set(key, a + (b - a) * t)


def macro_position(params, name):
    key, (a, b) = next(iter(MACROS[name][2].items()))
    return round(max(0, min(1, (getattr(params, key) - a) / (b - a))) * 100)


HELP = {
    "in_brightness": "Adds brightness before PAL encoding; high values can clip highlights during recording.",
    "in_contrast": "Scales contrast before recording; high contrast can overload the tape's recording range.",
    "in_saturation": "Scales colour before recording; 0 records a monochrome source.",
    "enc_luma_bw": "Encoder brightness bandwidth. Lower MHz softens detail before the tape stage.",
    "enc_chroma_bw": "Encoder colour bandwidth. Lower MHz spreads colour edges before recording.",
    "rec_luma_bw": "Record brightness low-pass. Lower MHz removes fine detail; tape speed scales this again.",
    "preemph_db": "Boosts high-frequency brightness before FM; playback applies matching de-emphasis. More can produce edge clipping.",
    "white_clip": "Upper record-stage clipping voltage after pre-emphasis. Lower values flatten bright edges.",
    "dark_clip": "Lower record-stage clipping voltage. Raising it clips dark excursions and can affect sync.",
    "fm_sync_mhz": "FM carrier frequency at sync-tip voltage. PAL VHS nominal is 3.8 MHz; changing it alters the recording format.",
    "fm_dev_mhz": "FM frequency change per volt. Nominal 1 MHz/V maps sync to white over 3.8–4.8 MHz.",
    "head_bw": "RF head/tape low-pass bandwidth. Lower MHz suppresses FM sidebands and fine detail.",
    "chroma_rec_bw": "Colour separation half-band around the PAL subcarrier before colour-under recording.",
    "chroma_play_bw": "Colour-under playback filter width. Lower MHz softens colour boundaries and reduces colour noise.",
    "chroma_noise": "Random colour-channel noise. Higher values add coloured speckles and unstable colour detail.",
    "chroma_gain": "Playback colour amplitude multiplier; burst regulation and TV decoding also influence visible saturation.",
    "acc": "Automatic colour control regulates playback burst level. Disable to expose colour level changes from the tape.",
    "chroma_delay_ns": "Net colour-versus-brightness delay after automatic filter alignment: positive moves colour right, negative left; zero aligns edges.",
    "lo_phase_err": "Colour playback oscillator phase offset. PAL-D cancels some phase errors; PAL-S reveals more hue error.",
    "tb_jitter_ns": "Random horizontal timing error per scan line. Higher nanoseconds make vertical edges shake.",
    "tb_wobble_ns": "Slow horizontal timing drift amplitude. Higher values make the picture sway; TV AFC may conceal it.",
    "tb_wobble_hz": "Rate of the slow horizontal wobble in cycles per second.",
    "tb_skew_us": "Top-of-field flagging amplitude. Negative bends the top left; positive bends it right.",
    "skew_random": "Chooses a new top-skew direction each field rather than retaining a consistent bend.",
    "hs_shift_us": "Horizontal displacement near the bottom head-switch zone. Negative left, positive right.",
    "hs_random": "Randomizes head-switch displacement direction independently for each field.",
    "hs_lines": "Legacy-overlay mode only: old whole-line zone before the field boundary. RF mode uses fractional switching advance.",
    "hs_noise": "Fractional RF loss at head changeover. Higher values deepen carrier loss; demodulation and tape noise produce the transient.",
    "hs_shift_rate": "Speed of the changing head-switch displacement. Requires nonzero shift variation.",
    "hs_snow_us": "Horizontal length of the head-switch snow burst in microseconds; a whole scan line is 64 µs.",
    "hs_snow_pos": "Base horizontal position of head-switch snow: 0 left, 1 right. Jitter and drift move it around this point.",
    "dropout_rate": "Expected dropout event density per frame. Higher values create more short RF losses; DOC can hide them.",
    "dropout_len_us": "Typical horizontal duration of RF losses. Higher values make longer dropout streaks.",
    "dropout_depth": "Fractional RF attenuation during a dropout. Near 1 means almost complete signal loss.",
    "track_band": "Strength of a travelling tracking-error band. Enables the band smear control; 0 disables this band.",
    "track_speed": "Vertical speed of the tracking band in field lines per frame; negative reverses its motion.",
    "wr_period": "Spacing between travelling wrinkle events in frames. At 25 fps, 75 frames equals 3 seconds; requires travelling wrinkle enabled.",
    "wr_hmin": "Minimum random travelling-band height in field lines. Keep no greater than the maximum.",
    "wr_hmax": "Maximum random travelling-band height in field lines. Keep no smaller than the minimum.",
    "wr_speed": "Downward travelling wrinkle speed in field lines per frame. Requires travelling wrinkles enabled.",
    "wr_white": "Brightness of travelling crease bands: 0 preserves repeated picture detail, 1 produces white damage.",
    "wr_ragged": "Irregularity of travelling-band edges. Higher values make broken, uneven crease boundaries.",
    "wrinkle_gap": "Spacing between ordinary wrinkle bands. Zero spreads them evenly; requires more than one band.",
    "wrinkle_height": "Height of the ordinary speed-error crease zone in field lines; requires nonzero wrinkle severity.",
    "wrinkle_pos": "Vertical centre of the ordinary crease: 0 top, 1 bottom; drift moves it over time.",
    "wrinkle_drift": "Ordinary crease vertical drift per frame in field lines. Negative moves upward; zero keeps its position.",
    "wrinkle_shift_us": "Random horizontal line-start scatter inside the ordinary crease. Higher microseconds add stronger tears.",
    "play_luma_bw": "Playback brightness low-pass. Lower MHz makes the recorded picture softer.",
    "sharpen": "High-frequency detail boost after playback. Higher values add edge halos and emphasize tape noise.",
    "out_bw": "Composite cable low-pass bandwidth. Lower MHz attenuates fine detail and can damage the PAL colour carrier.",
    "out_noise": "Noise added after the VCR at the composite output, independent of tape wear.",
    "ghost": "Strength of a delayed composite-signal reflection. Zero disables cable ghosting.",
    "ghost_ns": "Delay of the reflected signal. Higher values move the ghost farther right; requires reflection strength above zero.",
    "tv_apc": "TV colour burst-lock response speed. Low values retain more slow phase error; high follows the burst faster.",
    "tv_luma_bw": "TV brightness decoding bandwidth. Lower MHz softens detail at the final display stage.",
    "tv_chroma_bw": "TV decoded-colour low-pass bandwidth. Lower MHz makes colour edges softer.",
    "tv_brightness": "Final displayed black-level offset after decoding; does not change the recorded signal.",
    "tv_contrast": "Final displayed brightness contrast after decoding; high settings can clip highlights.",
    "tv_saturation": "Final displayed colour saturation. Zero displays monochrome without changing tape recording.",
    "tv_hue": "Final colour rotation in degrees, after PAL decoding. This is a display adjustment.",
    "seed": "Deterministic noise/damage seed. Same seed, frame and parameters reproduce the same damage when seeking or exporting.",
}


def help_for(spec):
    text = HELP.get(spec["key"]) or spec["tip"]
    if not text:
        raise ValueError(f"Missing help for {spec['key']}")
    if spec["kind"] in ("float", "int"):
        text += f"\nRange: {spec['lo']:g} … {spec['hi']:g}; default: {spec['default']:g}. Type an exact value beside the slider."
    elif spec["kind"] == "choice":
        text += "\nOptions: " + ", ".join(spec["lo"]) + f". Default: {spec['default']}."
    else:
        text += f"\nDefault: {'on' if spec['default'] else 'off'}."
    return text


def preset_info(name):
    return PRESET_INFO.get(name, ("Legacy / experimental", "Original project preset. Preserved for compatibility; damage and EP settings are illustrative, not a calibrated PAL deck."))
