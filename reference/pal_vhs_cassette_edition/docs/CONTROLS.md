# Control reference

124 controls. Generated from the actual GUI schema and hover text.

See VHS_EFFECTS_REFERENCE.md for researched head-switching behaviour and accuracy limits.

## Easy macro mappings

| Easy control | Advanced key | 0% | 100% |
|---|---|---:|---:|
| Tape wear | `tape_wear` | 0 | 0.4 |
| Tape wear | `tape_noise` | 0.02 | 0.08 |
| Tape wear | `dropout_rate` | 0 | 8 |
| Tape wear | `chroma_noise` | 0.006 | 0.035 |
| Colour bleed | `chroma_delay_ns` | 0 | 650 |
| Colour bleed | `chroma_play_bw` | 0.65 | 0.25 |
| Picture wobble | `tb_jitter_ns` | 0 | 140 |
| Picture wobble | `tb_wobble_ns` | 0 | 650 |
| Picture wobble | `tb_skew_us` | 0 | 5 |
| Tracking smears | `track_band` | 0 | 0.8 |
| Tracking smears | `track_smear` | 0 | 1 |
| Tape creases | `wrinkle` | 0 | 0.85 |
| Tape creases | `wrinkle_height` | 4 | 40 |

Apply deck changes playback only. Full presets reset every parameter. Damage buttons affect the whole clip, not timestamped events.

## Input

| Control / key | Help |
|---|---|
| Fit to 4:3 / `aspect` | fit = letterbox/pillarbox, crop = fill 4:3, stretch = ignore aspect Options: fit, crop, stretch. Default: fit. |
| Export fields / `export_fields` | interlaced: normal woven 576-line frame (both fields). 'field 1/2 only': only that field is rendered and every line is doubled -> a progressive, non-interlaced file (no combing, no interlace flags, ~2x faster). The GUI export also follows the 'Field 1/2 only' view selector Options: interlaced, field 1 only, field 2 only. Default: interlaced. |
| Field sampling / `field_mode` | temporal: field 2 is taken 1/50 s after field 1 (real interlace, combing on motion). frame: both fields come from one source frame (like film on PAL) Options: temporal, frame. Default: temporal. |
| Interlace (anti-twitter) filter / `vfilter` | Vertical low-pass before the frame is split into fields Range: 0 … 1; default: 0.25. Type an exact value beside the slider. |
| Brightness / `in_brightness` | Adds brightness before PAL encoding; high values can clip highlights during recording. Range: -0.3 … 0.3; default: 0. Type an exact value beside the slider. |
| Contrast / `in_contrast` | Scales contrast before recording; high contrast can overload the tape's recording range. Range: 0.5 … 1.5; default: 1. Type an exact value beside the slider. |
| Saturation / `in_saturation` | Scales colour before recording; 0 records a monochrome source. Range: 0 … 2; default: 1. Type an exact value beside the slider. |

## PAL encoder

| Control / key | Help |
|---|---|
| Luma bandwidth (MHz) / `enc_luma_bw` | Encoder brightness bandwidth. Lower MHz softens detail before the tape stage. Range: 2 … 6; default: 5. Type an exact value beside the slider. |
| U/V bandwidth (MHz) / `enc_chroma_bw` | Encoder colour bandwidth. Lower MHz spreads colour edges before recording. Range: 0.3 … 2; default: 1.3. Type an exact value beside the slider. |
| Bypass VHS (encoder -> TV only) / `bypass_tape` | Shows pure PAL encode/decode artefacts (cross-colour, dot crawl) Default: off. |

## VHS record (luma FM)

