# Validation: waveform snow restoration, 15 November 2026

51 regression tests pass on Windows, including offscreen Qt controls and a real
spawned-worker termination followed by fallback rendering. The suite covers
schema/JSON/help, presets, snow controls, movement, deck application, PAL phase,
RF envelope and switching, sync-preserving masking, and renderer failure paths.

New waveform checks cover selected field-line height, five-row bottom placement,
deterministic but evolving grain and shape, bright-head/tail decay, nominal-width
duration, bypass/Off/legacy/mask precedence, and snow appearing in luma-demod,
composite-output taps and decoded RGB. Exact rectangular RGB support is no longer
an acceptance criterion.

All 15 presets were rendered through the full 720x576 DSP pipeline. Dimension,
finite-output, image-variation and deterministic re-render checks pass. Logs are
`validation/unit_tests.txt` and `validation/render_smoke.txt`.

`liquid_snow_detail.png` shows enlarged bottom crops from three current full DSP
renders. `snow_motion.gif` shows 20 complete rendered frames cropped afterward,
with field-varying grain, shape and position. These use a synthetic dark source.
They are visual diagnostics, not measured matches to a particular VCR.

Earlier Easy/Advanced screenshots and all-preset/head-switch comparisons remain
as historical GUI/profile checks. They predate this shape restoration. Use the
liquid detail image and new GIF for the current snow appearance.

Earlier four-frame process/thread FFmpeg exports had identical decoded checksums;
their videos, checksum files and interlaced/progressive FFprobe reports remain.
The export implementation was unchanged by this snow restoration. Those prior
exports were not regenerated for the current visual effect.

No updated frozen Windows EXE has been built or launched for this revision.
Rebuild on the target machine. Native HiDPI, sustained playback, long-run audio
sync and physical mouse interaction remain target-machine acceptance checks.
The original waveform shape is restored, but no deck-specific RF fitting was
performed. Whole-line timing, ideal FM discrimination, simplified head response
and artistic snow/timebase effects remain model limitations.

Forward/back step tests verify exact 3:1 frame displacements, independent counts
and fractional step distances, field parity, seeking and reflected bounds. Qt
tests edit all four new controls. The motion GIF now uses the 3:1 step mode.
