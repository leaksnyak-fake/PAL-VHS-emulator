"""Parameter registry. Every knob of the simulation lives here (GUI is generated from it)."""
from __future__ import annotations
import json
import math

SPECS: list[dict] = []


def _a(key, label, group, kind, default, lo=None, hi=None, step=None, tip=""):
    SPECS.append(dict(key=key, label=label, group=group, kind=kind, default=default,
                      lo=lo, hi=hi, step=step, tip=tip))


# ---------------------------------------------------------------- Input
G = "1 Input"
_a("aspect", "Fit to 4:3", G, "choice", "fit", ["fit", "crop", "stretch"],
   tip="fit = letterbox/pillarbox, crop = fill 4:3, stretch = ignore aspect")
_a("export_fields", "Export fields", G, "choice", "interlaced", ["interlaced", "field 1 only", "field 2 only"],
   tip="interlaced: normal woven 576-line frame (both fields). 'field 1/2 only': only that field is rendered and "
       "every line is doubled -> a progressive, non-interlaced file (no combing, no interlace flags, ~2x faster). "
       "The GUI export also follows the 'Field 1/2 only' view selector")
_a("field_mode", "Field sampling", G, "choice", "temporal", ["temporal", "frame"],
   tip="temporal: field 2 is taken 1/50 s after field 1 (real interlace, combing on motion). "
       "frame: both fields come from one source frame (like film on PAL)")
_a("vfilter", "Interlace (anti-twitter) filter", G, "float", 0.25, 0.0, 1.0, 0.05,
   tip="Vertical low-pass before the frame is split into fields")
_a("in_brightness", "Brightness", G, "float", 0.0, -0.3, 0.3, 0.01)
_a("in_contrast", "Contrast", G, "float", 1.0, 0.5, 1.5, 0.01)
_a("in_saturation", "Saturation", G, "float", 1.0, 0.0, 2.0, 0.01)

# ---------------------------------------------------------------- Encoder
G = "2 PAL encoder"
_a("enc_luma_bw", "Luma bandwidth (MHz)", G, "float", 5.0, 2.0, 6.0, 0.1)
_a("enc_chroma_bw", "U/V bandwidth (MHz)", G, "float", 1.3, 0.3, 2.0, 0.05)
_a("bypass_tape", "Bypass VHS (encoder -> TV only)", G, "bool", False,
   tip="Shows pure PAL encode/decode artefacts (cross-colour, dot crawl)")

# ---------------------------------------------------------------- VHS record
G = "3 VHS record (luma FM)"
_a("tape_speed", "Tape speed", G, "choice", "SP", ["SP", "LP", "EP"],
   tip="LP/EP: narrower bandwidth, more noise")
_a("rec_luma_bw", "Record luma bandwidth (MHz)", G, "float", 3.4, 1.5, 4.5, 0.05)
_a("preemph_db", "Pre-emphasis (dB)", G, "float", 8.0, 0.0, 14.0, 0.5)
_a("white_clip", "White clip (V)", G, "float", 0.95, 0.7, 1.3, 0.01)
_a("dark_clip", "Dark clip (V)", G, "float", -0.42, -0.6, -0.3, 0.01)
_a("fm_sync_mhz", "FM carrier at sync tip (MHz)", G, "float", 3.8, 3.0, 4.2, 0.05)
_a("fm_dev_mhz", "FM deviation (MHz per volt)", G, "float", 1.0, 0.6, 1.6, 0.05)

# ---------------------------------------------------------------- Tape
G = "4 Tape & head"
_a("head_bw", "Head/tape RF bandwidth (MHz)", G, "float", 7.2, 5.0, 8.5, 0.1)
_a("rf_rate", "RF section sample rate", G, "choice", "2x", ["2x", "1x"],
   tip="2x = 35.5 MHz (accurate FM sidebands, slower). 1x = 17.7 MHz: ~25% faster render, tiny differences")
_a("head_peak_mhz", "Head/preamp resonance (MHz)", G, "float", 5.0, 4.2, 6.0, 0.1,
   tip="Head Q network peak. Service manuals tune VHS heads to ~4.9-5.0 MHz")
_a("head_peak_db", "Head/preamp resonance gain (dB)", G, "float", 3.0, 0.0, 9.0, 0.5,
   tip="Boosts the upper FM sidebands (4.8 MHz white edges) and their noise")