| Control / key | Help |
|---|---|
| Tape speed / `tape_speed` | LP/EP: narrower bandwidth, more noise Options: SP, LP, EP. Default: SP. |
| Record luma bandwidth (MHz) / `rec_luma_bw` | Record brightness low-pass. Lower MHz removes fine detail; tape speed scales this again. Range: 1.5 … 4.5; default: 3.4. Type an exact value beside the slider. |
| Pre-emphasis (dB) / `preemph_db` | Boosts high-frequency brightness before FM; playback applies matching de-emphasis. More can produce edge clipping. Range: 0 … 14; default: 8. Type an exact value beside the slider. |
| White clip (V) / `white_clip` | Upper record-stage clipping voltage after pre-emphasis. Lower values flatten bright edges. Range: 0.7 … 1.3; default: 0.95. Type an exact value beside the slider. |
| Dark clip (V) / `dark_clip` | Lower record-stage clipping voltage. Raising it clips dark excursions and can affect sync. Range: -0.6 … -0.3; default: -0.42. Type an exact value beside the slider. |
| FM carrier at sync tip (MHz) / `fm_sync_mhz` | FM carrier frequency at sync-tip voltage. PAL VHS nominal is 3.8 MHz; changing it alters the recording format. Range: 3 … 4.2; default: 3.8. Type an exact value beside the slider. |
| FM deviation (MHz per volt) / `fm_dev_mhz` | FM frequency change per volt. Nominal 1 MHz/V maps sync to white over 3.8–4.8 MHz. Range: 0.6 … 1.6; default: 1. Type an exact value beside the slider. |

## Tape & head

| Control / key | Help |
|---|---|
| Head/tape RF bandwidth (MHz) / `head_bw` | RF head/tape low-pass bandwidth. Lower MHz suppresses FM sidebands and fine detail. Range: 5 … 8.5; default: 7.2. Type an exact value beside the slider. |
| RF section sample rate / `rf_rate` | 2x = 35.5 MHz (accurate FM sidebands, slower). 1x = 17.7 MHz: ~25% faster render, tiny differences Options: 2x, 1x. Default: 2x. |
| Head/preamp resonance (MHz) / `head_peak_mhz` | Head Q network peak. Service manuals tune VHS heads to ~4.9-5.0 MHz Range: 4.2 … 6; default: 5. Type an exact value beside the slider. |
| Head/preamp resonance gain (dB) / `head_peak_db` | Boosts the upper FM sidebands (4.8 MHz white edges) and their noise Range: 0 … 9; default: 3. Type an exact value beside the slider. |
| Tape/head noise (RF) / `tape_noise` | White noise added to the RF signal, relative to carrier amplitude 1.0 Range: 0 … 0.3; default: 0.033. Type an exact value beside the slider. |
| Tape wear (signal loss) / `tape_wear` | Overall RF level reduction -> more FM noise / sparkles Range: 0 … 1; default: 0. Type an exact value beside the slider. |

## Chroma (colour-under)

| Control / key | Help |
|---|---|
| Colour-under record level (dB re FM) / `cu_level_db` | Burst amplitude of the 627 kHz colour-under relative to the unit FM carrier. Real decks record chroma ~20 dB under the luma FM (2-5 mV vs 25-70 mV at the record amp) Range: -30 … -8; default: -20. Type an exact value beside the slider. |
| Chroma record half-band (MHz) / `chroma_rec_bw` | Colour separation half-band around the PAL subcarrier before colour-under recording. Range: 0.3 … 1.3; default: 0.9. Type an exact value beside the slider. |
| Colour-under bandwidth (MHz) / `chroma_play_bw` | Colour-under playback filter width. Lower MHz softens colour boundaries and reduces colour noise. Range: 0.2 … 1.1; default: 0.55. Type an exact value beside the slider. |
| Chroma noise / `chroma_noise` | Random colour-channel noise. Higher values add coloured speckles and unstable colour detail. Range: 0 … 0.1; default: 0.012. Type an exact value beside the slider. |
| Chroma gain / `chroma_gain` | Playback colour amplitude multiplier; burst regulation and TV decoding also influence visible saturation. Range: 0.3 … 2; default: 1. Type an exact value beside the slider. |
| Chroma ACC (burst level control) / `acc` | Automatic colour control regulates playback burst level. Disable to expose colour level changes from the tape. Default: on. |
| Chroma delay (ns) / `chroma_delay_ns` | Net colour-versus-brightness delay after automatic filter alignment: positive moves colour right, negative left; zero aligns edges. Range: -800 … 800; default: 110. Type an exact value beside the slider. |
| Player colour lock (APC) speed / `apc_speed` | Phase-lock of the colour up-converter to the burst: low = slow PLL, hue wobble from jitter survives Range: 0.02 … 1; default: 0.15. Type an exact value beside the slider. |
| Playback LO phase error (deg) / `lo_phase_err` | Colour playback oscillator phase offset. PAL-D cancels some phase errors; PAL-S reveals more hue error. Range: -90 … 90; default: 0. Type an exact value beside the slider. |
| Colour-under phase sequence / `cu_phase_model` | PAL VHS: head A unchanged, head B delayed 90 degrees each line in colour-under (JVC VTG82063). Legacy reproduces the old common rotation for comparison. Options: PAL VHS, legacy 90deg. Default: PAL VHS. |

