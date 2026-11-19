# GStreamer Preview Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for independent preview and interface modules; root integrates the media pipeline and verifies all results.

**Goal:** Replace preview decoding with GStreamer and remove expensive RF simulation from the default interactive path, retaining an explicit exact mode.

**Architecture:** Shared Params feed two render modes. A persistent in-process GStreamer source supplies fields to a bounded worker. Fast mode uses a deterministic line/pixel approximation, exact mode retains Engine and real scope taps. Export remains exact.

**Tech stack:** Existing Rust/eframe, gstreamer/gstreamer-app/gstreamer-video bindings, official x64 GStreamer runtime/SDK.

## Global constraints

- Fast preview is explicitly approximate; exporting always uses the existing exact signal engine.
- Decode video in process with GStreamer; no gst-launch subprocess wrapper or silent FFmpeg fallback.
- Preserve 720×576 and PAL field modes, aspect settings, native settings/presets and deterministic random seeking.
- Bound all queues/caches; retain latest preview requests and discard stale results.
- Report real measurements and failures; preserve original output files on export failure.

## Task 1 — decoding

- [x] Add optional desktop GStreamer dependencies and obtain matching Windows runtime/development files locally.
- [x] Write integration tests using synthetic videos for decoded field dimensions, sequential/random seek agreement, frame mode, and errors.
- [x] Implement src/gst_media.rs with persistent pipeline, bounded appsink, timeout/error/EOS handling, negotiated mapping and cleanup to Null.
- [x] Validate with a real runtime and ship a reproducible local build/runtime configuration.

## Task 2 — fast renderer

- [x] Write tests/preview.rs for validation, field output, repeatability, monochrome display and parameter effects.
- [x] Implement src/preview.rs using row-local filters and deterministic per-frame seeds; render into reusable-size output buffers and never construct Engine.
- [x] Measure rendering throughput separately from decode, then tune based on actual bottlenecks.

## Task 3 — interface

- [x] Add Fast / Exact preview selection, default Fast, with concise accuracy descriptions.
- [x] Use GstVideoSource in the existing bounded preview worker; invoke the fast renderer or cached Engine according to the selected mode.
- [x] Allow real scope taps in Exact only; changing preview mode invalidates outstanding jobs.
- [x] Drive playback from elapsed time and repaint frequently enough for 25 fps; stop at end and preserve stepping/scrubbing.

## Task 4 — verification and delivery

- [x] Run all original Rust tests, new preview tests and GStreamer integration tests.
- [x] Measure sustained preview decode+processing p50/p95 and verify scopes/export remain exact.
- [x] Build/package updated executable and source, document runtime and measured limitations.