_a("tape_noise", "Tape/head noise (RF)", G, "float", 0.033, 0.0, 0.3, 0.005,
   tip="White noise added to the RF signal, relative to carrier amplitude 1.0")
_a("tape_wear", "Tape wear (signal loss)", G, "float", 0.0, 0.0, 1.0, 0.02,
   tip="Overall RF level reduction -> more FM noise / sparkles")

# ---------------------------------------------------------------- Chroma
G = "5 Chroma (colour-under)"
_a("cu_level_db", "Colour-under record level (dB re FM)", G, "float", -20.0, -30.0, -8.0, 0.5,
   tip="Burst amplitude of the 627 kHz colour-under relative to the unit FM carrier. "
       "Real decks record chroma ~20 dB under the luma FM (2-5 mV vs 25-70 mV at the record amp)")
_a("chroma_rec_bw", "Chroma record half-band (MHz)", G, "float", 0.9, 0.3, 1.3, 0.05)
_a("chroma_play_bw", "Colour-under bandwidth (MHz)", G, "float", 0.55, 0.2, 1.1, 0.05)
_a("chroma_noise", "Chroma noise", G, "float", 0.012, 0.0, 0.1, 0.002)
_a("chroma_gain", "Chroma gain", G, "float", 1.0, 0.3, 2.0, 0.05)
_a("acc", "Chroma ACC (burst level control)", G, "bool", True)
_a("chroma_delay_ns", "Chroma delay (ns)", G, "float", 110.0, -800.0, 800.0, 10.0,
   tip="VHS chroma lags luma")
_a("apc_speed", "Player colour lock (APC) speed", G, "float", 0.15, 0.02, 1.0, 0.01,
   tip="Phase-lock of the colour up-converter to the burst: low = slow PLL, hue wobble from jitter survives")
_a("lo_phase_err", "Playback LO phase error (deg)", G, "float", 0.0, -90.0, 90.0, 1.0)

_a("cu_phase_model", "Colour-under phase sequence", G, "choice", "PAL VHS", ["PAL VHS", "legacy 90deg"],
   tip="PAL VHS: head A unchanged, head B delayed 90 degrees each line in colour-under (JVC VTG82063). Legacy reproduces the old common rotation for comparison.")

# ---------------------------------------------------------------- Mechanics
G = "6 Timebase & mechanics"
_a("tb_jitter_ns", "Line jitter (ns rms)", G, "float", 35.0, 0.0, 300.0, 1.0)
_a("tb_wobble_ns", "Slow wobble (ns)", G, "float", 120.0, 0.0, 1500.0, 10.0)
_a("tb_wobble_hz", "Wobble rate (Hz)", G, "float", 1.7, 0.1, 15.0, 0.1)
_a("tb_skew_us", "Top skew / flagging (us, - left / + right)", G, "float", 1.2, -12.0, 12.0, 0.1)
_a("skew_random", "Random skew direction per field", G, "bool", False)
G = "6b Head switching"
_a("hs_residual", "Head-switch snow strength", G, "float", 0.0, 0.0, 1.0, 0.05,
   tip="Original-style waveform snow: a soft bright head, correlated grain and a fading tail, passed through the output and TV decoder. Zero disables it. Motion moves the streak, not the picture lines.")
_a("hs_residual_width_px", "Snow width (720-raster pixels)", G, "int", 9, 1, 60, 1,
   tip="Nominal width/time scale in native 720-raster pixels. Length breathes per field as in the original effect, and filtering creates a soft tail beyond this nominal size. This is not a hard-edged pixel box.")
_a("hs_residual_height", "Snow height (lines per field)", G, "int", 1, 1, 4, 1,
   tip="One or two scan lines per field for the supplied reference. Each field has independent grain; the woven frame has twice as many interleaved rows.")
_a("hs_residual_bottom_px", "Snow gap to bottom (woven-frame rows)", G, "int", 5, 0, 80, 1,
   tip="Assumed interpretation of the supplied reference: number of full 576-line woven-frame rows below the snow band. The field grids differ by one row in parity. Independent of RF switch advance.")