## Timebase & mechanics

| Control / key | Help |
|---|---|
| Line jitter (ns rms) / `tb_jitter_ns` | Random horizontal timing error per scan line. Higher nanoseconds make vertical edges shake. Range: 0 … 300; default: 35. Type an exact value beside the slider. |
| Slow wobble (ns) / `tb_wobble_ns` | Slow horizontal timing drift amplitude. Higher values make the picture sway; TV AFC may conceal it. Range: 0 … 1500; default: 120. Type an exact value beside the slider. |
| Wobble rate (Hz) / `tb_wobble_hz` | Rate of the slow horizontal wobble in cycles per second. Range: 0.1 … 15; default: 1.7. Type an exact value beside the slider. |
| Top skew / flagging (us, - left / + right) / `tb_skew_us` | Top-of-field flagging amplitude. Negative bends the top left; positive bends it right. Range: -12 … 12; default: 1.2. Type an exact value beside the slider. |
| Random skew direction per field / `skew_random` | Chooses a new top-skew direction each field rather than retaining a consistent bend. Default: off. |

## Head switching

| Control / key | Help |
|---|---|
| Head-switch snow strength / `hs_residual` | Original-style waveform snow: a soft bright head, correlated grain and a fading tail, passed through the output and TV decoder. Zero disables it. Motion moves the streak, not the picture lines. Range: 0 … 1; default: 0. Type an exact value beside the slider. |
| Snow width (720-raster pixels) / `hs_residual_width_px` | Nominal width/time scale in native 720-raster pixels. Length breathes per field as in the original effect, and filtering creates a soft tail beyond this nominal size. This is not a hard-edged pixel box. Range: 1 … 60; default: 9. Type an exact value beside the slider. |
| Snow height (lines per field) / `hs_residual_height` | One or two scan lines per field for the supplied reference. Each field has independent grain; the woven frame has twice as many interleaved rows. Range: 1 … 4; default: 1. Type an exact value beside the slider. |
| Snow gap to bottom (woven-frame rows) / `hs_residual_bottom_px` | Assumed interpretation of the supplied reference: number of full 576-line woven-frame rows below the snow band. The field grids differ by one row in parity. Independent of RF switch advance. Range: 0 … 80; default: 5. Type an exact value beside the slider. |
| Snow base horizontal position / `hs_residual_x` | Base horizontal start: 0 left, 1 right. Motion and position jitter are added relative to this point. Changes affect both preview and export. Range: 0 … 1; default: 0.12. Type an exact value beside the slider. |
| Snow motion / `hs_residual_motion` | Move the narrow snow while playing or stepping frames. Motion changes snow position only, not picture-line timing or vertical position. Deterministic when seeking/exporting; paused frames stay still. Options: Stationary, Drift, Random jumps, Drift + jitter, Forward/back steps. Default: Forward/back steps. |
| Snow drift (pixels per field) / `hs_residual_speed_px` | Horizontal travel each 1/50-second field in Drift modes. Negative moves left; zero stops steady drift. Bounces at the picture edges without clipping the snow width. Range: -60 … 60; default: 12. Type an exact value beside the slider. |
| Snow position scatter (pixels rms) / `hs_residual_jitter_px` | Random horizontal position changes per field in Random jumps or Drift + jitter. This moves the snow patch, not the image scan lines. Zero disables scatter. Range: 0 … 150; default: 10. Type an exact value beside the slider. |
| Snow sweep (pixels per field line) / `hs_residual_sweep_px` | Horizontal offset for each additional snow line in the same field. Applies to every motion mode; zero aligns the lines vertically. Does not widen any individual streak. Range: -30 … 30; default: 3. Type an exact value beside the slider. |
| Head-switch model / `hs_model` | RF switch: localized RF loss and FM phase mismatch. Legacy overlay: original painted white snow. Off disables head-switch disturbance and masking, not other tape errors. Options: RF switch, legacy overlay, off. Default: RF switch. |
| Switch before vertical sync (H) / `hs_advance` | Nominal PAL VHS 6.5 H before broad vertical sync. One H is 64 us. Larger switches earlier/higher. Existing field timing remains a whole-line approximation. Range: 1 … 20; default: 6.5. Type an exact value beside the slider. |
| RF interruption duration (us) / `hs_gap_us` | Carrier-loss duration at head changeover. The demodulator produces the visible transient; this does not paint a white stripe. Range: 0 … 64; default: 3. Type an exact value beside the slider. |
| RF recovery time constant (us) / `hs_recovery_us` | Exponential RF-envelope recovery after the interruption; larger values spread recovery along the scan line. Range: 0.1 … 64; default: 3. Type an exact value beside the slider. |
| FM phase discontinuity (deg) / `hs_phase_deg` | Incoming-head carrier phase mismatch, opposite signs in the two fields. Produces a localized FM discriminator transient; not a hue control or random line shake. Range: 0 … 180; default: 25. Type an exact value beside the slider. |
| Faulty servo vertical excursion (H) / `hs_servo_lines` | Explicit servo fault: vertical movement of the switch point. Zero for normal decks. Separate from horizontal line jitter and deterministic across seeks. Range: 0 … 90; default: 0. Type an exact value beside the slider. |
| SWP black mask (field lines) / `hs_mask_lines` | Replace the last N active field lines with video black after playback; preserve sync and burst. Hides picture detail, not RF damage. Zero preserves full raster. Range: 0 … 20; default: 0. Type an exact value beside the slider. |
| Head-switch shift (us, - left / + right) / `hs_shift_us` | Horizontal displacement near the bottom head-switch zone. Negative left, positive right. Range: -20 … 20; default: 1. Type an exact value beside the slider. |
| Head-switch shift variation (+- fraction) / `hs_shift_var` | How much the shift size wobbles from frame to frame. 0 = the shift stays exactly at the set value (use together with 'Head-switch line jitter' = 0 for a perfectly steady shift) Range: 0 … 0.5; default: 0. Type an exact value beside the slider. |
| Head-switch shift variation speed (Hz) / `hs_shift_rate` | Speed of the changing head-switch displacement. Requires nonzero shift variation. Range: 0.1 … 12.5; default: 4. Type an exact value beside the slider. |
| Random head-switch direction per field / `hs_random` | Randomizes head-switch displacement direction independently for each field. Default: off. |
| Legacy switch zone (lines) / `hs_lines` | Legacy-overlay mode only: old whole-line zone before the field boundary. RF mode uses fractional switching advance. Range: 1 … 20; default: 7. Type an exact value beside the slider. |
| Head-switch RF loss depth / `hs_noise` | Fractional RF loss at head changeover. Higher values deepen carrier loss; demodulation and tape noise produce the transient. Range: 0 … 1; default: 0.65. Type an exact value beside the slider. |
| Legacy head-switch snow streak / `hs_snow` | Bright snow burst at the start (left) of the head-switch lines that fades out toward the right Range: 0 … 1; default: 0. Type an exact value beside the slider. |
| Head-switch snow height (lines per field) / `hs_snow_lines` | How many scan lines of each field carry the snow burst (the two fields each have their own, so in the woven frame 1 = about 2 neighbouring rows). More lines fade out in strength Range: 1 … 8; default: 1. Type an exact value beside the slider. |
| Head-switch snow length (us) / `hs_snow_us` | Horizontal length of the head-switch snow burst in microseconds; a whole scan line is 64 µs. Range: 2 … 45; default: 16. Type an exact value beside the slider. |
| Head-switch snow drift (us/field, 0 = none) / `hs_snow_speed` | The snow burst moves horizontally from field to field: +7 us/field crosses the picture in ~7 fields (0.15 s) and wraps around. 0 = stays at the left edge Range: -30 … 30; default: 0. Type an exact value beside the slider. |
| Head-switch snow base position (0 left .. 1 right) / `hs_snow_pos` | Base horizontal position of head-switch snow: 0 left, 1 right. Jitter and drift move it around this point. Range: 0 … 1; default: 0.12. Type an exact value beside the slider. |
| Head-switch snow jitter (us rms) / `hs_snow_jitter` | Random left/right jumps of the snow burst, different every field (jitter around the base position) Range: 0 … 40; default: 0. Type an exact value beside the slider. |
| Head-switch line jitter (us rms) / `hs_jitter_us` | Random left/right shake of every line in the head-switch zone Range: 0 … 15; default: 0. Type an exact value beside the slider. |
| Head-switch snow sweep (us/line) / `hs_snow_sweep` | Each following head-switch line starts the streak further to the right, so the snow flicks left to right Range: 0 … 14; default: 3. Type an exact value beside the slider. |

