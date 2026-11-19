# BrokenProcessPool fix

## What the supplied traceback proves

A child process exited and the pool became unusable. The Qt preview timer then
continued to call `submit` on that same pool every 20 ms, flooding the console.
The repeated tail does **not** identify why the first worker exited. Missing
packaged DLLs, initializer errors, memory pressure and native-library faults are
possibilities, not established diagnoses of this incident.

## Changes

- Frozen EXEs now default to **one background render thread** for preview and
  export. This bypasses frozen child-process startup and lowers concurrent memory
  demand, while running the same DSP and moving-snow code. Rendering can be slower
  than a healthy multi-process setup; it remains outside the GUI event loop.
- Source preview defaults to at most two processes. Source offline exports
  default to at most four. An explicit `--workers` remains available.
- A process-pool failure detected on submission **or** when retrieving a result
  discards stale work and attempts one fallback to the background-thread backend.
  There is no unbounded restart loop.
- A failed fallback, failed thread initializer, or ordinary render/data error
  stops scheduling and preserves an actionable status message. **Retry renderer**
  starts a fresh renderer, retaining source and settings. Plain DSP errors are
  not disguised as worker startup failures.
- Partial submissions cancel any already-queued field when the second field
  cannot be submitted. Shutdown is idempotent.
- Deck caches are thread-local so simultaneous preview/export renderers cannot
  mutate a shared Deck's per-field state.
- Preview scheduling pauses during GUI export. The paused-scope cache retains
  two entries rather than ten; the frame-cache window is smaller but still
  supports the five-second pre-render mode.
- Launcher thread limits are set before importing NumPy/SciPy/OpenCV. The existing
  `freeze_support()` entry point is retained.

## Run after rebuilding

```cmd
build_windows.cmd
dist\PAL-VHS\PAL-VHS.exe
```

An explicit compatibility command is also available in the rebuilt executable:

```cmd
dist\PAL-VHS\PAL-VHS.exe --render-backend thread
```

For a source run:

```cmd
.venv\Scripts\python.exe -m pal_vhs --render-backend thread
```

Only if a parallel backend is known to work on the intended machine:

```cmd
dist\PAL-VHS\PAL-VHS.exe --render-backend process --workers 2
```

`PAL_VHS_RENDER_BACKEND=thread` or `process` is an environment alternative.
Thread mode intentionally uses one render worker regardless of `--workers`.

## Diagnostics

On Windows logs are written below:

```text
%LOCALAPPDATA%\PAL-VHS\logs
```

`render-<pid>.log` records Python exceptions, backend changes, and available worker
exit codes. `*-fault-<pid>.log` captures native fault traces when Python's fault
handler is active. A worker killed by the OS can leave no native traceback; its
exit code is still useful. `PAL_VHS_LOG_DIR` overrides the directory. Logging is
best-effort and cannot be allowed to break rendering.

The thread backend avoids subprocess startup failures; it cannot isolate a
native crash of the entire application. If the rebuilt app itself exits, the
fault log is needed to diagnose that separate failure. No specific original
worker-exit cause was reproduced from the supplied tail alone.

## Validation

All **51 tests** pass, including the earlier snow/UI tests plus ten concurrency
and failure-path tests and one Retry test. A real spawned child is deliberately
terminated with exit code 91; the renderer logs that exit, switches backend once,
and successfully renders a complete frame. Tests also exercise both timer-loop
failure paths, permanent error latching, partial-submit cancellation, frozen-mode
selection, isolated Deck caches and manual Retry preservation of source/settings.

Four-frame CLI exports through the real process pool and single-thread backend
were decoded and compared with FFmpeg `framemd5`; the decoded frame checksums
match. The `validation/process.md5` and `thread.md5` files contain that check.
The current source suite also passes on Windows with offscreen Qt; a rebuilt
Windows EXE has not been run for this revision. The checksum export check was
performed on the earlier recovery build before the snow-shape restoration.

Official implementation references:

- [Python concurrent futures](https://docs.python.org/3/library/concurrent.futures.html)
- [PyInstaller multiprocessing notes](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#multi-processing)
