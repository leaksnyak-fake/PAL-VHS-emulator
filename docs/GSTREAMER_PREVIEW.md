# GStreamer preview — full-signal accuracy update

## Changed behavior

The earlier 0.2 program used a separate f32 pixel/scanline approximation for its default Fast mode. This update removes it from the active application and tests. There is no Fast/Exact selection: preview always uses `signal::Engine::render_field`, the same code as offline export. The signal scope taps are genuine RF waveform taps.

### Performance-preserving changes

- Top and bottom PAL fields render in parallel with `std::thread::scope` on one immutable shared `Engine`, then use exactly the export field-weaving method.
- The eight PAL carrier basis tables are constructed once (`OnceLock<Arc<Basis>>`) and shared by engines/workers. The decoder's calibration references one of these same tables.
- The deck precomputes its colour-under carrier phase vectors per field for each settings configuration; the expressions are unchanged.
- FFT forward/inverse plans are cached in thread-local `FftPlanner<f64>`, so repeated Hilbert transforms do not re-plan.
- PAL line blanking/sync templates and burst envelope are built once.
- Eight fully rendered RGB frames are retained in a bounded LRU. Waveform taps are never cached; a request for scopes triggers a genuine signal render.
- The GStreamer decoder pipeline and bounded 16-frame decode cache are unchanged. On changing the source path or settings, the exact-effect cache is discarded.
- The UI shows measured RF render milliseconds rather than claiming that 25 fps presentation was achieved.

## Accuracy limits

Preview and export produce the same output **for identical 720×288 RGB input fields, frame index, field mode, and parameter set**. A new regression test compares full RGB frames and signal taps against `renderer::render_frame`. GStreamer and FFmpeg do not necessarily supply pixel-identical field buffers because their source decoding and scaling differ. This update does not make any claim of physical VHS calibration beyond the existing signal model.

## Speed and verification

The prior Windows baseline (before this update) was 9.093 s for 4 full-RF export frames with one worker, approximately 0.45 fps, including I/O. The prior 29.68 ms median for Fast preview was for the *discarded approximation* and does not apply to this version. Two-core field parallelism and caching reduce repeated work but do not establish that the full RF pipeline meets a 40 ms budget for 25 fps. Those results must be measured; no new timings have been collected in this environment because Rust/GStreamer compilation is unavailable here.

On a Windows machine with a Rust toolchain, GStreamer SDK, and FFmpeg/FFprobe in PATH, run:

```powershell
cargo test --release --locked --no-default-features --test preview -- --nocapture
cargo test --release --locked --test gst_media -- --nocapture
cargo test --release --locked --no-default-features --test preview -- --ignored --nocapture
cargo test --release --locked --test gst_media -- --ignored --nocapture --test-threads=1
.\build_windows.ps1
```

The two ignored tests print times (ms/frame) without asserting an unverified 25 fps throughput claim. For an end-to-end real-time guarantee, instrument GStreamer decoding, DSP, texture upload, and the display swap/presentation timing on the actual device. Avoid parallel compilation or other heavy background CPU loads during measurements.

## Distribution

The source update cannot patch an existing Windows executable. Rebuild `PAL-VHS.exe` and copy it over the executable in the existing GStreamer `dist` directory, leaving the original DLL, `lib`, and `libexec` runtime directories intact. The supplied Windows ZIP contains runtime binaries, not a Rust compiler. Offline `--no-default-features` builds continue to use the exact export engine.