## Dropouts & tracking

| Control / key | Help |
|---|---|
| Dropouts per frame / `dropout_rate` | Expected dropout event density per frame. Higher values create more short RF losses; DOC can hide them. Range: 0 … 40; default: 1.5. Type an exact value beside the slider. |
| Dropout length (us) / `dropout_len_us` | Typical horizontal duration of RF losses. Higher values make longer dropout streaks. Range: 1 … 60; default: 9. Type an exact value beside the slider. |
| Dropout depth / `dropout_depth` | Fractional RF attenuation during a dropout. Near 1 means almost complete signal loss. Range: 0.2 … 1; default: 0.9. Type an exact value beside the slider. |
| Dropout compensator (DOC) / `doc` | Player replaces dropouts with the previous line Default: on. |
| Tracking noise band / `track_band` | Strength of a travelling tracking-error band. Enables the band smear control; 0 disables this band. Range: 0 … 1; default: 0. Type an exact value beside the slider. |
| Tracking knob (- noise at bottom, + at top) / `tracking` | Manual tracking misadjustment. 0 = perfectly tracked. Negative: noise builds up from the bottom of the picture; positive: from the top. Larger /value/ = more of the picture is covered, down to full snow Range: -1 … 1; default: 0. Type an exact value beside the slider. |
| Snow streak density / `snow_streaks` | Long single-line white/black streaks in the noise of lost tracking. 0 = none Range: 0 … 4; default: 1. Type an exact value beside the slider. |
| Snow streak length (us, typical) / `snow_streak_us` | Median streak length in microseconds (64 us = full line); lengths vary around it Range: 1 … 40; default: 9. Type an exact value beside the slider. |
| Sparse streaks over the whole frame (weak tape) / `snow_sparse` | Short white streaks on random lines anywhere in the picture, independent of the tracking band Range: 0 … 4; default: 0. Type an exact value beside the slider. |
| Snow grain coarseness / `snow_grain` | 0 = fine single-pixel noise, 1 = coarse horizontally stretched flecks Range: 0 … 1; default: 0.5. Type an exact value beside the slider. |
| Band speed (lines/frame) / `track_speed` | Vertical speed of the tracking band in field lines per frame; negative reverses its motion. Range: -30 … 30; default: 3. Type an exact value beside the slider. |
| Tracking band line smear/duplication / `track_smear` | Inside the tracking band the head reads the tape at a wandering speed: lines stretch/compress, shift sideways and repeat (long white/grey streaks, colour lost). Needs 'Tracking noise band' > 0 Range: 0 … 1; default: 0.7. Type an exact value beside the slider. |