_a("hs_residual_x", "Snow base horizontal position", G, "float", 0.12, 0.0, 1.0, 0.01,
   tip="Base horizontal start: 0 left, 1 right. Motion and position jitter are added relative to this point. Changes affect both preview and export.")
_a("hs_residual_motion", "Snow motion", G, "choice", "Drift + jitter", ["Stationary", "Drift", "Random jumps", "Drift + jitter"],
   tip="Move the narrow snow while playing or stepping frames. Motion changes snow position only, not picture-line timing or vertical position. Deterministic when seeking/exporting; paused frames stay still.")
_a("hs_residual_speed_px", "Snow drift (pixels per field)", G, "float", 12.0, -60.0, 60.0, 0.5,
   tip="Horizontal travel each 1/50-second field in Drift modes. Negative moves left; zero stops steady drift. Bounces at the picture edges without clipping the snow width.")
_a("hs_residual_jitter_px", "Snow jitter (pixels rms)", G, "float", 10.0, 0.0, 150.0, 0.5,
   tip="Random horizontal jitter of the snow, different every field, plus a smaller independent jitter per snow line. Used by Random jumps and Drift + jitter (drift and jitter add up). This moves the snow patch, not the image scan lines. Zero disables jitter.")
_a("hs_residual_sweep_px", "Snow sweep (pixels per field line)", G, "float", 3.0, -30.0, 30.0, 0.5,
   tip="Horizontal offset for each additional snow line in the same field. Applies to every motion mode; zero aligns the lines vertically. Does not widen any individual streak.")
_a("hs_model", "Head-switch model", G, "choice", "RF switch", ["RF switch", "legacy overlay", "off"],
   tip="RF switch: localized RF loss and FM phase mismatch. Legacy overlay: original painted white snow. Off disables head-switch disturbance and masking, not other tape errors.")
_a("hs_advance", "Switch before vertical sync (H)", G, "float", 6.5, 1.0, 20.0, 0.1,
   tip="Nominal PAL VHS 6.5 H before broad vertical sync. One H is 64 us. Larger switches earlier/higher. Existing field timing remains a whole-line approximation.")
_a("hs_gap_us", "RF interruption duration (us)", G, "float", 3.0, 0.0, 64.0, 0.1,
   tip="Carrier-loss duration at head changeover. The demodulator produces the visible transient; this does not paint a white stripe.")
_a("hs_recovery_us", "RF recovery time constant (us)", G, "float", 3.0, 0.1, 64.0, 0.1,
   tip="Exponential RF-envelope recovery after the interruption; larger values spread recovery along the scan line.")
_a("hs_phase_deg", "FM phase discontinuity (deg)", G, "float", 25.0, 0.0, 180.0, 1.0,
   tip="Incoming-head carrier phase mismatch, opposite signs in the two fields. Produces a localized FM discriminator transient; not a hue control or random line shake.")
_a("hs_servo_lines", "Faulty servo vertical excursion (H)", G, "float", 0.0, 0.0, 90.0, 0.1,
   tip="Explicit servo fault: vertical movement of the switch point. Zero for normal decks. Separate from horizontal line jitter and deterministic across seeks.")
_a("hs_mask_lines", "SWP black mask (field lines)", G, "int", 0, 0, 20, 1,
   tip="Replace the last N active field lines with video black after playback; preserve sync and burst. Hides picture detail, not RF damage. Zero preserves full raster.")
_a("hs_shift_us", "Head-switch shift (us, - left / + right)", G, "float", 1.0, -20.0, 20.0, 0.1)
_a("hs_shift_var", "Head-switch shift variation (+- fraction)", G, "float", 0.0, 0.0, 0.5, 0.01,
   tip="How much the shift size wobbles from frame to frame. 0 = the shift stays exactly at the set value "
       "(use together with 'Head-switch line jitter' = 0 for a perfectly steady shift)")
_a("hs_shift_rate", "Head-switch shift variation speed (Hz)", G, "float", 4.0, 0.1, 12.5, 0.1)
_a("hs_random", "Random head-switch direction per field", G, "bool", False)
_a("hs_lines", "Legacy switch zone (lines)", G, "int", 7, 1, 20, 1)
_a("hs_noise", "Head-switch RF loss depth", G, "float", 0.65, 0.0, 1.0, 0.05)
_a("hs_snow", "Legacy head-switch snow streak", G, "float", 0.0, 0.0, 1.0, 0.05,
   tip="Bright snow burst at the start (left) of the head-switch lines that fades out toward the right")
