# Native Rust PAL VHS Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement independent modules with review, followed by integration verification.

**Goal:** Deliver a runnable native Rust desktop app and offline CLI for the supplied PAL/VHS simulator.

**Architecture:** One library and binary, divided by model, signal, scheduling and media boundaries. The original Python archive stays under reference/ and is never invoked by the released application.

**Tech Stack:** Rust stable, serde/serde_json, eframe/egui, clap, rustfft, native file dialogs, FFmpeg subprocesses.

## Global Constraints

- Runtime must not require Python.
- Output is 720×576 at 25 frames/sec, top-field-first for woven output, progressive for selected-field output, display aspect 4:3.
- Preserve original parameter names and bundled presets; preserve unknown imported keys.
- Use explicit native RNG model version; do not assert NumPy seed parity.
- Preserve existing destination files on export failure/cancellation.
- Keep GUI rendering asynchronous and queues bounded.

### Task 1: Model and migrated data

Files: src/model.rs, assets/schema.json, assets/presets.json, tests/model.rs.
Consume reference params.py, experience.py, headswitch.py. Produce Params and metadata APIs from the design contract. Write tests before implementation for defaults, validation, legacy snow mode, preset reset versus deck partial update, macros and JSON round trips. Generate data offline; bundle it with include_str! for Python-free runtime. Run cargo test --test model.

### Task 2: Signal engine and DSP

Files: src/dsp.rs, src/signal.rs, src/signal/*.rs, tests/signal.rs.
Consume Params and packed 720×288 RGB fields. Produce Engine and FieldOutput from the design contract. Port the sampled PAL/VHS path from reference modules rather than replacing it with an RGB filter. Test timing, filter DC state, interpolation, FM carrier mapping, phase sequencing, switch envelope and render determinism. Run cargo test --test signal. Document numerical differences and unsupported details precisely.

### Task 3: Native interface and scheduling

Files: src/gui.rs, src/renderer.rs, tests/renderer.rs.
Consume Params and Engine. Produce gui::run(initial_video:Option<PathBuf>, params:Params, workers:usize)->Result<(),String>. Implement Easy/Advanced UI, complete parameter controls, cassette illustration, preview, playback/seeking, scopes and error/retry behavior. A bounded worker uses generation IDs to discard stale preview jobs. Write weaving, selected-field and generation tests, then implement. Run cargo test --test renderer and compile the GUI.

### Task 4: Media and CLI integration

Files: Cargo.toml, src/lib.rs, src/main.rs, src/media.rs, tests/media.rs, README.md, build_windows.ps1.
Produce probe/decode/export FFmpeg APIs and CLI equivalents for list params, presets, overrides, start/max frames, worker count, encoding settings and audio. Write temporal sampling, safe destination and argument tests first. Implement bounded encoding with cooperative cancellation, error propagation and subprocess cleanup. Run cargo test, cargo build --release, short export, FFprobe assertions and reference comparisons. Fix integration defects before completion.

### Task 5: Review and delivery

Review code against the approved scope and reference controls. Resolve material defects. Record actual tests and fidelity limits in docs/VALIDATION.md. Deliver source, lockfile, build instructions and a tested Windows executable when toolchain availability permits.

## Execution record

- [x] Migrate 136 controls, 30 presets, 8 deck profiles and 5 macros.
- [x] Port sampled DSP/PAL/VHS path and reference fixtures.
- [x] Implement native cassette GUI, preview worker, scopes and field renderer.
- [x] Implement media/CLI, safe output replacement and cancellation.
- [x] Pass 31 Rust tests and build the optimized Windows application.
- [x] Verify FFprobe export flags, audio presence and one/two-worker decoded-frame equality.
- [x] Inspect the running desktop app; correct search expansion and restore keyboard shortcuts.
- [x] Document measured numerical differences and validation boundaries.