## Tape wrinkle

| Control / key | Help |
|---|---|
| Travelling wrinkle (white band from the top) / `wr_travel` | A crease band of random height enters at the top, runs down the picture and leaves at the bottom: its lines are duplicated / stretched and go solid white with ragged edges Default: off. |
| Time between wrinkles (frames) / `wr_period` | Spacing between travelling wrinkle events in frames. At 25 fps, 75 frames equals 3 seconds; requires travelling wrinkle enabled. Range: 10 … 500; default: 75. Type an exact value beside the slider. |
| Band height min (field lines) / `wr_hmin` | Minimum random travelling-band height in field lines. Keep no greater than the maximum. Range: 1 … 60; default: 3. Type an exact value beside the slider. |
| Band height max (field lines) / `wr_hmax` | Maximum random travelling-band height in field lines. Keep no smaller than the minimum. Range: 1 … 60; default: 14. Type an exact value beside the slider. |
| Band speed (field lines/frame) / `wr_speed` | Downward travelling wrinkle speed in field lines per frame. Requires travelling wrinkles enabled. Range: 0.5 … 40; default: 6. Type an exact value beside the slider. |
| White bands at once / `wr_count` | Exactly this many white bands are on screen at the same time (each with its own random height) Range: 1 … 6; default: 1. Type an exact value beside the slider. |
| Gap between simultaneous bands (lines) / `wr_gap` | 0 = random positions. Otherwise the bands follow each other at this distance (top to top) Range: 0 … 250; default: 0. Type an exact value beside the slider. |
| Train length with several bands (frames) / `wr_hold` | With 'White bands at once' > 1 the bands run as a train: each band that leaves at the bottom is replaced at the top, so exactly that many bands are on screen, for this many frames Range: 10 … 1000; default: 150. Type an exact value beside the slider. |
| White part height (lines, 0 = whole band) / `wr_white_h` | Size of the solid-white part, starting at the band's first (top) line. The duplicated (repeated) lines keep the size set by 'Band height min/max', so the white can be made smaller or bigger without changing the line duplication Range: 0 … 90; default: 0. Type an exact value beside the slider. |
| Repeated (non-white) lines darkening / `wr_dup_dark` | The repeated lines of the band that are not in the white part are a copy of the line above the band. On a bright picture that copy also looks white; this fades it toward black so only the white part reads as white Range: 0 … 1; default: 0. Type an exact value beside the slider. |
| Band enters at the top with full size / `wr_full_entry` | On: the band is full height from the first picture line (no growing-in at the top, no duplicated white fields of the wrong size). Off: it slides in from above, growing line by line Default: on. |
| Band whiteness / `wr_white` | Brightness of travelling crease bands: 0 preserves repeated picture detail, 1 produces white damage. Range: 0 … 1; default: 0.9. Type an exact value beside the slider. |
| Band horizontal tear (0 = clean line repeat) / `wr_dup` | 0 = the line above the band is repeated unchanged over the band height. Higher adds a random horizontal stretch/offset per line Range: 0 … 1; default: 0. Type an exact value beside the slider. |
| Ragged edges / `wr_ragged` | Irregularity of travelling-band edges. Higher values make broken, uneven crease boundaries. Range: 0 … 1; default: 0.5. Type an exact value beside the slider. |
| Wrinkle severity / `wrinkle` | Creased tape: the head reads a local patch at a wrong, wandering speed (lines stretched/compressed, repeated or skipped, FM carrier shifted -> brightness stripes, chroma lost) plus head-lift dropouts Range: 0 … 1; default: 0. Type an exact value beside the slider. |
| Wrinkle bands (usual wrinkle) / `wrinkle_count` | Number of usual (stretch/skip) wrinkle bands in the picture at the same time Range: 1 … 6; default: 1. Type an exact value beside the slider. |
| Gap between wrinkle bands (lines, 0 = spread evenly) / `wrinkle_gap` | Spacing between ordinary wrinkle bands. Zero spreads them evenly; requires more than one band. Range: 0 … 250; default: 0. Type an exact value beside the slider. |
| Wrinkle height (lines) / `wrinkle_height` | Height of the ordinary speed-error crease zone in field lines; requires nonzero wrinkle severity. Range: 4 … 90; default: 24. Type an exact value beside the slider. |
| Wrinkle position (0 top .. 1 bottom) / `wrinkle_pos` | Vertical centre of the ordinary crease: 0 top, 1 bottom; drift moves it over time. Range: 0 … 1; default: 0.6. Type an exact value beside the slider. |
| Wrinkle drift (lines/frame) / `wrinkle_drift` | Ordinary crease vertical drift per frame in field lines. Negative moves upward; zero keeps its position. Range: -20 … 20; default: 0. Type an exact value beside the slider. |
| Vertical stretch (line repeat factor) / `wrinkle_stretch` | 2.5 = each source line is shown ~2.5 times in the middle of the wrinkle (then lines are skipped to catch up) Range: 1 … 6; default: 2.5. Type an exact value beside the slider. |
| Read-speed error (+- %) / `wrinkle_speed_pct` | Tape speed error past the head. +10 % raises the FM carrier 10 % = ~+0.43 V brightness shift Range: 0 … 60; default: 12. Type an exact value beside the slider. |
| Line start scatter (us) / `wrinkle_shift_us` | Random horizontal line-start scatter inside the ordinary crease. Higher microseconds add stronger tears. Range: 0 … 30; default: 6. Type an exact value beside the slider. |

