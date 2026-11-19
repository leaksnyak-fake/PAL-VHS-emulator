# Historical engine notes (pre-edition-2 baseline)

The following notes describe the original version. Default values, calibration numbers, head phase handling and head-switch effects have since changed. See ../docs/VHS_EFFECTS_REFERENCE.md for the current model.

# pal_vhs - PAL composite + VHS deck simulator (625i / 50 Hz, interlaced, TFF)

    pip install -r requirements.txt        # needs ffmpeg + ffprobe in PATH for export
    python -m pal_vhs video.mp4            # RCA monitor window (run from the folder that contains pal_vhs/)
    python -m pal_vhs in.mp4 --export out.mp4 --preset "VHS LP - worn" --set tb_jitter_ns=80
    python -m pal_vhs --list-params

## Signal flow (every stage works on a real sampled waveform, fs = 17.734 MHz, 1135 samples/line)
1. Source frame -> two fields (field 1 = top/even rows, shown first = TFF). Temporal mode takes field 2 from
   1/50 s later, so motion combs like real interlace.
2. PAL encoder: Y/U/V, band limits, sync / equalising / broad pulses, blanking, swinging burst
   (135/225 deg), quadrature subcarrier 4.43361875 MHz with the PAL V-switch, 313 + 312 lines.
3. VCR record: luma = LPF + 4.43 MHz trap -> pre-emphasis -> white/dark clip -> FM (3.8 MHz sync .. 4.8 MHz white,
   2x oversampled). Chroma = band-pass -> heterodyne to 626.953 kHz (colour-under, per-line phase rotation).
4. Tape/head: head bandwidth, RF level changes (wear, dropouts, tracking band, head-switch), RF noise.
5. VCR playback: FM demod (limiter + discriminator), de-emphasis, detail boost, dropout compensator,
   colour-under low-pass, burst ACC, APC phase lock, up-conversion back to 4.43 MHz,
   time-base errors (line jitter, wobble, top flagging, head-switch shift), chroma delay.
6. RCA output: cable low-pass, reflection, noise.
7. TV: sync slicer + AFC, clamp/AGC, chroma trap, burst-locked demodulator, PAL-D delay line, YUV -> RGB, weave.

The preview "Probe" box shows any stage on any line of either field (waveform + spectrum);
the optional red line (checkbox "Show probe line") marks the probed line.

## Calibration against real VHS (PAL, SP)
`python -m pal_vhs.bench` prints the scope-style numbers below for the current parameters.
Sources: Beeching *Domestic Videocassette Recorders* (PAL service data), JVC/VHS format data, vhs-decode notes.

| item | real VHS | model default |
|---|---|---|
| FM luma | 3.8 MHz sync tip -> 4.8 MHz white, 1 MHz dev | same |
| recorded luma spectrum | starts ~1.3 MHz | RF high-pass 1.4 MHz (was 1.8) |
| head/preamp | Q network peaked ~4.9-5 MHz | +3 dB peak at 5.0 MHz (`head_peak_*`) |
| colour-under | 627 kHz, ~20 dB under the FM (2-5 mV vs 25-70 mV) | `cu_level_db` = -20 (was ~-16.5) |
| luma response | 240 TVL, ~-3 dB at 2.5-3 MHz, steep after 3.5 | -3.1 dB @2.5, -7.9 @3, -17 @3.5, -32 @4 MHz |
| luma noise | triangular FM noise, de-emphasised, peak ~1-2.5 MHz | same shape; 32.6 dB unweighted |
| burst / chroma | chroma at nominal ratio to burst on output | chroma/burst ratio 0.98 (was ~1.37) |
| head switch | 6-8 lines before field sync | 7 lines |

Fixes made in this version
- ACC over-saturation: the 2.3 us burst is only ~1.4 cycles long at 627 kHz so the colour-under filters shave it
  (-3.2 dB). The ACC then boosted real chroma ~1.3x and the TV's burst-referenced gain did not undo it.
  The deck now measures its own burst loss, regulates to the right chroma level and re-inserts the burst at
  nominal level (`Deck.burst_loss`).
