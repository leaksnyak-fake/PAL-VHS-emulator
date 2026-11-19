"""Oscilloscope-style widgets: line waveform monitor and spectrum analyser (QPainter, no matplotlib)."""
from __future__ import annotations
import numpy as np
from scipy import signal
from PySide6 import QtCore, QtGui, QtWidgets as W
from . import consts as C

BG = QtGui.QColor("#0b1210")
GRID = QtGui.QColor("#1f3a2e")
TXT = QtGui.QColor("#7fbf9f")

# key -> (label, sample-rate factor, y range, traces[(tap, colour)])
STAGES = {
    "comp": ("Composite: encoder out vs RCA out", 1, (-0.5, 1.3),
             [("comp_in", "#4aa3ff"), ("comp_out", "#ffd24a")]),
    "comp_out": ("RCA composite output (what the TV gets)", 1, (-0.5, 1.3), [("comp_out", "#ffd24a")]),
    "comp_in": ("PAL encoder output (before VCR)", 1, (-0.5, 1.3), [("comp_in", "#4aa3ff")]),
    "rec_luma": ("VCR record: luma (LPF, pre-emphasis, clip)", 1, (-0.6, 1.1), [("rec_luma", "#7dff9a")]),
    "fm": ("VCR record: luma FM carrier (3.8-4.8 MHz)", 2, (-1.3, 1.3), [("fm", "#ff8c5a")]),
    "tape": ("Tape RF: FM + colour-under + noise", 2, (-2.0, 2.0), [("tape", "#c58aff")]),
    "c_under": ("VCR record: colour-under (627 kHz)", 1, (-0.7, 0.7), [("c_under", "#ff6ad5")]),
    "luma_demod": ("VCR playback: luma after FM demod", 1, (-0.5, 1.1), [("luma_demod", "#7dff9a")]),
    "c_out": ("VCR playback: chroma heterodyned back to 4.43 MHz", 1, (-1.0, 1.0), [("c_out", "#ff6ad5")]),
}


class _Base(W.QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(170)
        self.setSizePolicy(W.QSizePolicy.Expanding, W.QSizePolicy.Expanding)
        self.msg = "no signal"

    def plot_rect(self):
        return QtCore.QRectF(46, 10, self.width() - 56, self.height() - 30)

    def _frame(self, p):
        p.fillRect(self.rect(), BG)
        p.setPen(QtGui.QPen(GRID, 1))
        p.setFont(QtGui.QFont("monospace", 8))


class WaveformView(_Base):
    def __init__(self):
        super().__init__()
        self.traces = []          # (x_us ndarray, y ndarray, colour)
        self.yr = (-0.5, 1.3)
        self.x0, self.x1 = 0.0, 64.0
        self.marks = True

    def set_traces(self, traces, yr, x0, x1, msg=""):
        self.traces, self.yr, self.x0, self.x1, self.msg = traces, yr, x0, x1, msg
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, False)
        self._frame(p)
        r = self.plot_rect()
        y0, y1 = self.yr
        X = lambda us: r.left() + (us - self.x0) / (self.x1 - self.x0) * r.width()
        Y = lambda v: r.bottom() - (v - y0) / (y1 - y0) * r.height()
        step = 0.5 if (y1 - y0) > 1.5 else 0.25 if (y1 - y0) > 0.8 else 0.1
        v = np.ceil(y0 / step) * step
        while v <= y1:
            p.setPen(QtGui.QPen(QtGui.QColor("#2c5a46") if abs(v) < 1e-9 else GRID, 1))
            p.drawLine(QtCore.QPointF(r.left(), Y(v)), QtCore.QPointF(r.right(), Y(v)))
            p.setPen(TXT)
            p.drawText(QtCore.QRectF(0, Y(v) - 7, 42, 14), QtCore.Qt.AlignRight, f"{v:+.2f}")
            v += step
        span = self.x1 - self.x0
        ux = 16 if span > 40 else 8 if span > 20 else 4 if span > 10 else 2 if span > 5 else 1
        u = np.ceil(self.x0 / ux) * ux
        while u <= self.x1:
            p.setPen(GRID)
            p.drawLine(QtCore.QPointF(X(u), r.top()), QtCore.QPointF(X(u), r.bottom()))
            p.setPen(TXT)
            p.drawText(QtCore.QRectF(X(u) - 20, r.bottom() + 3, 40, 14), QtCore.Qt.AlignCenter, f"{u:g}us")
            u += ux
        if self.marks and (self.yr == (-0.5, 1.3)):
            for a, b, name in ((0, 4.7, "sync"), (5.6, 7.85, "burst"), (10.5, 62.5, "active video")):
                if b > self.x0 and a < self.x1:
                    p.setPen(QtGui.QPen(QtGui.QColor("#3f7f64"), 1, QtCore.Qt.DashLine))
                    xa, xb = max(X(a), r.left()), min(X(b), r.right())
                    p.drawRect(QtCore.QRectF(xa, r.top() + 1, xb - xa, 12))
                    p.setPen(TXT)
                    p.drawText(QtCore.QRectF(xa, r.top() + 1, xb - xa, 12), QtCore.Qt.AlignCenter, name)
        if not self.traces:
            p.setPen(TXT)
            p.drawText(r, QtCore.Qt.AlignCenter, self.msg)
            return
        p.setClipRect(r)
        for xs, ys, col in self.traces:
            m = (xs >= self.x0 - 0.2) & (xs <= self.x1 + 0.2)
            xs2, ys2 = xs[m], np.clip(ys[m], y0 - 0.2 * (y1 - y0), y1 + 0.2 * (y1 - y0))
            pts = [QtCore.QPointF(X(a), Y(b)) for a, b in zip(xs2, ys2)]
            p.setPen(QtGui.QPen(QtGui.QColor(col), 1.2))
            p.drawPolyline(pts)


