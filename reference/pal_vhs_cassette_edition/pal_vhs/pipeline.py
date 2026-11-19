"""Frame renderer: fields -> PAL composite -> VHS deck -> RCA signal -> TV decode -> woven frame.

The two fields of a frame are independent (noise is seeded per frame/field), so the Renderer farms
each *field* out to the process pool: a single scrubbed frame uses two cores and export keeps all
cores busy with finer-grained work. Scope taps are only produced when asked for."""
from __future__ import annotations
import numpy as np
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures import BrokenExecutor
import multiprocessing as mp
import os
import sys
import threading
from . import consts as C, pal
from .params import Params
from .vhs import Deck
from .diagnostics import logger, enable_fault_log

_DECK = threading.local()


def _deck_for(pdict):
    key = tuple(sorted(pdict.items()))
    if getattr(_DECK,'key',None) != key:
        # A Deck mutates per-field calibration/state. Preview and export threads
        # must never share it, even when they happen to use identical parameters.
        deck = Deck(Params(**pdict))
        _DECK.key, _DECK.deck = key, deck
    return _DECK.deck


def _warm():
    """Worker initialiser: one thread per worker (OpenCV/BLAS pools in every process oversubscribe the CPU),
    then import everything and run the one-off calibrations before the first frame."""
    enable_fault_log('renderer')
    try:
        import cv2
        cv2.setNumThreads(1)
        deck = _deck_for(Params().to_dict())
        pal.basis(0, 0), pal.basis(0, 1)
        pal.decode_field(np.zeros(C.FIELD_LINES[1] * C.SPL), 1, 0, deck.p)
    except Exception:
        logger().exception('Renderer initialization failed')
        raise


def render_field(f, fi, frame_idx, pdict, want_taps=False):
    """f: uint8 (288,720,3). Returns (field uint8 (288,720,3), taps dict|None)."""
    deck = _deck_for(pdict)
    p = deck.p
    comp = pal.encode_field(f.astype(np.float64) / 255.0, fi, frame_idx, p)
    t = {} if want_taps else None
    if p.bypass_tape:
        stream = comp.reshape(-1)
        if want_taps:
            t.update(comp_in=stream)
    else:
        stream = deck.process_field(comp, fi, frame_idx, t)
    out = deck.output_stage(stream, fi, frame_idx)
    rgb = pal.decode_field(out, fi, frame_idx, p)
    taps = None
    if want_taps:
        keep = {"comp_in": t["comp_in"], "comp_out": out}
        if not p.bypass_tape:
            for k in ("rec_luma", "c_under", "luma_demod", "c_out", "rf_env", "fm", "tape"):
                keep[k] = t[k]
        taps = {k: v.astype(np.float16) for k, v in keep.items()}
    return (rgb * 255.0 + 0.5).astype(np.uint8), taps


def render_frame(f1, f2, frame_idx, pdict, want_taps=False):
    """Single-process helper. Returns (frame uint8 (576,720,3), {0: taps, 1: taps} | None)."""
    a, ta = render_field(f1, 0, frame_idx, pdict, want_taps)
    b, tb = render_field(f2, 1, frame_idx, pdict, want_taps)
    return pal.weave(a, b), ({0: ta, 1: tb} if want_taps else None)


def _field_task(args):
    try:
        return render_field(*args)
    except Exception:
        logger().exception('Field render failed frame=%s field=%s',args[2],args[1])
        raise


class FrameFuture:
    """Combines the two field futures of one frame; quacks like a concurrent.futures.Future."""

    def __init__(self, futs, only=None):
        self.futs = futs                  # [field0, field1] futures, or one future when only is 0 / 1
        self.only = only

    def done(self):
        return all(f.done() for f in self.futs)

    def cancelled(self):
        return any(f.cancelled() for f in self.futs)

    def cancel(self):
        for f in self.futs:
            f.cancel()

    def result(self):
        if self.only is not None:         # one field only: double every line -> progressive 576-line frame
            a, ta = self.futs[0].result()
            return np.repeat(a, 2, axis=0), ({self.only: ta} if ta is not None else None)
        (a, ta), (b, tb) = self.futs[0].result(), self.futs[1].result()
        return pal.weave(a, b), ({0: ta, 1: tb} if ta is not None else None)


class Renderer:
    """Bounded process rendering, with a conservative frozen-app thread backend.

    A single background thread avoids packaged multiprocessing/DLL startup and
    runs the same field renderer. Process failures may fall back once, explicitly.
    """

    def __init__(self, workers=None, backend=None):
        for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            os.environ[v] = '1'
        selected = backend or os.environ.get('PAL_VHS_RENDER_BACKEND') or (
            'thread' if getattr(sys,'frozen',False) else 'process')
        if selected not in ('thread','process'):
            raise ValueError('Renderer backend must be thread or process')
        count = workers if workers is not None else min(4,os.cpu_count() or 2)
        if int(count) < 1:
            raise ValueError('Worker count must be positive')
        self.backend = selected
        self.workers = 1 if selected == 'thread' else min(int(count),61)
        self._closed = False
        self._fallback_used = False
        self.pool = self._make_pool()
        logger().info('Renderer created backend=%s workers=%s',self.backend,self.workers)

    def _make_pool(self):
        if self.backend == 'thread':
            return ThreadPoolExecutor(1,thread_name_prefix='pal-vhs-render',initializer=_warm)
        return ProcessPoolExecutor(self.workers,mp_context=mp.get_context('spawn'),initializer=_warm)

    def submit(self, f1, f2, idx, pdict, want_taps=False, only=None):
        if self._closed:
            raise RuntimeError('Renderer is closed')
        futures=[]
        try:
            for fi in ((only,) if only is not None else (0,1)):
                futures.append(self.pool.submit(_field_task,((f1,f2)[fi],fi,idx,pdict,want_taps)))
        except Exception:
            for future in futures:
                future.cancel()
            raise
        return FrameFuture(futures,only)

    def recover(self):
        """Abandon a broken process pool once; never retry indefinitely."""
        if self._closed or self.backend != 'process' or self._fallback_used:
            return False
        exits={pid:proc.exitcode for pid,proc in (getattr(self.pool,'_processes',None) or {}).items()}
        logger().error('Process pool unusable; exit codes=%s. Switching to one background thread.',exits)
        old=self.pool
        self._fallback_used=True
        self.backend='thread'
        self.workers=1
        old.shutdown(wait=False,cancel_futures=True)
        self.pool=self._make_pool()
        return True

    def close(self):
        if self._closed:
            return
        self._closed=True
        self.pool.shutdown(wait=False, cancel_futures=True)