_a("hs_snow_lines", "Head-switch snow height (lines per field)", G, "int", 1, 1, 8, 1,
   tip="How many scan lines of each field carry the snow burst (the two fields each have their own, so in the woven frame 1 = about 2 neighbouring rows). More lines fade out in strength")
_a("hs_snow_us", "Head-switch snow length (us)", G, "float", 16.0, 2.0, 45.0, 0.5)
_a("hs_snow_speed", "Head-switch snow drift (us/field, 0 = none)", G, "float", 0.0, -30.0, 30.0, 0.5,
   tip="The snow burst moves horizontally from field to field: +7 us/field crosses the picture in ~7 fields (0.15 s) and wraps around. 0 = stays at the left edge")
_a("hs_snow_pos", "Head-switch snow base position (0 left .. 1 right)", G, "float", 0.12, 0.0, 1.0, 0.01)
_a("hs_snow_jitter", "Head-switch snow jitter (us rms)", G, "float", 0.0, 0.0, 40.0, 0.5,
   tip="Random left/right jumps of the snow burst, different every field (jitter around the base position)")
_a("hs_jitter_us", "Head-switch line jitter (us rms)", G, "float", 0.0, 0.0, 15.0, 0.1,
   tip="Random left/right shake of every line in the head-switch zone")
_a("hs_snow_sweep", "Head-switch snow sweep (us/line)", G, "float", 3.0, 0.0, 14.0, 0.5,
   tip="Each following head-switch line starts the streak further to the right, so the snow flicks left to right")

# ---------------------------------------------------------------- Dropouts
G = "7 Dropouts & tracking"
_a("dropout_rate", "Dropouts per frame", G, "float", 1.5, 0.0, 40.0, 0.5)
_a("dropout_len_us", "Dropout length (us)", G, "float", 9.0, 1.0, 60.0, 1.0)
_a("dropout_depth", "Dropout depth", G, "float", 0.9, 0.2, 1.0, 0.05)
_a("doc", "Dropout compensator (DOC)", G, "bool", True,
   tip="Player replaces dropouts with the previous line")
_a("track_band", "Tracking noise band", G, "float", 0.0, 0.0, 1.0, 0.05)
_a("tracking", "Tracking knob (- noise at bottom, + at top)", G, "float", 0.0, -1.0, 1.0, 0.05,
   tip="Manual tracking misadjustment. 0 = perfectly tracked. Negative: noise builds up from the bottom of the "
       "picture; positive: from the top. Larger |value| = more of the picture is covered, down to full snow")
_a("snow_streaks", "Snow streak density", G, "float", 1.0, 0.0, 4.0, 0.1,
   tip="Long single-line white/black streaks in the noise of lost tracking. 0 = none")
_a("snow_streak_us", "Snow streak length (us, typical)", G, "float", 9.0, 1.0, 40.0, 0.5,
   tip="Median streak length in microseconds (64 us = full line); lengths vary around it")
_a("snow_sparse", "Sparse streaks over the whole frame (weak tape)", G, "float", 0.0, 0.0, 4.0, 0.1,
   tip="Short white streaks on random lines anywhere in the picture, independent of the tracking band"),
_a("snow_grain", "Snow grain coarseness", G, "float", 0.5, 0.0, 1.0, 0.05,
   tip="0 = fine single-pixel noise, 1 = coarse horizontally stretched flecks")
_a("track_speed", "Band speed (lines/frame)", G, "float", 3.0, -30.0, 30.0, 0.5)
_a("track_accel", "Tracking band: speeds up toward the bottom", G, "float", 0.0, 0.0, 2.0, 0.05,
   tip="Same analog speed-up as for creases: slower at the top, faster near the bottom. 0 = constant speed")
_a("track_wobble", "Tracking band: wobble (lines)", G, "float", 0.0, 0.0, 8.0, 0.1,
   tip="Slow back-and-forth wobble of the tracking band position, in lines")
_a("track_smear", "Tracking band line smear/duplication", G, "float", 0.7, 0.0, 1.0, 0.05,
   tip="Inside the tracking band the head reads the tape at a wandering speed: lines stretch/compress, shift "
       "sideways and repeat (long white/grey streaks, colour lost). Needs 'Tracking noise band' > 0")