- Chroma delay: `chroma_delay_ns` is now the net chroma-vs-luma offset, range -800..+800 ns. 0 = chroma exactly
  aligned with luma, + = chroma later (right), - = earlier (left). The deck measures its own filter delays at
  start-up (`Deck.align`, ~710 ns of colour-under filtering) and removes them. Previously 0 still lagged ~700 ns,
  so the old default of 110 behaved like ~+800 ns. Burst/ACC windows now follow the burst's real position.
- FM demod output is band-limited (7 MHz, 4th order) before the 2:1 decimation (no aliased discriminator noise).
- Colour-under recorded level is a parameter and playback makes up the gain.

## Tracking noise and tape wrinkle (`line_warp` in vhs.py)
Modelled from a real capture of tracking error (night building, "КОНЕЦ" text): the picture is not replaced by
noise, it is torn line by line - bright windows smear into long streaks, shapes repeat over several lines,
text garbles and nearly all colour disappears. The physical cause is the head reading the tape at a wrong,
wandering speed, so each affected line is re-read from the tape stream as
`tape(r[k]*SPL + b[k] + a[k]*n)` before head noise is added:
- `a` (read speed, ~+-7 % in the tracking band, `wrinkle_speed_pct` in a wrinkle): stretches/compresses the line and
  scales every frequency on it. FM carrier up -> white, down -> black (4.3 V per 100 % speed), and the 627 kHz
  colour-under leaves its filter -> chroma lost. `a` also drifts along the line, so streaks fade out.
- `b` scatters the line start (horizontal tearing), `r` repeats source lines (vertical stretch) and the head
  then skips lines to catch up (`wrinkle_stretch`). Line-to-line values are strongly correlated like the real thing.
- RF level dip (existing) + colour killer in the deck and in the TV (burst < ~40 % -> that line has no colour).
- `track_smear` sets how much of this the tracking band adds; `wrinkle*` is a separate, localised crease
  (position, height, drift per frame, severity). Presets: "VHS tracking error (end of tape)", "VHS wrinkled tape".
Verified on a unique-grey-per-line test pattern: inside a wrinkle one source line is shown up to 7 times, then
lines are skipped (130 -> 134 -> 136 -> 139) until the head is back on track.
Not modelled: the rolled-up vertical blanking interval (teletext-like bar) at the bottom of the capture.

## Preview / export
- Each frame's two fields render on separate workers (single scrubbed frame ~1.8x faster, workers pre-warmed).
- Scope taps (~17 MB/frame) are only produced for the paused frame you are inspecting, not during playback.
- Export: output name gets `.mp4` if it has no extension (ffmpeg cannot pick a container otherwise - this was the
  `[Errno 32] Broken pipe`); ffmpeg's own error text is reported if it stops; partial files are removed on
  cancel/failure; `--x264-preset` (default veryfast; the render, not x264, is the bottleneck); falls back to
  libopenh264 / MPEG-4 if ffmpeg has no libx264.

## Speed notes
- Render cost is ~0.55 s per frame per core (many small SciPy filters; float32 does not help them).
  Export scales with cores; `--workers N` overrides the count. Workers are single-threaded (OpenCV/BLAS pools are
  disabled per worker, otherwise N workers x N threads fight for the CPU).
- `rf_rate = 1x` (`--set rf_rate=1x`): RF section at 17.7 MHz instead of 35.5 MHz, ~1.3x faster, but softer
  luma above ~3 MHz and a slightly different FM noise/edge behaviour. Use it for drafts, keep 2x for finals.
- Long exports: render a test range first with `--max-frames 250`.

## Approximations
- Vertical sync is modelled at whole-line resolution (no true half-line offset between fields).
- No head azimuth crosstalk; the dropout compensator copies the previous line (luma and re-modulated chroma).
- FM demod is an ideal analytic-signal discriminator, not a specific PLL/delay-line circuit.
- Audio is passed through unchanged.

## Tracking knob (signed) and editable values
* `tracking` (-1..+1): manual tracking misadjustment, 0 = tracked. **Negative** = head-to-track error grows toward the
  bottom: bottom-heavy bright grey snow with long white/black dashes, colour lost, sync stays locked (the VCR regenerates
  sync/blanking when RF is lost). **Positive** = the same from the top: noise only in the upper part, picture below stays
  clean. Presets "VHS tracking knob left/right" show both. Tuned by eye against SP-mode captures, not a pixel match.
