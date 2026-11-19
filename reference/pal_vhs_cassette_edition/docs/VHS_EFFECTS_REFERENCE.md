# VHS effects and source notes — cassette edition 2

## What was inspected

The AV Artifact Atlas pages below were read, its two butterfly playback stills
were visually inspected, and three linked example videos were downloaded into
temporary analysis space. Decoded frames at 15%, 50% and 85% of each clip were
inspected. Original reference media is **not redistributed** in this release.

| Example | Source / playback | Decoded derivative properties |
|---|---|---|
| Normal head switch | [Atlas](https://www.avartifactatlas.com/artifacts/head_switching_noise.html), [video](https://archive.org/details/AVAAHeadSwitchNYU) | 480×360, 102 frames, approximately 30.25 fps |
| Faulty recorded servo | [video](https://archive.org/details/test-clip-xcms-d-9lu-xni) | 490×360, 123 frames, approximately 29.97 fps |
| Tracking | [Atlas](https://www.avartifactatlas.com/artifacts/tracking_error.html), [video](https://archive.org/details/tracking_201702) | 640×480, 441 frames, approximately 29.97 fps |
| Ordinary-player butterfly still | [original still](https://www.avartifactatlas.com/images/HeadSwitch_Butterfly_SLV-779HF_Sharp1_XCard.jpg) | 720×480; narrow bottom disturbance visible |
| Professional-player butterfly still | [original still](https://www.avartifactatlas.com/images/HeadSwitch_Butterfly_BR-S525U_VC500.jpg) | 720×480; less visible bottom disturbance; capture framing differs |

The normal video has a thin bottom disturbance while the rest of the image is
readable. The servo example shows a much higher horizontal tear and displacement.
The tracking example illustrates another failure family and must not be treated
as a normal head-switch pattern. These observations are qualitative: the files
are compressed derivatives with rescaling and unknown processing. Their frame
rates and the 480-line stills do not establish a PAL field-by-field calibration.

## Artifact families and the model

| Artifact | Physical interpretation / source | Relevant controls |
|---|---|---|
| Head switching | Head changeover near the end of a field; distinguish RF interruption, stable displacement, and explicit servo faults. [Atlas](https://www.avartifactatlas.com/artifacts/head_switching_noise.html) | `hs_model`, `hs_advance`, `hs_gap_us`, `hs_recovery_us`, `hs_phase_deg`, `hs_noise`, `hs_shift_us` |
| Recorded servo fault | A vertically moving switch boundary can originate in the recording. It is not the normal signature of a cheap player. [Atlas](https://www.avartifactatlas.com/artifacts/head_switching_noise.html) | `hs_servo_lines`; separate fault demonstration |
| Tracking error | The playback head does not follow the recorded track. [Atlas](https://www.avartifactatlas.com/artifacts/tracking_error.html) | `tracking`, `track_band`, `track_smear` |
| RF dropout | Brief RF loss may become a short black/white disturbance or a compensated line. [Atlas](https://www.avartifactatlas.com/artifacts/video_dropout.html) | `dropout_rate`, `dropout_len_us`, `dropout_depth`, `doc` |
| Time-base error | Timing variation can bend or tear picture structure. [Atlas](https://www.avartifactatlas.com/artifacts/time_base_error.html) | `tb_jitter_ns`, `tb_wobble_ns`, `tb_skew_us`, `tv_afc` |
| Skew / flagging | A bend at picture edges; do not add it indiscriminately as noise. [Atlas](https://www.avartifactatlas.com/artifacts/skew_error.html) | `tb_skew_us`, `hs_shift_us` |
| Colour noise | Coloured specks and traces; not identical to luminance grain. [Atlas](https://www.avartifactatlas.com/artifacts/chrominance_noise.html) | `chroma_noise`, `chroma_gain` |
| Y/C misalignment | Colour edges displaced relative to brightness edges. [Atlas](https://www.avartifactatlas.com/artifacts/yc_delay_error.html) | `chroma_delay_ns`; zero aligns modeled filter delays |
| Low RF | Reduced off-tape signal can have several causes, not just age. [Atlas](https://www.avartifactatlas.com/artifacts/low_rf.html) | `tape_wear`, `tape_noise`; simplified combined head/tape model |

## Technical anchors and implementation changes

[JVC VTG82063, section 1](https://decode-orc.github.io/analogue-video-specifications/vhs/JVC-Video-Technical-Guide-VTG82063/section-1/)
specifies nominal PAL VHS FM 3.8–4.8 MHz and colour-under at
626.953 kHz. It describes unchanged phase for head channel A and a 90-degree
per-line delay for channel B, reversed during playback conversion. This replaces
the old identical per-line rotation on both heads. The implementation's high-side
LO sign is chosen to produce that colour-under delay. Burst-loss and group-delay
calibration now run separately for the two phase sequences.

The RF analytic signal and discriminator now retain f64 precision. The FM record
tap remains the ideal recorded carrier; the incoming-head phase discontinuity is
applied to playback RF, leaving colour-under independent. A local RF-envelope
loss and exponential recovery go through the existing noise, filters and ideal
FM discriminator. The RF interruption is separate from the optional snow waveform. RF-mode snow
now restores the original smoothed luma streak before output/TV filtering; the
legacy branch remains available. Neither is a calibrated demodulator model.

[JVC HR-XV/HR-XVS service manual, adjustment 4.3.1.1](https://rcaudio.rclabs.com.br/library/docs/Schematics%2C%20Service%20Manuals%20and%20Catalogs/Jvc/Jvc-HRXV-31-EX-Service-Manual.pdf)
lists 6.5±0.5 H for the specified VHS models and 7.5±0.5 H for its S-VHS models.
Those are model-specific settings, not a ranking of player quality. The release
uses 6.5 H as its nominal VHS point. On the existing simplified grid the next
broad vertical-sync pulse starts at next-field +2 lines, so the changeover is at
`field_length + 2 - hs_advance`. Fractional-line positioning is supported; true
half-line field timing still is not.

## Playback profiles

Every profile has **zero random head-switch line jitter**, zero shift variation,
and zero legacy snow-position jitter. The fault profile moves the boundary
vertically through a separate control. The profile numbers below are engineering
choices informed by the references, not measurements of the named machine classes.

| Profile | Advance (H) | RF gap (µs) | Recovery (µs) | RF loss | FM phase mismatch | Stable shift (µs) | Output treatment |
|---|---:|---:|---:|---:|---:|---:|---|
| Budget 2-head, rough alignment | 8 | 1 | .3 | .8 | 40° | 4 | Uncorrected, DOC off |
| Domestic 2-head, aligned | 6.5 | 5 | 5 | .65 | 50° | 1 | Ordinary horizontal lock, DOC on |
| Domestic 4-head, aligned | 6.5 | 2.5 | 3 | .4 | 30° | .5 | Smaller modeled mismatch, DOC on |
| High-end 6+ head S-VHS-capable, playing VHS | 6.5 | .8 | 1.2 | .18 | 12° | .15 | Idealized horizontal correction |
| Professional, later switch | 5 | .4 | .8 | .12 | 8° | .1 | 1.5 H later than nominal, idealized correction |
| Professional, black mask | 6.5 | .8 | 1.2 | .18 | 12° | .15 | Last 4 active field lines black, idealized correction |
| Recorded-servo fault | 6.5 ±35 | 35 | 20 | .98 | 120° | 4 | Explicit periodic vertical fault, DOC off |

The professional output choices are separate: later changeover reduces how much
disturbance falls in the active raster; masking replaces bottom picture samples
with black. Neither reconstructs missing content. Atlas describes both approaches,
and overscan can conceal artifacts without changing the signal itself. The +1.5 H
profile is a generic adaptation, not an exact PAL emulation of the cited JVC units.

Head count is deliberately not a DSP parameter. For example, the
[Philips VR550 manufacturer brochure](https://www.clasohlson.com/medias/sys_master/9542829113374.pdf)
advertises six heads but specifies four video and two FM-audio heads. Head count,
tape speed, alignment, output processing and tape condition are separate variables.
All new profiles play **standard VHS**; S-VHS-capable deck does not mean S-VHS
recording. Actual S-VHS FM 5.4–7 MHz and a proper Y/C recording path are not added.

## Using the update

Choose a full `Deck / ...` preset for an isolated starting point. In Easy mode,
**Apply deck** changes playback controls only, retaining tape wear, wrinkles,
recording speed and source adjustments; Undo reverses the deck-button action too.
Selecting a dropdown item alone does not apply it. Use Advanced → Head switching
to adjust individual values. Legacy-only controls are hidden in RF mode.

Existing saved JSON is respected. If an old file explicitly contains
`hs_jitter_us: 2.5`, loading it still restores that value. Apply a new preset or
deck profile, or set the control to zero, to remove it. No silent migration changes
an intentionally hand-tuned file.

## Accuracy limits and next measurements

This is a better-grounded model, not a measured deck emulator. Remaining limits:
whole-line vertical structure, ideal analytic FM discrimination rather than a
particular PLL, post-demodulated timebase displacement, no adjacent-track azimuth
crosstalk or actual 2H playback chroma comb, and simplified RF head transfer/noise.
The legacy wrinkle/snow effects still contain artistic overlays.

Next calibration needs raw/full-raster PAL SP and LP captures and ideally RF taps:
known chart and deck, field order, capture-window start, overscan, TBC/DOC state,
switch point, RF envelope, phase mismatch, and line-by-line displacement. Fit these
independently. Do not equate consumer versus professional capture-card framing
with a measured improvement in the VCR itself.

## Follow-up: user-specified residual size

The later pixel-width clarification is implemented in RESIDUAL_REFERENCE_UPDATE.md.
It adds a professional narrow-residual profile without replacing later-switch or
black-mask alternatives. The RF timing table above still describes the RF path;
nominal snow duration and position are controlled separately. See that document
for the restored liquid waveform and why width is not an exact RGB box.