# ---------------------------------------------------------------- Wrinkle
G = "7b Tape wrinkle"
_a("wr_travel", "Travelling wrinkle (white band from the top)", G, "bool", False,
   tip="A crease band of random height enters at the top, runs down the picture and leaves at the bottom: "
       "its lines are duplicated / stretched and go solid white with ragged edges")
_a("wr_period", "Time between wrinkles (frames)", G, "int", 75, 10, 500, 5)
_a("wr_hmin", "Band height min (field lines)", G, "float", 3.0, 1.0, 60.0, 1.0)
_a("wr_hmax", "Band height max (field lines)", G, "float", 14.0, 1.0, 60.0, 1.0)
_a("wr_speed", "Band speed (field lines/frame)", G, "float", 6.0, 0.5, 40.0, 0.5)
_a("wr_count", "White bands at once", G, "int", 1, 1, 6, 1,
   tip="Exactly this many white bands are on screen at the same time (each with its own random height)")
_a("wr_gap", "Gap between simultaneous bands (lines)", G, "float", 0.0, 0.0, 250.0, 5.0,
   tip="0 = random positions. Otherwise the bands follow each other at this distance (top to top)")
_a("wr_hold", "Train length with several bands (frames)", G, "int", 150, 10, 1000, 10,
   tip="With 'White bands at once' > 1 the bands run as a train: each band that leaves at the bottom is replaced "
       "at the top, so exactly that many bands are on screen, for this many frames")
_a("wr_white_h", "White part height (lines, 0 = whole band)", G, "float", 0.0, 0.0, 90.0, 1.0,
   tip="Size of the solid-white part, starting at the band's first (top) line. The duplicated (repeated) lines keep the size set by "
       "'Band height min/max', so the white can be made smaller or bigger without changing the line duplication")
_a("wr_dup_dark", "Repeated (non-white) lines darkening", G, "float", 0.0, 0.0, 1.0, 0.05,
   tip="The repeated lines of the band that are not in the white part are a copy of the line above the band. On a "
       "bright picture that copy also looks white; this fades it toward black so only the white part reads as white")
_a("wr_full_entry", "Band enters at the top with full size", G, "bool", True,
   tip="On: the band is full height from the first picture line (no growing-in at the top, no duplicated "
       "white fields of the wrong size). Off: it slides in from above, growing line by line")
_a("wr_accel", "Analog motion: speeds up toward the bottom", G, "float", 0.6, 0.0, 2.0, 0.05,
   tip="Measured on real tape: a crease moves slowly at the top and 1.3-2x faster near the bottom. 0 = constant "
       "speed (digital look). The set speed is the average over the picture")
_a("wr_wobble", "Analog motion: wobble (lines)", G, "float", 1.5, 0.0, 8.0, 0.1,
   tip="Slow sideways-in-time speed wobble of each band (tape tension), a few lines")
_a("wr_rise", "Band grows in over (frames)", G, "int", 25, 0, 120, 1,
   tip="A crease does not appear at full height: it starts thin (about a third) and thickens over these frames")
_a("wr_soft", "Soft edges (top fuzzy, bottom crisp)", G, "float", 0.6, 0.0, 1.0, 0.05,
   tip="0 = hard line edges. The top edge of a real band fades in gradually, the bottom edge ends sharply")
_a("wr_sat", "Satellite bands (thin companions)", G, "float", 0.5, 0.0, 1.0, 0.05,
   tip="Thin secondary creases that travel together with the main band (about 0-2 per band at 1.0)")
_a("wr_flicker", "White flicker (field to field)", G, "float", 0.5, 0.0, 1.0, 0.05,
   tip="The white part flickers: its brightness is dimmed by up to this fraction. The flicker is smooth in time (a few frames) with only a little field-to-field randomness")
_a("wr_shrink", "Band shrinks toward the bottom", G, "float", 0.6, 0.0, 1.5, 0.05,
   tip="Bands lose height as they move down the picture. Each band gets its own random rate (0.4x-1.4x of this "
       "setting); a band that becomes smaller than about one line disappears, which can happen anywhere in the "
       "picture - above 1.0 many bands vanish before the bottom. 0 = constant height")
