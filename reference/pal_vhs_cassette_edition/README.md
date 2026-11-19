# PAL VHS — cassette deck edition

A Python PAL/VHS signal simulator with a cassette-style Easy mode and a complete
Advanced signal laboratory. Edition 2 corrects PAL head-channel phase sequencing and adds RF-based head switching.

## Run

Use Python 3.12 or newer. From this directory (the one containing `pal_vhs/`):

```powershell
python -m pip install -r pal_vhs/requirements.txt
python -m pal_vhs
python -m pal_vhs "input.mp4"
```

Install FFmpeg and FFprobe and put both on PATH for video export. The archive is
source code, not a standalone Windows executable. Start from a terminal so any
dependency error is visible. Existing JSON parameter files remain usable.

## Easy mode: use it like a tape deck

1. Insert a video with **Open mp4** (Ctrl+O; the file chooser also accepts MOV,
   MKV, AVI and WebM).
2. Select **PAL VHS / SP - fresh cassette** and press **Apply preset** for a
   restrained starting point. Choosing a name alone does not apply it. Startup
   and Defaults now use stable RF head switching with zero head-switch line jitter. Applying a preset resets the complete parameter set.
3. Use **Tape wear**, **Colour bleed**, and **Picture wobble**. Choose SP for
   ordinary PAL VHS; LP for a longer recording. EP is retained as an optional
   experimental model, not a universal PAL mode.
4. Click **+ Smear**, **+ Crease**, **+ Dropouts**, or **White band** to damage
   the cassette. Repeated clicks increase the amount; White band toggles a
   recurring effect. **Undo** reverses the most recent damage-button action
   (up to 20). **Repair damage** removes deliberate wear/damage while retaining
   the colour and wobble settings. Fine VHS noise and the bottom head-switch
   region may remain: these are separate signal mechanisms.
5. Adjust **Tracking − / +**: zero aligns the head; negative loses tracking
   toward the bottom, positive toward the top.
6. Play/pause with Space. Scrub the timeline or step with Left/Right. Export
   the full clip when satisfied. Easy is a simpler interface, not a faster renderer.

Damage applies to the **whole clip**. Buttons do not insert timestamped events.
Travelling bands recur according to their Advanced timing settings. A timeline
editor for isolated damage is a future improvement.

## Advanced mode and hover help

Switch modes at the top of the left panel. Both modes edit the **same settings**;
switching never resets them. Advanced retains all 124 parameters, grouped in
signal-flow order, and reveals waveform/spectrum scopes. Search by control
label, technical key, or effect description. Hover the label, slider, number,
checkbox or selector for its meaning, range, and default. Type into a slider's
number field and press Enter for a precise value; values clamp to the permitted
range and snap to slider steps.

Easy sliders are multi-parameter macros. Moving a macro replaces only its own
parameter family. Its percentage follows the family's first parameter, so a
hand-tuned Advanced combination may not match every secondary macro value.
Use [the control reference](docs/CONTROLS.md) for the exact mappings and keys.

In Advanced, **Field 1/2 only** changes both preview and GUI export: the selected
field is doubled into a progressive 720×576 output. Ordinary woven output is
25 frames / 50 fields per second, top field first. Combing during motion is
expected when a woven interlaced frame is viewed without deinterlacing.

## Presets and accuracy

Seven tape presets cover fresh SP, home SP, LP, worn rental, tracking failure,
creased tape, and stable playback. Eight additional playback profiles cover rough
budget through professional output and an explicit recorded-servo fault. Legacy presets remain selectable. Hover each
preset for its intent. Everyday presets are deliberately restrained; damage
presets are marked as illustrative. The technical anchor is PAL 625/50 and
nominal VHS FM 3.8–4.8 MHz with colour-under, not an RGB overlay.

These presets are **model-based estimates**, not calibrated copies of a specific
VCR/camcorder. The existing SP/LP/EP bandwidth/noise multipliers and simplified
mechanics remain. Exact matching needs a known deck, tape, test chart, and real
capture. Do not compare differently weighted S/N numbers as if they were equal.
Audio passes through unchanged; the simulator does not add VHS audio hiss,
wow/flutter, Hi-Fi switching, or dropouts.

