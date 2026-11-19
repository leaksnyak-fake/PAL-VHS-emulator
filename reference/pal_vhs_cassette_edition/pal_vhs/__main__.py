"""Command line:
    python -m pal_vhs [video.mp4]                       open the RCA preview window
    python -m pal_vhs in.mp4 --export out.mp4 [...]     render offline (interlaced TFF H.264)
"""
from __future__ import annotations
import argparse
import multiprocessing as mp
import sys
import time
import os

from .params import Params, PRESETS, SPEC
from . import experience  # registers curated presets for CLI and GUI alike


def build_params(args):
    p = Params()
    if args.params:
        p = Params.load(args.params)
    if args.preset:
        p.update(PRESETS[args.preset])
    for kv in args.set or []:
        k, v = kv.split("=", 1)
        if k not in SPEC:
            sys.exit(f"unknown parameter {k!r}; run with --list-params")
        kind = SPEC[k]["kind"]
        p.set(k, {"float": float, "int": int, "bool": lambda s: s.lower() in ("1", "true", "yes", "on")}
              .get(kind, str)(v))
    return p


def main():
    ap = argparse.ArgumentParser(prog="pal_vhs", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", nargs="?", help="input video (mp4, anything OpenCV/ffmpeg reads)")
    ap.add_argument("--export", metavar="OUT.mp4", help="render offline instead of opening the GUI")
    ap.add_argument("--preset", choices=list(PRESETS))
    ap.add_argument("--params", metavar="FILE.json", help="load a saved parameter set")
    ap.add_argument("--set", action="append", metavar="KEY=VALUE", help="override a parameter")
    ap.add_argument("--list-params", action="store_true")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--render-backend", choices=['thread','process'], default=None,
                    help='thread: one background renderer; process: parallel workers. Frozen apps default to thread.')
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--start-frame", type=int, default=0, help="first output frame (resume a long export)")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--crf", type=int, default=14)
    ap.add_argument("--x264-preset", default="veryfast",
                    help="ultrafast..slow; slower = smaller file, same picture (render is the bottleneck)")
    args = ap.parse_args()
    if args.render_backend:
        os.environ['PAL_VHS_RENDER_BACKEND'] = args.render_backend

    if args.list_params:
        for k, s in SPEC.items():
            rng = s["lo"] if s["kind"] == "choice" else (f"{s['lo']}..{s['hi']}" if s["lo"] is not None else "")
            print(f"{k:18s} {str(s['default']):10s} {rng!s:18s} {s['label']}")
        return
    p = build_params(args)

    if args.export:
        if not args.video:
            sys.exit("--export needs an input video")
        from .export import export_video
        t = time.time()

        def prog(d, n):
            el = max(time.time() - t, 1e-6)
            fps = d / el
            eta = (n - d) / fps if d else 0
            print(f"\r{d}/{n} frames  {fps:.2f} fps  elapsed {el:5.0f}s  eta {eta:5.0f}s   ", end="", flush=True)
        out = export_video(args.video, args.export, p.to_dict(), args.workers, prog, None,
                     not args.no_audio, args.crf, args.max_frames, args.start_frame, args.x264_preset,
                           lambda s: print(f"\nnote: {s}", file=sys.stderr))
        print(f"\nwrote {out}")
        return

    from .gui import run_gui
    run_gui(args.video, p,workers=args.workers)


if __name__ == "__main__":
    mp.freeze_support()
    main()