_a("wr_chroma_loss", "Colour loss under the stretched lines (chance)", G, "float", 0.4, 0.0, 1.0, 0.05,
   tip="Chance that a band also loses its colour over the whole stretched (repeated) area, not just in the white part")
_a("wr_style", "Band style", G, "choice", "white", ["white", "grey fade"],
   tip="white: solid white repeated lines. grey fade: grey lines that fade to black toward the bottom of the band with "
       "vertical streaks and no colour (head lifted off the tape, as on a blank blue tape)")
_a("wr_grey", "Grey fade: top brightness", G, "float", 0.45, 0.1, 0.9, 0.05,
   tip="Brightness of the top of a grey-fade band; it fades to black toward the bottom of the band")
_a("wr_white", "Band whiteness", G, "float", 0.9, 0.0, 1.0, 0.05)
_a("wr_dup", "Band horizontal tear (0 = clean line repeat)", G, "float", 0.0, 0.0, 1.0, 0.05, tip="0 = the line above the band is repeated unchanged over the band height. Higher adds a random horizontal stretch/offset per line")
_a("wr_ragged", "Ragged edges", G, "float", 0.5, 0.0, 1.0, 0.05)
_a("cu_glitch", "Colour lock glitch (phase / saturation)", G, "float", 0.0, 0.0, 1.0, 0.05,
   tip="Occasional episodes where the colour-under phase is lost: the whole picture turns green/purple with bands of "
       "wrong hue, then a saturated cast. 0 = off")
_a("chroma_band", "Colour banding (slow line-group hue/saturation drift)", G, "float", 0.0, 0.0, 1.0, 0.05,
   tip="Soft horizontal bands of slightly different hue and saturation, a few to tens of lines tall, drifting slowly "
       "(colour-under phase/gain instability, visible on flat colour such as a blank blue tape)")
_a("cu_glitch_period", "Colour glitch: one episode every (frames)", G, "int", 300, 40, 2000, 10,
   tip="Average spacing of colour-lock glitch episodes (one random episode inside every such period)")
_a("cu_glitch_len", "Colour glitch: episode length (frames)", G, "int", 20, 2, 80, 1,
   tip="How many frames one colour-lock glitch episode lasts (it ramps in and out)")
_a("wrinkle", "Wrinkle severity", G, "float", 0.0, 0.0, 1.0, 0.05,
   tip="Creased tape: the head reads a local patch at a wrong, wandering speed (lines stretched/compressed, "
       "repeated or skipped, FM carrier shifted -> brightness stripes, chroma lost) plus head-lift dropouts")
_a("wrinkle_count", "Wrinkle bands (usual wrinkle)", G, "int", 1, 1, 6, 1,
   tip="Number of usual (stretch/skip) wrinkle bands in the picture at the same time")
_a("wrinkle_gap", "Gap between wrinkle bands (lines, 0 = spread evenly)", G, "float", 0.0, 0.0, 250.0, 5.0)
_a("wrinkle_height", "Wrinkle height (lines)", G, "float", 24.0, 4.0, 90.0, 1.0)
_a("wrinkle_pos", "Wrinkle position (0 top .. 1 bottom)", G, "float", 0.6, 0.0, 1.0, 0.01)
_a("wrinkle_drift", "Wrinkle drift (lines/frame)", G, "float", 0.0, -20.0, 20.0, 0.5)
_a("wrinkle_stretch", "Vertical stretch (line repeat factor)", G, "float", 2.5, 1.0, 6.0, 0.1,
   tip="2.5 = each source line is shown ~2.5 times in the middle of the wrinkle (then lines are skipped to catch up)")
_a("wrinkle_speed_pct", "Read-speed error (+- %)", G, "float", 12.0, 0.0, 60.0, 1.0,
   tip="Tape speed error past the head. +10 % raises the FM carrier 10 % = ~+0.43 V brightness shift")
_a("wrinkle_shift_us", "Line start scatter (us)", G, "float", 6.0, 0.0, 30.0, 0.5)

# ---------------------------------------------------------------- Playback
G = "8 VHS playback"
_a("play_luma_bw", "Playback luma bandwidth (MHz)", G, "float", 3.6, 1.5, 5.0, 0.05)
_a("sharpen", "Player sharpness (detail boost)", G, "float", 0.35, 0.0, 1.5, 0.05)

