# Native Rust validation — 16 November 2026

This document records the 0.1 exact-signal baseline. Version 0.2's GStreamer preview, 42-test suite and performance measurements are documented in [GSTREAMER_PREVIEW.md](GSTREAMER_PREVIEW.md).

## Build and tests

Validated on this Windows x86-64 host with Rust 1.100.0 (GNU target) and the installed FFmpeg/FFprobe. `cargo build --release --locked --offline` compiled the native desktop and CLI. `cargo test --offline --no-default-features -- --nocapture` passed all 31 tests: 5 internal signal/process tests, 10 signal integration tests, 5 model tests, 4 renderer tests, 4 media argument/timing tests and 3 real FFmpeg integration tests.

The preserved Python project's 24 head-switch regression tests also passed using reference-only Python dependencies. These dependencies are not used by the Rust application or required for the Rust fixture tests.

## Numerical comparison

`tests/fixtures/generate_signal_reference.py` generates the reference data with the supplied Python engine, NumPy 2.5.5, SciPy 1.18.1 and OpenCV 5.0.0. The corpus uses full-height, eight-colour bars, noiseless settings, disabled head switching, both top/bottom fields, and both RF sample rates. All 622,080 RGB channel values are compared in each case.

| Case | Maximum absolute channel error | Mean absolute channel error | RMS channel error |
| --- | ---: | ---: | ---: |
| 1× RF, top field | 1 | 0.001315 | 0.036262 |
| 1× RF, bottom field | 1 | 0.001349 | 0.036725 |
| 2× RF, top field | 1 | 0.001392 | 0.037311 |
| 2× RF, bottom field | 1 | 0.001477 | 0.038436 |

No channel differs by more than one 8-bit code in these four fixtures. This is evidence for this corpus, not a claim of pixel parity for arbitrary images, settings or damage.

Tests separately check six filter shapes and polyphase resampling against SciPy fixtures; group delay against SciPy within 1e-10 samples for three test filters; FM sync/white carrier mapping; per-head burst/group-delay calibration; RF switch geometry at both rates; head-switch snow coordinates and masking; deterministic travelling crease scheduling; unchanged record taps under playback phase changes; finite output with simultaneous severe damage; and identical native fields after random seeking.

The comparison identified and corrected an exact-length versus padded Hilbert-transform difference in calibration. Filter group delay uses the analytic SOS derivative rather than finite phase differences. Native f64 scope taps are retained instead of the Python renderer's float16 transfer representation.

## Media/export checks

A synthetic 50 fps source with AAC audio was exported to four-frame H.264 MP4 files through the release binary. FFprobe confirmed:

- 720×576 stored dimensions, 25/1 fps, 16:15 sample aspect and 4:3 display aspect.
- `field_order=tt` for woven top-field-first export.
- `field_order=progressive` for line-doubled field-2 export, including a nonzero start frame.
- Audio is present on the enabled export and absent with `--no-audio`.
- All four decoded frame MD5 hashes match between one-worker and two-worker exports using the same preset.

The real media regression tests also verify sequential-versus-random field equality at 30000/1001 source fps, correct fitting of 720×576 SAR16:15 input, and preservation of an existing destination when an export is cancelled after its first frame. A subprocess test verifies cancellation terminates a continuously running FFmpeg process within three seconds. Destination replacement happens only after the encoder finishes successfully.

Audio is stream-copied; the four-frame AAC test retained packet-boundary duration 0.170667 seconds alongside 0.160000 seconds of video. No audio effects or resampling are applied. Unsupported codec/container combinations produce an encoder error and preserve the old destination.

## Desktop check

Opened the release app with the synthetic clip and visually inspected Easy mode, the cassette panel, Advanced groups, the 4:3 preview, waveform/spectrum scopes, timeline/playback and export options. Search revealed a collapsed-results usability defect; matching groups now open while a search is active. Space controls playback, Left/Right step fields' woven frames, and Ctrl+O opens a video. Rendering runs on the preview worker and displays a pending-frame indicator.

## Boundaries

- Native deterministic random model is **native-v1** (SplitMix64, Box-Muller normal sampling and native event generation). NumPy seeds do not give identical native noise or damage. Native seeking and worker-count determinism are tested.
- RGB resizing and floating-point evaluation use native/FFmpeg implementations rather than OpenCV throughout; broader material and parameter combinations need additional reference captures.
- The reference's whole-line vertical timing and model-based deck approximations are preserved. This is not calibration against a physical deck.
- Correct random FFmpeg seeking currently decodes from the beginning to preserve the global frame-sampling phase; long clips can seek slowly. Decoder and encoder pipes have cancellation watchdogs; initial FFprobe inspection does not.
- Audio stream copy requires a compatible output container. FFmpeg must supply libx264 and is installed separately.
- No real-time rendering or speedup claim is made. The short concurrent export smoke tests are correctness checks, not controlled performance benchmarks.
- The Windows build and the checked workflows were exercised here; Linux/macOS packaging and assistive-technology navigation have not been validated.
