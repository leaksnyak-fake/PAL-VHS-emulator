"""MP4 reading (any OpenCV/ffmpeg-readable file) and interlaced field extraction (TFF)."""
from __future__ import annotations
import cv2
import numpy as np
from . import consts as C

CANVAS_W = 768        # square-pixel 4:3 canvas; stored 720 wide (anamorphic, like real PAL)


def fit_frame(bgr, aspect):
    h, w = bgr.shape[:2]
    if aspect == "stretch":
        out = cv2.resize(bgr, (CANVAS_W, C.FRAME_H), interpolation=cv2.INTER_AREA)
    else:
        sc = (min if aspect == "fit" else max)(CANVAS_W / w, C.FRAME_H / h)
        nw, nh = max(1, int(round(w * sc))), max(1, int(round(h * sc)))
        r = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_CUBIC)
        out = np.zeros((C.FRAME_H, CANVAS_W, 3), np.uint8)
        if aspect == "fit":
            y0, x0 = (C.FRAME_H - nh) // 2, (CANVAS_W - nw) // 2
            out[y0:y0 + nh, x0:x0 + nw] = r
        else:
            y0, x0 = (nh - C.FRAME_H) // 2, (nw - CANVAS_W) // 2
            out = r[y0:y0 + C.FRAME_H, x0:x0 + CANVAS_W]
    out = cv2.resize(out, (C.FRAME_W, C.FRAME_H), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)


def vfilter(rgb, amount):
    """Vertical [a, 1-2a, a] low-pass so single-line detail does not twitter in interlace."""
    if amount <= 0:
        return rgb
    a = 0.25 * amount
    k = np.array([[a], [1 - 2 * a], [a]], np.float32)
    return np.clip(cv2.filter2D(rgb, -1, k, borderType=cv2.BORDER_REPLICATE), 0, 255).astype(np.uint8)


class VideoSource:
    OUT_FPS = 25.0

    def __init__(self, path):
        self.path = path
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise IOError(f"cannot open {path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.n_src = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.duration = self.n_src / self.fps if self.n_src > 0 else 0.0
        self.n_out = max(1, int(self.duration * self.OUT_FPS))
        self._pos = -1
        self._last = None             # last good decoded frame
        self.truncated = False        # True once the stream ended before the container said it would
        self.notes = []               # human-readable warnings (bad frames, early end)
        self._cache = {}              # (src_idx, aspect, vf) -> uint8 frame

    def _read(self, i):
        """Decode source frame i. Container frame counts and seeks are often wrong (truncated files, VFR,
        broken index), so a failed read is retried, then a nearby frame is substituted, and if the stream
        simply ends early the video is shortened instead of aborting the whole job."""
        i = int(np.clip(i, 0, max(self.n_src - 1, 0)))
        for attempt in range(2):
            if attempt or i != self._pos + 1:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ok, bgr = self.cap.read()
            if ok:
                self._pos, self._last = i, bgr
                return bgr
        for j in range(i + 1, min(i + 4, self.n_src)):          # damaged frame: use the next good one
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, j)
            ok, bgr = self.cap.read()
            if ok:
                self._pos, self._last = j, bgr
                self.notes.append(f"source frame {i} unreadable, used frame {j}")
                return bgr
        if self._last is None:
            raise IOError(f"read failed at frame {i} (nothing readable before it)")
        if not self.truncated:                                    # stream ended earlier than claimed
            self.notes.append(f"video ends at source frame {i}, container claimed {self.n_src}")
        self.truncated = True
        self.n_src = max(1, min(self.n_src, i))
        self.duration = self.n_src / self.fps
        self.n_out = max(1, int(self.duration * self.OUT_FPS))
        self._pos = -1
        return self._last

    def frame(self, i, aspect, vf):
        key = (int(i), aspect, round(vf, 3))
        if key in self._cache:
            return self._cache[key]
        i = key[0]
        rgb = vfilter(fit_frame(self._read(i), aspect), vf)
        if len(self._cache) > 8:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = rgb
        return rgb

    def src_index(self, t):
        return min(int(round(t * self.fps)), max(self.n_src - 1, 0))

    def fields(self, m, p):
        """Output frame m -> (field1, field2) uint8 (288,720,3). Field 1 (top, even rows) is first."""
        if p.field_mode == "temporal":
            a = self.frame(self.src_index(2 * m / 50.0), p.aspect, p.vfilter)
            b = self.frame(self.src_index((2 * m + 1) / 50.0), p.aspect, p.vfilter)
        else:
            a = b = self.frame(self.src_index(m / self.OUT_FPS), p.aspect, p.vfilter)
        return a[0::2], b[1::2]

    def close(self):
        self.cap.release()