# ---------------------------------------------------------------- RCA
G = "9 RCA output"
_a("out_gain", "Output level", G, "float", 1.0, 0.5, 1.5, 0.01,
   tip="The TV AGC normalises this, but scope shows the level")
_a("out_bw", "Cable bandwidth (MHz)", G, "float", 6.5, 3.0, 8.5, 0.1)
_a("out_noise", "Output noise", G, "float", 0.008, 0.0, 0.1, 0.002)
_a("ghost", "Cable reflection (ghost)", G, "float", 0.0, 0.0, 0.5, 0.01)
_a("ghost_ns", "Ghost delay (ns)", G, "float", 450.0, 100.0, 3000.0, 10.0)

# ---------------------------------------------------------------- TV
G = "A TV decoder"
_a("tv_decoder", "Colour decoder", G, "choice", "PAL-D", ["PAL-D", "PAL-S"],
   tip="PAL-D = delay-line decoder, PAL-S = simple (hue errors show)")
_a("tv_afc", "Horizontal lock (AFC)", G, "float", 0.35, 0.02, 1.0, 0.01,
   tip="1.0 = ideal time-base corrector (wobble hidden); low = jitter visible")
_a("tv_apc", "Colour burst lock speed", G, "float", 0.5, 0.05, 1.0, 0.05)
_a("tv_luma_bw", "Luma bandwidth (MHz)", G, "float", 5.0, 2.5, 6.0, 0.1)
_a("tv_chroma_bw", "Chroma bandwidth (MHz)", G, "float", 1.1, 0.4, 2.0, 0.05)
_a("tv_brightness", "Brightness", G, "float", 0.0, -0.3, 0.3, 0.01)
_a("tv_contrast", "Contrast", G, "float", 1.0, 0.5, 1.5, 0.01)
_a("tv_saturation", "Saturation", G, "float", 1.0, 0.0, 2.0, 0.01)
_a("tv_hue", "Hue (deg)", G, "float", 0.0, -45.0, 45.0, 1.0)

G = "B Misc"
_a("seed", "Noise seed", G, "int", 1, 0, 9999, 1)

SPEC = {s["key"]: s for s in SPECS}
GROUPS = list(dict.fromkeys(s["group"] for s in SPECS))