## VHS playback

| Control / key | Help |
|---|---|
| Playback luma bandwidth (MHz) / `play_luma_bw` | Playback brightness low-pass. Lower MHz makes the recorded picture softer. Range: 1.5 … 5; default: 3.6. Type an exact value beside the slider. |
| Player sharpness (detail boost) / `sharpen` | High-frequency detail boost after playback. Higher values add edge halos and emphasize tape noise. Range: 0 … 1.5; default: 0.35. Type an exact value beside the slider. |

## RCA output

| Control / key | Help |
|---|---|
| Output level / `out_gain` | The TV AGC normalises this, but scope shows the level Range: 0.5 … 1.5; default: 1. Type an exact value beside the slider. |
| Cable bandwidth (MHz) / `out_bw` | Composite cable low-pass bandwidth. Lower MHz attenuates fine detail and can damage the PAL colour carrier. Range: 3 … 8.5; default: 6.5. Type an exact value beside the slider. |
| Output noise / `out_noise` | Noise added after the VCR at the composite output, independent of tape wear. Range: 0 … 0.1; default: 0.008. Type an exact value beside the slider. |
| Cable reflection (ghost) / `ghost` | Strength of a delayed composite-signal reflection. Zero disables cable ghosting. Range: 0 … 0.5; default: 0. Type an exact value beside the slider. |
| Ghost delay (ns) / `ghost_ns` | Delay of the reflected signal. Higher values move the ghost farther right; requires reflection strength above zero. Range: 100 … 3000; default: 450. Type an exact value beside the slider. |

