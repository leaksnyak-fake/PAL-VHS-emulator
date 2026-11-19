# Native Rust PAL VHS application

The user approved a full native rewrite on 2026-11-16. The attached Python archive is reference material, including its migration suggestions; it does not override the approved native application scope.

## Scope

Preserve the Easy and Advanced control workflows, complete parameter schema and existing JSON presets, PAL composite and VHS RF simulation, preview, scopes, seeking, deterministic clip-wide tape damage, CLI export, and unchanged-source audio passthrough where supported by the output container. The Rust application must run without Python. Preserve the original source under reference/ for comparison.

## Architecture

A Rust package exposes model, DSP, signal, renderer and media modules; an eframe/egui desktop application and clap CLI share them. FFmpeg/FFprobe remain external subprocesses. Parameter descriptions and preset data are migrated to bundled JSON, with Rust validating values and preserving unknown imported keys. The signal path uses f64 buffers and includes PAL encoding, luma FM and colour-under record/playback, tape damage, head switching, output filtering and television decoding. Keep CPU rendering off the GUI thread and bound outstanding requests. Frame-local randomness has an explicit native model version rather than claiming NumPy RNG parity.

## Interface contracts

`model::Params`: Default + Clone, `number(&str)->f64`, `boolean(&str)->bool`, `choice(&str)->&str`, `set(&str, serde_json::Value)->Result<(),String>`, JSON load/save, preset and macro application. Public specs describe all parameter metadata. Defaults and migrated keys retain original names.

`signal::Engine::new(Params) -> Result<Engine,String>`; `render_field(&mut self, rgb:&[u8], fi:usize, frame_idx:u64, want_taps:bool)->Result<FieldOutput,String>`. RGB input/output is packed 720×288×3. `FieldOutput { rgb:Vec<u8>, taps:BTreeMap<String,Vec<f64>> }`. `signal::WIDTH=720`, `HEIGHT=576`, `FIELD_HEIGHT=288`.

`renderer` weaves fields or line-doubles a selected field. `media` samples input video at 50 temporal fields/sec (or 25 whole frames/sec), fits 4:3 with 16:15 output SAR, and exports 720×576 at 25 fps. Interlaced output is top-field-first; single-field output is progressive. Export writes beside the destination to a temporary file and only replaces it on success; cancellation preserves existing output.

## User interface

Maintain a cassette-inspired dark interface with readable labels, Easy macros/damage controls, deck and tape presets, searchable Advanced controls and hover descriptions. The preview displays at 4:3. Playback, stepping, timeline seeking, load/save settings and export use the same parameter state. Show renderer/export failures once with explicit retry controls. Waveform and spectrum views use requested signal taps.

## Verification

Test schema/preset compatibility, macro families, legacy migrations, deterministic seeking, signal finite values, PAL timing, FM carrier mapping, head switch geometry, unchanged record taps, field weaving and output flags. Compile GUI and CLI; run a short FFmpeg export and inspect with FFprobe. Compare numerical kernels and noiseless rendering against the reference when feasible. Record measured differences and any remaining parity gaps explicitly; do not claim pixel parity or speed gains without evidence.