class Params:
    """Attribute-style, validated parameter set (picklable, JSON-serialisable)."""

    def __init__(self, **kw):
        object.__setattr__(self, "_v", {s["key"]: s["default"] for s in SPECS})
        for k, v in kw.items():
            self.set(k, v)

    REMOVED = {"hs_residual_forward_frames", "hs_residual_backward_frames",
               "hs_residual_forward_px", "hs_residual_backward_px"}      # old 'Forward/back steps' mode

    def set(self, key, value):
        if key in self.REMOVED:                       # old saved parameter files still load
            return
        if key == "hs_residual_motion" and value == "Forward/back steps":
            value = "Drift + jitter"
        s = SPEC[key]
        k = s["kind"]
        if k == "bool":
            value = bool(value)
        elif k == "int":
            value = int(min(max(int(value), s["lo"]), s["hi"]))
        elif k == "float":
            value = float(value)
            if not math.isfinite(value):
                raise ValueError(f"{key}: value must be finite")
            value = float(min(max(value, s["lo"]), s["hi"]))
        elif k == "choice":
            if value not in s["lo"]:
                raise ValueError(f"{key}: {value!r} not in {s['lo']}")
        self._v[key] = value

    def __getattr__(self, name):
        if name == "_v":
            raise AttributeError(name)
        try:
            return self._v[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self.set(name, value)

    def __getstate__(self):
        return dict(self._v)

    def __setstate__(self, st):
        object.__setattr__(self, "_v", dict(st))

    def to_dict(self):
        return dict(self._v)

    def copy(self):
        return Params(**self._v)

    def update(self, d):
        for k, v in d.items():
            if k in SPEC:
                self.set(k, v)
        return self

    def save(self, path):
        with open(path, "w") as f:
            json.dump(self._v, f, indent=2)

    @staticmethod
    def load(path):
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Parameter file must contain a JSON object")
        return Params().update(data)


PRESETS = {
    # values below the "reference" preset come from the research (see README); the LP/EP/worn offsets are judgement
    "VHS SP - reference (service data)": dict(
        tape_speed="SP", fm_sync_mhz=3.8, fm_dev_mhz=1.0,          # 3.8 MHz sync -> 4.8 MHz white
        cu_level_db=-20.0,                                          # colour-under ~20 dB under the FM
        head_peak_mhz=5.0, head_peak_db=3.0,                        # head Q network peaked ~5 MHz
        rec_luma_bw=3.4, play_luma_bw=3.6, preemph_db=8.0,          # -3 dB ~2.5 MHz, 240 TVL class
        tape_noise=0.033, chroma_delay_ns=110.0, hs_lines=7),       # ~33 dB unweighted S/N, head switch 7 lines
    "VHS SP - good tape": {},
    "VHS LP - worn": dict(tape_speed="LP", tape_noise=0.07, tb_jitter_ns=60, tb_wobble_ns=250,
                          dropout_rate=4, chroma_noise=0.025, tape_wear=0.15, tb_skew_us=2.5,
                          cu_level_db=-21.0, head_peak_db=2.5),
    "VHS EP - bad dub": dict(tape_speed="EP", tape_noise=0.07, tb_jitter_ns=90, tb_wobble_ns=400,
                             dropout_rate=7, chroma_noise=0.03, tape_wear=0.2, tb_skew_us=5,
                             hs_shift_us=8, track_band=0.5, sharpen=0.6, tv_afc=0.2,
                             cu_level_db=-22.0, head_peak_db=2.0),
    "VHS tracking error (end of tape)": dict(tape_speed="EP", track_band=1.0, track_speed=2.0, track_smear=0.8,
                                             tape_wear=0.25, tape_noise=0.035, chroma_noise=0.006, cu_level_db=-20.0,
                                             tb_jitter_ns=60),
    "VHS tracking knob left (bottom noise)": dict(tracking=-0.9),
    "VHS tracking knob right (top noise)": dict(tracking=0.4),
    "VHS wrinkled tape": dict(wrinkle=0.8, wrinkle_pos=0.55, wrinkle_height=30, wrinkle_stretch=3.0,
                              wrinkle_speed_pct=14, wrinkle_shift_us=5, wrinkle_drift=1.5, tape_wear=0.1,
                              dropout_rate=3),
    "VHS wrinkle - travelling white band": dict(wr_travel=True, wr_period=60, wr_hmin=3, wr_hmax=14,
                                                wr_speed=6, tape_wear=0.05),
    "VHS wrinkle - several bands + creases": dict(wr_travel=True, wr_period=120, wr_hmin=8, wr_hmax=14, wr_speed=4,
                                                  wr_count=3, wr_gap=90, wr_white_h=5, wrinkle=0.7,
                                                  wrinkle_count=2, wrinkle_gap=120, wrinkle_pos=0.5, tape_wear=0.05),
    "VHS SP weak tape - heavy tracking": dict(tape_noise=0.05, tape_wear=0.3, track_band=0.0, tracking=0.0,
                                              snow_sparse=0.4, snow_streak_us=3.5, snow_grain=0.6,
                                              chroma_noise=0.025, chroma_gain=0.9, dropout_rate=4,
                                              dropout_len_us=10, hs_snow=0.5),
    "Clean PAL (no tape)": dict(bypass_tape=True, out_noise=0.0),
    "Pristine deck + TBC": dict(tape_noise=0.02, tb_jitter_ns=5, tb_wobble_ns=0, tb_skew_us=0,
                                hs_shift_us=0, dropout_rate=0, tv_afc=1.0, chroma_noise=0.006,
                                hs_noise=0.0, hs_snow=0.0, cu_level_db=-19.0, head_peak_db=3.0),
    "Extreme": dict(tape_speed="EP", tape_noise=0.2, tb_jitter_ns=250, tb_wobble_ns=1200,
                    dropout_rate=25, tape_wear=0.6, track_band=1.0, hs_shift_us=15, tb_skew_us=10,
                    chroma_noise=0.08, tv_afc=0.1, tv_decoder="PAL-S", ghost=0.25,
                    cu_level_db=-26.0, head_peak_db=6.0, head_peak_mhz=4.6),
}
