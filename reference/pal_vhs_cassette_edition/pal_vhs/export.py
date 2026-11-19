"""Render a whole video through the PAL/VHS chain and encode it as interlaced (TFF) H.264."""
from __future__ import annotations
import os
import shutil
import subprocess
import tempfile
from collections import deque
from . import consts as C
from .params import Params
from .pipeline import Renderer
from .video_io import VideoSource

X264_PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow")


def has_audio(path):
    if not shutil.which("ffprobe"):
        return False
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                        "stream=index", "-of", "csv=p=0", path], capture_output=True, text=True)
    return bool(r.stdout.strip())


def _video_encoder(ff):
    """libx264 if this ffmpeg has it, otherwise libopenh264, otherwise MPEG-4 part 2."""
    r = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True)
    for enc in ("libx264", "libopenh264"):
        if f" {enc} " in r.stdout:
            return enc
    return "mpeg4"


def _tail(path, n=1500):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - n))
            return f.read().decode("utf-8", "replace").strip()
    except OSError:
        return ""


def export_video(src_path, out_path, pdict, workers=None, progress=None, cancel=None,
                 audio=True, crf=14, max_frames=None, start_frame=0, x264_preset="veryfast", notify=None):
    ff = shutil.which("ffmpeg")
    if not ff:
        raise RuntimeError("ffmpeg not found in PATH (install it, e.g. `sudo pacman -S ffmpeg`)")
    if x264_preset not in X264_PRESETS:
        raise ValueError(f"x264 preset must be one of {X264_PRESETS}")
    out_path = os.fspath(out_path)
    if not os.path.splitext(out_path)[1]:
        out_path += ".mp4"                       # ffmpeg cannot guess a container without an extension
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if not os.access(out_dir, os.W_OK):
        raise RuntimeError(f"cannot write to {out_dir}")
    p = Params(**pdict)
    only = {"field 1 only": 0, "field 2 only": 1}.get(p.export_fields)     # None = interlaced
    src = VideoSource(src_path)
    n = src.n_out - start_frame
    if max_frames:
        n = min(n, max_frames)
    if n <= 0:
        src.close()
        raise RuntimeError("nothing to export (start frame beyond the end of the video)")
    enc = _video_encoder(ff)
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{C.FRAME_W}x{C.FRAME_H}", "-r", "25", "-i", "-"]
    use_audio = audio and has_audio(src_path)
    if use_audio:
        cmd += ["-ss", f"{start_frame / 25.0:.3f}", "-i", src_path, "-map", "0:v", "-map", "1:a:0",
                "-c:a", "aac", "-b:a", "160k", "-shortest"]
    if enc == "libx264":
        cmd += ["-c:v", "libx264", "-preset", x264_preset, "-crf", str(crf)]
        if only is None:
            cmd += ["-flags", "+ilme+ildct", "-x264-params", "tff=1"]    # tff: portable across ffmpeg versions
    elif enc == "libopenh264":
        cmd += ["-c:v", "libopenh264", "-b:v", "12M"]
    else:
        cmd += ["-c:v", "mpeg4", "-q:v", "2"] + ([] if only is not None else ["-flags", "+ilme+ildct"])
    cmd += ["-pix_fmt", "yuv420p", "-aspect", "4:3", "-color_range", "tv", "-colorspace", "bt470bg",
            "-color_primaries", "bt470bg", "-color_trc", "gamma28", "-movflags", "+faststart", out_path]
    log = tempfile.TemporaryFile()               # ffmpeg's stderr, read back if it dies
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
    rend = Renderer(workers)
    pd = p.to_dict()
    pending, done, nxt = deque(), 0, 0
    window = rend.workers * 2 + 2
    ok, failed = False, None

    def fail(exc=None):
        log.seek(0)
        msg = log.read().decode("utf-8", "replace").strip()[-1500:]
        raise RuntimeError("ffmpeg stopped while writing frames" + (f":\n{msg}" if msg else "")) from exc

    try:
        while done < n:
            if cancel is not None and cancel():
                break
            while nxt < n and len(pending) < window:
                m = start_frame + nxt
                f1, f2 = src.fields(m, p)
                if src.truncated and m >= src.n_out:          # stream ended early: shorten the output
                    n = min(n, nxt)
                    break
                pending.append(rend.submit(f1, f2, m, pd, False, only))
                nxt += 1
            if done >= n:
                break
            frame, _ = pending.popleft().result()
            try:
                proc.stdin.write(memoryview(frame))
            except (BrokenPipeError, OSError) as e:
                fail(e)
            done += 1
            if progress:
                progress(done, n)
        ok = True
    except Exception as exc:                                  # keep what was rendered; report afterwards
        failed = exc
    finally:
        rend.close()
        try:
            proc.stdin.close()
        except Exception:
            pass
        rc = proc.wait()
        src.close()
        cancelled = cancel is not None and cancel()
        if cancelled or (failed is not None and (rc != 0 or done == 0)):
            try:
                os.remove(out_path)              # cancelled, or ffmpeg itself died: nothing usable
            except OSError:
                pass
    for note in src.notes:
        if notify:
            notify(note)
    if failed is not None:
        if rc == 0 and done > 0 and os.path.exists(out_path):
            raise RuntimeError(f"{failed}\nThe {done} frames rendered so far were saved to {out_path} "
                               f"(resume with --start-frame {start_frame + done}).") from failed
        raise failed
    if rc != 0:
        log.seek(0)
        raise RuntimeError(f"ffmpeg exited with code {rc}:\n{log.read().decode('utf-8', 'replace').strip()[-1500:]}")
    return out_path