## TV decoder

| Control / key | Help |
|---|---|
| Colour decoder / `tv_decoder` | PAL-D = delay-line decoder, PAL-S = simple (hue errors show) Options: PAL-D, PAL-S. Default: PAL-D. |
| Horizontal lock (AFC) / `tv_afc` | 1.0 = ideal time-base corrector (wobble hidden); low = jitter visible Range: 0.02 … 1; default: 0.35. Type an exact value beside the slider. |
| Colour burst lock speed / `tv_apc` | TV colour burst-lock response speed. Low values retain more slow phase error; high follows the burst faster. Range: 0.05 … 1; default: 0.5. Type an exact value beside the slider. |
| Luma bandwidth (MHz) / `tv_luma_bw` | TV brightness decoding bandwidth. Lower MHz softens detail at the final display stage. Range: 2.5 … 6; default: 5. Type an exact value beside the slider. |
| Chroma bandwidth (MHz) / `tv_chroma_bw` | TV decoded-colour low-pass bandwidth. Lower MHz makes colour edges softer. Range: 0.4 … 2; default: 1.1. Type an exact value beside the slider. |
| Brightness / `tv_brightness` | Final displayed black-level offset after decoding; does not change the recorded signal. Range: -0.3 … 0.3; default: 0. Type an exact value beside the slider. |
| Contrast / `tv_contrast` | Final displayed brightness contrast after decoding; high settings can clip highlights. Range: 0.5 … 1.5; default: 1. Type an exact value beside the slider. |
| Saturation / `tv_saturation` | Final displayed colour saturation. Zero displays monochrome without changing tape recording. Range: 0 … 2; default: 1. Type an exact value beside the slider. |
| Hue (deg) / `tv_hue` | Final colour rotation in degrees, after PAL decoding. This is a display adjustment. Range: -45 … 45; default: 0. Type an exact value beside the slider. |

## Misc

| Control / key | Help |
|---|---|
| Noise seed / `seed` | Deterministic noise/damage seed. Same seed, frame and parameters reproduce the same damage when seeking or exporting. Range: 0 … 9999; default: 1. Type an exact value beside the slider. |