* The number next to every slider is now an edit box: click, type, Enter (clamped to the range, snapped to the slider step).

## Tracking noise
Lost-tracking snow is built from three parts (tab "Dropouts & tracking"): grey FM noise, coarse horizontal grain
(`snow_grain`), and long white/black streaks that each live on ONE field line (`snow_streaks`, `snow_streak_us`).
Neighbouring lines and the other field draw their own streaks, so in the interlaced picture they alternate.
They appear with the tracking knob and inside the tracking band.

## Tape wrinkle (travelling) and head-switch snow
- `wr_travel` (tab "Tape wrinkle"): bands of random height (`wr_hmin`..`wr_hmax` field lines) enter at the top and run
  down the picture at `wr_speed`; every `wr_period` frames a new one. Inside a band lines are duplicated / stretched
  / torn (`wr_dup`), go solid white (`wr_white`) with ragged edges (`wr_ragged`) and lose their colour.
  The schedule depends only on the seed, so preview seeking and parallel rendering stay consistent.
- `hs_snow`, `hs_snow_us`, `hs_snow_sweep` (tab "Timebase & mechanics"): at the head switch the demodulator loses the
  carrier; a bright snow burst starts at the left of the switching line and fades out to the right, and each following
  line starts it a little further right.
- `hs_snow_speed` (us/field): the head-switch snow now travels horizontally. Its start position advances every field
  (+7 us/field = ~190 px per frame) and wraps back to the left edge; negative values run right to left, 0 keeps it at the left edge.
- Head-switch jitter: the snow burst jumps randomly left/right every field around `hs_snow_pos` (`hs_snow_jitter`, us rms; a
  smaller scatter is added per line), and every line of the head-switch zone shakes left/right by `hs_jitter_us`.
  `hs_snow_speed` (steady drift) is kept but is 0 by default.

- `hs_snow_lines` (1..8, default 1): how many scan lines of each field carry the head-switch snow; extra lines fade in strength. Each field has its own burst, so 1 line is roughly 2 neighbouring rows in the woven frame.
- `snow_sparse` (0..4): short white streaks on random lines over the whole frame (weak SP tape look). Preset "VHS SP weak tape - heavy tracking" uses it.
- Tape wrinkle band: the line just above the band is now repeated over the whole band height (vertical stretch, no jitter). `wr_dup` (default 0) only adds an optional horizontal tear.

## Wrinkle bands: separate white size, several bands
* **White part height** (`wr_white_h`): size of the solid-white part, independent of the duplicated-line height
  (`wr_hmin/wr_hmax`). 0 = whole band white. Lines of the band outside the white part are still repeated, just not white.
* **Band enters at the top with full size** (`wr_full_entry`, default on): no growing-in at the first line.
* **White bands at once** (`wr_count`) with **gap** (`wr_gap`, 0 = random positions).
* **Usual wrinkle bands** (`wrinkle_count`, `wrinkle_gap`; 0 = spread evenly). The travelling white bands and the usual
  wrinkle are independent switches, so both can run together at different positions.
* **Repeated (non-white) lines darkening** (`wr_dup_dark`): fades the copied lines toward black so only the white part reads as white on bright pictures.
* With **White bands at once** N > 1 the bands run as a train (`wr_hold` frames): when one leaves at the bottom another
  enters at the top, so N bands are on screen together (they enter one after another at the start of the train and leave
  one after another at its end).
* **Head-switch shift variation** (`hs_shift_var`, `hs_shift_rate`): how much and how fast the head-switch shift wobbles between frames. Set variation 0 and "Head-switch line jitter" 0 for a perfectly steady shift.
* **Layer order** (bottom to top): all other effects, then tape wrinkles (usual and travelling), then tracking noise on top of everything. Inside the usual wrinkle lines the dropout compensator, sparse snow and head-switch snow are taken back; wrinkle head-lift no longer counts as tracking loss.
* **Single-field export** (`export_fields`, or the "Field 1/2 only" view selector in the GUI): only that field is rendered and each line is doubled, giving a progressive 720x576 file with no interlace flags and no combing, about twice as fast. CLI: `--set "export_fields=field 1 only"`.