class SpectrumView(_Base):
    def __init__(self):
        super().__init__()
        self.curves = []          # (f_mhz, dB, colour)
        self.fmax = 9.0
        self.dbr = (-120.0, -40.0)

    def set_curves(self, curves, fmax, msg=""):
        self.curves, self.fmax, self.msg = curves, fmax, msg
        if curves:
            top = max(float(np.max(c[1])) for c in curves)
            self.dbr = (top - 80.0, top + 5.0)
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        self._frame(p)
        r = self.plot_rect()
        d0, d1 = self.dbr
        X = lambda f: r.left() + f / self.fmax * r.width()
        Y = lambda d: r.bottom() - (d - d0) / (d1 - d0) * r.height()
        d = np.ceil(d0 / 10) * 10
        while d <= d1:
            p.setPen(GRID)
            p.drawLine(QtCore.QPointF(r.left(), Y(d)), QtCore.QPointF(r.right(), Y(d)))
            p.setPen(TXT)
            p.drawText(QtCore.QRectF(0, Y(d) - 7, 42, 14), QtCore.Qt.AlignRight, f"{d:.0f}")
            d += 10
        fs = 1.0 if self.fmax <= 10 else 2.0
        f = 0.0
        while f <= self.fmax:
            p.setPen(GRID)
            p.drawLine(QtCore.QPointF(X(f), r.top()), QtCore.QPointF(X(f), r.bottom()))
            p.setPen(TXT)
            p.drawText(QtCore.QRectF(X(f) - 20, r.bottom() + 3, 40, 14), QtCore.Qt.AlignCenter, f"{f:g}")
            f += fs
        for fm, name, col in ((C.FCU / 1e6, "colour-under 0.627", "#ff6ad5"),
                              (3.8, "FM sync", "#ff8c5a"), (4.8, "FM white", "#ff8c5a"),
                              (C.FSC / 1e6, "fsc 4.43", "#4aa3ff")):
            if fm <= self.fmax:
                p.setPen(QtGui.QPen(QtGui.QColor(col), 1, QtCore.Qt.DashLine))
                p.drawLine(QtCore.QPointF(X(fm), r.top() + 12), QtCore.QPointF(X(fm), r.bottom()))
        p.setPen(TXT)
        p.drawText(QtCore.QRectF(r.left(), r.bottom() + 14, r.width(), 12), QtCore.Qt.AlignRight, "MHz   (dB, relative)")
        if not self.curves:
            p.drawText(r, QtCore.Qt.AlignCenter, self.msg)
            return
        p.setClipRect(r)
        for f, db, col in self.curves:
            pts = [QtCore.QPointF(X(a), Y(b)) for a, b in zip(f, db) if a <= self.fmax]
            p.setPen(QtGui.QPen(QtGui.QColor(col), 1.2))
            p.drawPolyline(pts)


def welch_db(x, fs, nper=8192):
    f, pxx = signal.welch(np.asarray(x, np.float32), fs=fs, nperseg=nper, window="hann")
    return f / 1e6, 10 * np.log10(pxx + 1e-16)