Primary technical references consulted:

- [JVC Video Technical Guide, VHS basics](https://decode-orc.github.io/analogue-video-specifications/vhs/JVC-Video-Technical-Guide-VTG82063/section-1/)
- [Pioneer Tuning Fork No. 9, PAL VHS technical description](https://www.cieri.net/Documenti/Altri%20marchi/Pioneer%20-%20Tuning%20Fork%20No.9%20%28~1980%29.pdf)
- [JVC HR-XV series service manual](https://rcaudio.rclabs.com.br/library/docs/Schematics%2C%20Service%20Manuals%20and%20Catalogs/Jvc/Jvc-HRXV-31-EX-Service-Manual.pdf)

The archived JVC guide's format-summary table has an apparent PAL colour-under
transcription inconsistency (625.953 versus the established 626.953 kHz). The
existing engine's 40.125 × line frequency = 626.953125 kHz is retained.

## Save, CLI, and source map

Save/Load uses complete JSON parameters shared by preview and export. Applying a
preset, loading a file, or restoring defaults clears damage-button undo history.

```powershell
python -m pal_vhs input.mp4 --export output.mp4 --preset "PAL VHS / SP - home recording" --workers 4 --max-frames 250
python -m pal_vhs input.mp4 --params cassette.json --set tracking=-0.25
python -m pal_vhs --list-params
python -m unittest discover -s tests -v
python tests/render_smoke.py
```

Frozen executables use one background render thread to avoid packaged child-process
startup failures. Source preview defaults to two processes and source CLI export
to at most four; `--workers` and `--render-backend` are configurable. Scopes are not
computed in Easy mode, reducing paused-preview overhead. Final RF quality stays
at 2x in the curated presets. The Advanced 1x RF setting is for draft previews.

| File | Responsibility |
|---|---|
| `params.py` | Parameter schema, validation, JSON, legacy presets |
| `experience.py` | Curated presets, help text, Easy macro mappings |
| `headswitch.py` | Fractional switch geometry, RF envelope, PAL head phase and deck profiles |
| `easy_ui.py` | Cassette drawing, Easy controls and damage-button undo |
| `gui.py` | Mode switch, searchable Advanced controls, preview and scopes |
| `video_io.py` | Source video fitting and temporal field extraction |
| `pal.py` | PAL waveform encoding and TV decoding |
| `vhs.py` | Record, tape/head, playback, timebase and damage modelling |
| `dsp.py` | Filters, FM modulation/demodulation, resampling utilities |
| `pipeline.py` | Field/frame orchestration and worker pool |
| `export.py` | FFmpeg output, audio passthrough and cancellation |
| `bench.py` | Synthetic signal measurements |

The original technical notes remain in `pal_vhs/README.md`. See
[validation](docs/VALIDATION.md) for checks and current testing limits, and
[the Rust migration plan](docs/RUST_PLAN.md) for the next implementation stages.

## Edition 2: head-switch update

Read [the researched effects guide](docs/VHS_EFFECTS_REFERENCE.md). All presets
and defaults now have zero head-switch line jitter. Normal profiles use a local
RF interruption and FM phase mismatch, with separate per-head colour calibration.
Legacy painted snow remains available in legacy-overlay mode. Easy mode adds an
**Apply deck** selector that preserves tape condition; full presets still reset
all settings. Applying a new profile also clears any inherited old jitter value.

Old JSON files intentionally retain their explicit values, so load then apply
a deck profile or set `hs_jitter_us=0` when migrating a hand-tuned file.

For Windows use [the build guide](docs/WINDOWS_BUILD.md) and `build_windows.cmd`.
Launch from `dist`, never from `build`. The archive contains source, not a new EXE.

## Waveform snow update

Use `Deck / Professional / narrow residual (user reference)` for nominal 9-pixel
snow, one line per field, with five woven-frame rows below the band. Cheaper
profiles use 12 or 15 pixels and two field lines. All values are editable.
See [the snow reference notes](docs/RESIDUAL_REFERENCE_UPDATE.md) for units, the
assumed vertical offset, and the restored soft waveform shape.

## Snow controls and motion fix

Advanced / Head switching now shows the active **Head-switch snow** controls in
RF mode. The incompatible legacy snow controls are hidden in that mode, and
return when Legacy overlay is selected. Search follows the same mode selection.
Easy mode has a snow-strength slider and a **Moving** toggle.

Snow defaults to **Drift + jitter** (drift plus random jitter, see below). This moves the snow streak independently of image-line jitter.
Set **Snow motion** to Stationary to stop it. Play or step frames to see motion;
a paused frame stays deterministic. Rebuild the executable after updating source.

## Worker-crash recovery update

The repeating BrokenProcessPool timer-loop error is fixed. Frozen apps default to
a background thread; source process pools can recover once to that backend. A
failed renderer stops scheduling and shows **Retry renderer**. See
[recovery notes](docs/RENDERER_RECOVERY.md) for limits and diagnostics. All prior
snow controls and motion are retained. Rebuild the EXE before testing this fix.

## Original snow shape restored

The rectangular post-decode snow patch has been removed. RF-mode snow now uses
the original attack/decay, correlated grain and length breathing on the luma
waveform before output filters and TV decoding. Width is a nominal duration,
with a soft fading tail. All width, height, position and motion controls remain;
the Legacy overlay implementation and renderer-crash recovery are retained.
51 regression tests pass on Windows. Rebuild with `build_windows.cmd` and launch
`dist\PAL-VHS\PAL-VHS.exe` to use the updated source.

## Snow movement and jitter
The Forward/back steps mode and its four settings were removed. **Snow motion** now defaults to **Drift + jitter**:
**Snow drift** moves the snow every field and **Snow jitter (pixels rms)** adds a random position change every field
plus a smaller independent jitter per snow line. Jitter works with Drift + jitter and Random jumps; set it to 0 for
drift only. Old parameter files that use Forward/back steps still load (they become Drift + jitter).

## White band: flicker, shrinking, colour loss
* **White flicker** (`wr_flicker`): the white part is randomly dimmed every field (up to this fraction).
* **Band shrinks toward the bottom** (`wr_shrink`): bands lose height as they travel down, each at its own random rate
  (0.4x-1.4x of the setting); a band smaller than about one line disappears, which can happen anywhere in the picture.
  0 = constant height. The white part shrinks with the band.
* **Colour loss under the stretched lines** (`wr_chroma_loss`): chance that a band also loses colour over its whole
  repeated area, not only the white part.

## SP tape damage on a blank tape (preset "PAL VHS / SP - blank tape damage (reference)")
Built from the 1nicboy "tape damage on all 4 speeds" video (SP panel), matched by eye on a flat blue picture:
* **Band style: grey fade** (`wr_style`, `wr_grey`): the travelling band is grey lines fading to black toward the band
  bottom, with vertical streaks and no colour, instead of solid white.
* **Colour banding** (`chroma_band`): soft horizontal bands of different saturation drifting slowly.
* **Colour lock glitch** (`cu_glitch`, `cu_glitch_period`, `cu_glitch_len`): episodes where colour saturation/phase
  swings by line groups. With the PAL-D decoder this shows as saturation changes; with PAL-S it also shifts hue
  (greenish / bluish), which is closer to the reference capture.
Known gap: the reference's tracking band is fine white/black/yellow confetti; ours is still streakier.

## Analog dynamics of creases (measured on the SP reference)
Tracked frame by frame on the SP panel: a crease moves about 2 lines/frame at the top and 1.3-2x faster near the bottom,
starts thin and thickens over ~25 frames, keeps its height, then thins out and vanishes in the lower part; thin satellite
creases move with it; the top edge fades in softly while the bottom edge ends sharply; brightness changes are smooth in time.
New settings: `wr_accel`, `wr_wobble`, `wr_rise`, `wr_soft`, `wr_sat` (and `wr_shrink`, now starting at mid-picture),
and for the tracking band `track_accel`, `track_wobble`. Set them to 0 for the old constant-speed look.
