# Accurate preview patch notes

This source archive is **not** a rebuilt Windows binary. It is based on `PAL-VHS-Rust-source-0.2.zip` and contains the modified Rust source, regression tests and documentation. `PAL-VHS-GStreamer-0.2.zip` is a previously built portable runtime; its `PAL-VHS.exe` is the old version until you rebuild.

## Key changes

1. Preview uses the **same** PAL/VHS RF pipeline as export; the independent approximate renderer and Fast/Exact GUI mode have been removed.
2. Both fields compute in parallel from a single thread-safe, read-only Engine and are woven exactly as export.
3. PAL basis tables and templates, FFT plans and deck colour-under phase vectors are reused; an 8-frame final RGB cache speeds repeated seeking.
4. UI displays observed milliseconds per full-RF frame. The 25 fps timeline clock is not falsely advertised as achieved throughput.
5. Regression tests compare all pixel values (and signal taps) to the export renderer using identical input fields.

## Build on Windows

Put this archive's `Cargo.toml`, `src/`, `assets/`, etc. in your project source root, not under `dist`. If a GStreamer development SDK is already configured as with the original 0.2 build, run:

```powershell
cargo test --release --locked --no-default-features --test preview
cargo test --release --locked --test gst_media
.\build_windows.ps1
```

The script defaults to `dist\GStreamer\PAL-VHS.exe`. Retain the old GStreamer runtime directories. Install GStreamer development libraries and matching Rust host toolchain if they are not already present.

## Performance constraint

Exact full RF processing previously measured about 0.45 fps with one export worker on the developer's host. This patch removes duplicated initialization and parallelizes the two fields, but **real-time 25 fps has not been demonstrated**. Achieving 25 fps without a lower-fidelity algorithm likely requires further DSP profiling, allocation reduction, vectorization and/or GPU compute on the target hardware. The new benchmark targets a 40 ms complete-frame budget and reports actual timings instead of reporting the discontinued approximate-preview result.

## Test status

Static source edits completed; compilation and runtime benchmarks were unavailable in the current sandbox (no Rust toolchain and no accessible Windows/GStreamer build environment). Do not treat this archive as a verified binary release.
