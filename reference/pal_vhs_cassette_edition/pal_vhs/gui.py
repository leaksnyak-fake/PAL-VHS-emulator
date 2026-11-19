"""RCA preview window (PySide6): TV picture + signal scopes + live parameter panel."""
from __future__ import annotations
import os
import sys
import time
import math
from collections import OrderedDict
from concurrent.futures import BrokenExecutor

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets as W

from . import consts as C
from .export import export_video
from .params import GROUPS, PRESETS, SPEC, SPECS, Params
from .experience import CURATED, help_for, preset_info
from .easy_ui import EasyPanel
from .pipeline import Renderer
from .diagnostics import logger, log_directory
from .scopes import STAGES, SpectrumView, WaveformView, welch_db
from .video_io import VideoSource

FLOW = ("source mp4 -> PAL encoder (Y/U/V, sync, burst, subcarrier) -> VCR record "
        "[luma: LPF + pre-emph + FM 3.8-4.8 MHz | chroma: heterodyne to 627 kHz] -> tape/head "
        "-> VCR playback [FM demod | colour up-convert, ACC/APC, time-base errors] "
        "-> RCA composite -> TV decoder (sync, burst lock, PAL-D) -> picture")


class VideoView(W.QWidget):
    def __init__(self):
        super().__init__()
        self.img = None
        self.marker = None
        self.setMinimumSize(480, 360)
        self.setSizePolicy(W.QSizePolicy.Expanding, W.QSizePolicy.Expanding)

    def set_image(self, rgb):
        h, w = rgb.shape[:2]
        self.img = QtGui.QImage(np.ascontiguousarray(rgb).data, w, h, 3 * w,
                                QtGui.QImage.Format_RGB888).copy()
        self.update()

    def target(self):
        W_, H_ = self.width(), self.height()
        w = min(W_, H_ * 4 / 3)
        h = w * 3 / 4
        return QtCore.QRectF((W_ - w) / 2, (H_ - h) / 2, w, h)

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#050807"))
        r = self.target()
        if self.img is not None:
            p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
            p.drawImage(r, self.img)
            if self.marker is not None:
                y = r.top() + self.marker * r.height()
                p.setPen(QtGui.QPen(QtGui.QColor(255, 60, 60, 200), 1))
                p.drawLine(QtCore.QPointF(r.left(), y), QtCore.QPointF(r.right(), y))
        else:
            p.setPen(QtGui.QColor("#7fbf9f"))
            p.drawText(r, QtCore.Qt.AlignCenter, "Open an mp4 (Ctrl+O)")


class ParamPanel(W.QWidget):
    changed = QtCore.Signal(str, object)
    mode_changed = QtCore.Signal(bool)

    def __init__(self, params):
        super().__init__()
        self.params = params
        self.ctl = {}
        v = W.QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        self.mode_selector = W.QComboBox()
        self.mode_selector.addItems(["Easy · cassette deck", "Advanced · signal laboratory"])
        self.mode_selector.setToolTip("Switch the control layout without changing your tape settings. Advanced also shows signal scopes.")
        v.addWidget(self.mode_selector)
        row = W.QHBoxLayout()
        self.preset = W.QComboBox()
        self.preset.setSizeAdjustPolicy(W.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.preset.setMinimumContentsLength(22)
        self.preset.addItems(list(CURATED) + [n for n in PRESETS if n not in CURATED])
        for i in range(self.preset.count()):
            self.preset.setItemData(i, "\n".join(preset_info(self.preset.itemText(i))), QtCore.Qt.ToolTipRole)
        self.preset.setToolTip("Choose a starting point, then Apply. Applying resets all parameters, including source and TV adjustments.")
        b_apply = W.QPushButton("Apply preset")
        b_apply.clicked.connect(lambda: self.apply_preset(self.preset.currentText()))
        b_apply.setToolTip("Reset the complete parameter set, then apply the selected preset.")
        row.addWidget(self.preset, 1)
        row.addWidget(b_apply)
        v.addLayout(row)
        self.preset_note = W.QLabel()
        self.preset_note.setWordWrap(True)
        self.preset.currentTextChanged.connect(self._preset_note)
        self._preset_note(self.preset.currentText())
        v.addWidget(self.preset_note)
        row = W.QHBoxLayout()
        for text, fn in (("Save...", self.save), ("Load...", self.load), ("Defaults", self.reset)):
            b = W.QPushButton(text)
            b.setToolTip({"Save...": "Save every Easy and Advanced parameter to a JSON file.",
                          "Load...": "Load a saved parameter set; both modes share these values.",
                          "Defaults": "Restore the original project's defaults, including its stronger head-switch effects."}[text])
            b.clicked.connect(fn)
            row.addWidget(b)
        v.addLayout(row)
        self.stack = W.QStackedWidget()
        self.easy = EasyPanel(params)
        self.easy.changed.connect(self._easy_changed)
        sc_easy = W.QScrollArea()
        sc_easy.setWidgetResizable(True)
        sc_easy.setWidget(self.easy)
        self.stack.addWidget(sc_easy)
        advanced = W.QWidget()
        adv = W.QVBoxLayout(advanced)
        self.search = W.QLineEdit()
        self.search.setPlaceholderText("Find a control: label, key, or effect…")
        self.search.setToolTip("Filter Advanced controls by name, internal parameter key, or hover-help text.")
        self.search.textChanged.connect(self._filter)
        adv.addWidget(self.search)
        tb = self.toolbox = W.QToolBox()
        self.rows = []
        for g in GROUPS:
            page = W.QWidget()
            form = W.QFormLayout(page)
            form.setLabelAlignment(QtCore.Qt.AlignRight)
            for s in [s for s in SPECS if s["group"] == g]:
                label = W.QLabel(s["label"])
                label.setWordWrap(True)
                label.setMaximumWidth(180)
                label.setToolTip(help_for(s))
                control = self._make(s)
                form.addRow(label, control)
                self.rows.append((s, label, control))
            sc = W.QScrollArea()
            sc.setWidgetResizable(True)
            sc.setWidget(page)
            sc.setFrameShape(W.QFrame.NoFrame)
            tb.addItem(sc, g.split(" ", 1)[1].replace("&", "&&"))
        adv.addWidget(tb, 1)
        self.stack.addWidget(advanced)
        v.addWidget(self.stack, 1)
        self.mode_selector.currentIndexChanged.connect(self._mode)
        self.refresh_widgets()

    def _mode(self, index):
        self.stack.setCurrentIndex(index)
        self.mode_changed.emit(index == 1)

    def _preset_note(self, name):
        category, description = preset_info(name)
        self.preset_note.setText(f"Selected preset · {category}\n{description}\nPress Apply to replace the current settings.")

    def _easy_changed(self):
        self.refresh_widgets()
        self.changed.emit("*", None)

    def _filter(self, text):
        text = text.casefold().strip()
        counts = {g: 0 for g in GROUPS}
        for s, label, control in self.rows:
            show = self._available(s['key']) and text in (s['key'] + ' ' + s['label'] + ' ' + help_for(s)).casefold()
            label.setVisible(show)
            control.setVisible(show)
            counts[s['group']] += int(show)
        for i, group in enumerate(GROUPS):
            self.toolbox.setItemEnabled(i, counts[group] > 0)
        if counts[GROUPS[self.toolbox.currentIndex()]] == 0:
            for i, group in enumerate(GROUPS):
                if counts[group]:
                    self.toolbox.setCurrentIndex(i)
                    break

    def _available(self,key):
        if key == 'hs_lines' or key.startswith('hs_snow'):
            return self.params.hs_model == 'legacy overlay'
        if key.startswith('hs_residual'):
            return self.params.hs_model != 'legacy overlay'
        return True

    def _make(self, s):
        k, key = s["kind"], s["key"]
        cur = getattr(self.params, key)
        if k == "bool":
            w = W.QCheckBox()
            w.setChecked(cur)
            w.toggled.connect(lambda val, key=key: self._emit(key, val))
            self.ctl[key] = (w, None)
            box = w
        elif k == "choice":
            w = W.QComboBox()
            w.addItems(s["lo"])
            w.setCurrentText(cur)
            w.currentTextChanged.connect(lambda val, key=key: self._emit(key, val))
            self.ctl[key] = (w, None)
            box = w
        else:
            n = int(round((s["hi"] - s["lo"]) / s["step"]))
            sl = W.QSlider(QtCore.Qt.Horizontal)
            sl.setRange(0, n)
            lab = W.QLineEdit()                       # click the number to type an exact value
            lab.setFixedWidth(62)
            lab.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            lab.setToolTip("Click and type a value, then press Enter (clamped to the slider range)")

            def to_val(i, s=s):
                v = s["lo"] + i * s["step"]
                return int(round(v)) if s["kind"] == "int" else round(v, 4)

            def on(i, key=key, lab=lab, to_val=to_val):
                val = to_val(i)
                lab.setText(f"{val:g}")
                self._emit(key, val)
            sl.setValue(int(round((cur - s["lo"]) / s["step"])))
            lab.setText(f"{cur:g}")
            sl.valueChanged.connect(on)

            def typed(sl=sl, lab=lab, s=s):
                try:
                    x = float(lab.text().replace(",", ".").strip())
                except ValueError:
                    x = None
                if x is None or not math.isfinite(x):  # reject NaN/inf as well as bad text
                    lab.setText(f"{s['lo'] + sl.value() * s['step']:g}")
                    return
                i = int(round((min(max(x, s["lo"]), s["hi"]) - s["lo"]) / s["step"]))
                if i == sl.value():                   # same slot: just normalise the text
                    lab.setText(f"{s['lo'] + i * s['step']:g}")
                else:
                    sl.setValue(i)                    # fires `on`, which updates text + params
            lab.editingFinished.connect(typed)

            class _SelectAll(QtCore.QObject):         # select the whole number when clicked into
                def eventFilter(self, o, e):
                    if e.type() == QtCore.QEvent.FocusIn:
                        QtCore.QTimer.singleShot(0, o.selectAll)
                    return False
            lab._sel = _SelectAll(lab)
            lab.installEventFilter(lab._sel)
            sl.setToolTip(help_for(s))
            lab.setToolTip(help_for(s))
            self.ctl[key] = (sl, lab)
            box = W.QWidget()
            h = W.QHBoxLayout(box)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(sl, 1)
            h.addWidget(lab)
        box.setToolTip(help_for(s))
        return box

    def _emit(self, key, val):
        self.params.set(key, val)
        if key == 'hs_model':
            self.refresh_widgets()
        self.easy.refresh()

        self.changed.emit(key, val)

    def refresh_widgets(self):
        for key, (w, lab) in self.ctl.items():
            s, cur = SPEC[key], getattr(self.params, key)
            w.blockSignals(True)
            if s["kind"] == "bool":
                w.setChecked(cur)
            elif s["kind"] == "choice":
                w.setCurrentText(cur)
            else:
                w.setValue(int(round((cur - s["lo"]) / s["step"])))
                lab.setText(f"{cur:g}")
            w.blockSignals(False)
            legacy = key == 'hs_lines' or key.startswith('hs_snow')
            rf_only = key in ('hs_advance','hs_gap_us','hs_recovery_us','hs_phase_deg','hs_servo_lines')
            enabled = (self.params.hs_model == 'legacy overlay' if legacy else
                       self.params.hs_model == 'RF switch' if rf_only else True)
            if self.params.hs_model == 'off' and key.startswith('hs_') and key != 'hs_model':
                enabled = False
            w.setEnabled(enabled)
            if lab is not None:
                lab.setEnabled(enabled)
        self.easy.refresh()
        self._filter(self.search.text())

    def apply_preset(self, name):
        self.params.update(Params().to_dict())
        self.params.update(PRESETS[name])
        self.easy.history.clear()
        self.refresh_widgets()
        self.changed.emit("*", None)

    def reset(self):
        self.params.update(Params().to_dict())
        self.easy.history.clear()
        self.refresh_widgets()
        self.changed.emit("*", None)

    def save(self):
        f, _ = W.QFileDialog.getSaveFileName(self, "Save parameters", "vhs_params.json", "JSON (*.json)")
        if f:
            try:
                self.params.save(f)
            except (OSError, ValueError) as e:
                W.QMessageBox.warning(self, "Save parameters", str(e))

    def load(self):
        f, _ = W.QFileDialog.getOpenFileName(self, "Load parameters", "", "JSON (*.json)")
        if f:
            try:
                loaded = Params.load(f)
            except (OSError, ValueError, TypeError, KeyError, OverflowError) as e:
                W.QMessageBox.warning(self, "Load parameters", str(e))
                return
            self.params.update(loaded.to_dict())
            self.easy.history.clear()
            self.refresh_widgets()
            self.changed.emit("*", None)


class ExportWorker(QtCore.QThread):
    progress = QtCore.Signal(int, int)
    failed = QtCore.Signal(str)
    notice = QtCore.Signal(str)

    def __init__(self, src, out, pdict, workers):
        super().__init__()
        self.args = (src, out, pdict, workers)
        self.cancel = False

    def run(self):
        s, o, pd, w = self.args
        try:
            export_video(s, o, pd, w, lambda d, n: self.progress.emit(d, n), lambda: self.cancel,
                         notify=self.notice.emit)
        except Exception as e:                      # noqa
            logger().exception('Export failed')
            self.failed.emit(str(e))


class MainWindow(W.QMainWindow):
    def __init__(self, path=None, params=None, workers=None):
        super().__init__()
        self.setWindowTitle("PAL / VHS RCA monitor - 625i 50 Hz interlaced, TFF")
        self.params = params or Params()
        self.src = None
        self.path = None
        self.cur = 0
        self.playing = False
        self.gen = 0
        self.cache, self.tapcache, self.inflight = {}, OrderedDict(), {}
        self.shown_key = None
        self.scope_key = None
        self.spec_key = None
        self.t_last_adv = 0.0
        self.target = None
        self.buffering = False
        self.stat_t = time.time()
        self.stat_n = 0
        self.fps_est = 0.0
        self.requested_workers = workers if workers is not None else max(1,min(2,os.cpu_count() or 2))
        self.renderer = Renderer(self.requested_workers)
        self.workers = self.renderer.workers
        self.render_error = None
        self.render_notice = ''
        self.export_thread = None
        self._build()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(20)
        self.debounce = QtCore.QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.timeout.connect(self.invalidate)
        if path:
            self.open_video(path)

    # ------------------------------------------------------------------ UI
    def _build(self):
        self.panel = ParamPanel(self.params)
        self.panel.changed.connect(lambda *_: self.debounce.start(150))
        dock = W.QDockWidget("VCR / signal parameters", self)
        dock.setWidget(self.panel)
        dock.setMinimumWidth(390)
        dock.setFeatures(W.QDockWidget.DockWidgetMovable | W.QDockWidget.DockWidgetFloatable)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)

        self.video = VideoView()
        self.disp = W.QComboBox()
        self.disp.addItems(["Interlaced (woven frame)", "Field 1 only (top)", "Field 2 only (bottom)"])
        self.disp.setToolTip("Woven preview shows both fields and motion combing. Single-field view also makes GUI export progressive with doubled lines.")
        self.disp.currentIndexChanged.connect(lambda *_: self._redraw())
        self.chk_marker = W.QCheckBox("Show probe line")
        self.chk_marker.setToolTip("Red line on the picture = the scan line the scopes are probing")
        self.chk_marker.toggled.connect(lambda *_: self._redraw())
        self.btn_open = W.QPushButton("Open mp4")
        self.btn_open.clicked.connect(self.open_dialog)
        self.btn_open.setToolTip("Insert a video cassette: open a source video (Ctrl+O).")
        self.btn_play = W.QPushButton("Play")
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_play.setToolTip("Play or pause (Space). Arrow keys step one frame. Playback may run slower than real time.")
        self.mode = W.QComboBox()
        self.mode.addItems(["Live (as fast as CPU allows)", "Pre-render 5 s, then play at 25 fps"])
        self.mode.setToolTip("Live previews immediately. Pre-render buffers a 5-second section before playing at PAL frame rate.")
        self.btn_export = W.QPushButton("Export mp4 (interlaced TFF)")
        self.btn_export.clicked.connect(self.export)
        self.btn_retry = W.QPushButton('Retry renderer')
        self.btn_retry.setToolTip('Start a fresh renderer after an error. Settings and source are preserved.')
        self.btn_retry.clicked.connect(self.retry_renderer)
        self.btn_retry.hide()
        self.btn_export.setToolTip("Export the full clip with current settings. The field-view selector also controls interlaced or progressive output. Audio passes through unchanged.")
        self.seek = W.QSlider(QtCore.Qt.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.setToolTip("Scrub the source timeline. Tape damage is deterministic at every frame.")
        self.seek.sliderMoved.connect(self.on_seek)
        self.lab_pos = W.QLabel("-")
        self.lab_stat = W.QLabel("")
        row = W.QHBoxLayout()
        for w in (self.btn_open, self.btn_play, self.mode, self.btn_export):
            row.addWidget(w)
        display_row = W.QHBoxLayout()
        display_row.addWidget(self.disp)
        display_row.addWidget(self.chk_marker)
        display_row.addStretch()
        left = W.QVBoxLayout()
        left.addWidget(self.video, 1)
        left.addWidget(self.seek)
        left.addWidget(self.lab_pos)
        left.addLayout(row)
        left.addLayout(display_row)
        left.addWidget(self.lab_stat)
        left.addWidget(self.btn_retry)
        lw = W.QWidget()
        lw.setLayout(left)

        flow = W.QLabel(FLOW)
        flow.setWordWrap(True)
        flow.setStyleSheet("color:#7fbf9f;font-size:10px")
        self.field = W.QComboBox()
        self.field.addItems(["Field 1 (top, first)", "Field 2 (bottom)"])
        self.line = W.QSpinBox()
        self.line.setRange(0, 312)
        self.line.setValue(C.ACTIVE_FIRST + 120)
        self.stage = W.QComboBox()
        for k, v in STAGES.items():
            self.stage.addItem(v[0], k)
        self.wid = W.QComboBox()
        for us in (64, 32, 16, 8, 4):
            self.wid.addItem(f"{us} us", us)
        self.start = W.QSlider(QtCore.Qt.Horizontal)
        self.start.setRange(0, 640)
        for w in (self.field, self.stage, self.wid):
            w.currentIndexChanged.connect(lambda *_: self.update_scopes())
        self.line.valueChanged.connect(lambda *_: (self.update_scopes(), self._redraw()))
        self.start.valueChanged.connect(lambda *_: self.update_scopes())
        ctl = W.QGridLayout()
        ctl.addWidget(W.QLabel("Field"), 0, 0)
        ctl.addWidget(self.field, 0, 1)
        ctl.addWidget(W.QLabel("Line"), 0, 2)
        ctl.addWidget(self.line, 0, 3)
        ctl.addWidget(W.QLabel("Probe"), 1, 0)
        ctl.addWidget(self.stage, 1, 1, 1, 3)
        ctl.addWidget(W.QLabel("Window"), 2, 0)
        ctl.addWidget(self.wid, 2, 1)
        ctl.addWidget(self.start, 2, 2, 1, 2)
        self.wave = WaveformView()
        self.spec = SpectrumView()
        right = W.QVBoxLayout()
        right.addWidget(flow)
        right.addLayout(ctl)
        right.addWidget(self.wave, 3)
        right.addWidget(self.spec, 2)
        rw = W.QWidget()
        rw.setLayout(right)
        rw.setMinimumWidth(430)
        self.scope_widget = rw
        for widget, tip in ((self.field, "Choose the temporal field to probe: top first, then bottom 20 ms later."),
                            (self.line, "Scan-line index within the selected field, including blanking; active video begins at line 23."),
                            (self.stage, "Choose a signal stage for the waveform and spectrum. Tape stages are unavailable when bypassed."),
                            (self.wid, "Horizontal time span of the waveform in microseconds. One PAL line lasts 64 µs."),
                            (self.start, "Move the waveform's zoomed window across the scan line.")):
            widget.setToolTip(tip)

        sp = W.QSplitter(QtCore.Qt.Horizontal)
        sp.addWidget(lw)
        sp.addWidget(rw)
        sp.setStretchFactor(0, 3)
        sp.setStretchFactor(1, 2)
        self.setCentralWidget(sp)
        self.panel.mode_changed.connect(self._control_mode)
        self._control_mode(False)
        self.resize(1500, 820)
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+O"), self, self.open_dialog)
        QtGui.QShortcut(QtGui.QKeySequence("Space"), self, self.toggle_play)
        QtGui.QShortcut(QtGui.QKeySequence("Right"), self, lambda: self.step(1))
        QtGui.QShortcut(QtGui.QKeySequence("Left"), self, lambda: self.step(-1))
        self.setStyleSheet("QMainWindow,QWidget{background:#101815;color:#cfe8da}"
                           "QPushButton,QComboBox,QSpinBox{background:#1b2b24;border:1px solid #2c5a46;padding:3px}"
                           "QToolBox::tab{background:#1b2b24;padding:6px}"
                           "QLineEdit{background:#09110e;border:1px solid #3c5c4d;padding:4px}"
                           "QToolTip{background:#ecf2e9;color:#13201a;border:1px solid #688477;padding:6px}"
                           "QPushButton{padding:7px;border-radius:3px}"
                           "QPushButton:hover{background:#2c4b3d;border:1px solid #7bc3a3}"
                           "QSlider::groove:horizontal{height:5px;background:#30473e;border-radius:2px}"
                           "QSlider::handle:horizontal{width:13px;margin:-5px 0;background:#a2ddbc;border-radius:4px}")

    def _control_mode(self, advanced):
        self.scope_widget.setVisible(advanced)
        self.chk_marker.setVisible(advanced)
        self.disp.setVisible(advanced)
        if not advanced:
            self.chk_marker.setChecked(False)
        if hasattr(self, "debounce"):
            self.debounce.start(150)

    # ------------------------------------------------------------------ source / transport
    def open_dialog(self):
        f, _ = W.QFileDialog.getOpenFileName(self, "Open video", "", "Video (*.mp4 *.mov *.mkv *.avi *.webm);;All (*)")
        if f:
            self.open_video(f)

    def open_video(self, path):
        try:
            src = VideoSource(path)
        except Exception as e:                       # noqa
            W.QMessageBox.warning(self, "Open", str(e))
            return
        if self.src:
            self.src.close()
        self.src, self.path = src, path
        if self.render_error is not None:
            self.retry_renderer()
        self.cur = 0
        self.seek.setRange(0, src.n_out - 1)
        self.playing = False
        self.btn_play.setText("Play")
        self.invalidate()
        self.setWindowTitle(f"PAL / VHS RCA monitor - {os.path.basename(path)}")

    def invalidate(self):
        self.gen += 1
        for f, _ in self.inflight.values():
            f.cancel()
        self.inflight.clear()
        self.cache.clear()
        self.tapcache.clear()
        self.shown_key = self.scope_key = self.spec_key = None
        self.buffering = self.buffering and self.playing

    def toggle_play(self):
        if not self.src or self.render_error is not None:
            return
        self.playing = not self.playing
        self.btn_play.setText("Pause" if self.playing else "Play")
        if self.playing:
            if self.cur >= self.src.n_out - 1:
                self.cur = 0
            if self.mode.currentIndex() == 1:
                self.target = min(self.cur + 125, self.src.n_out - 1)
                self.buffering = True
            else:
                self.target, self.buffering = None, False

    def on_seek(self, v):
        self.cur = v

    def step(self, d):
        if self.src:
            self.playing = False
            self.btn_play.setText("Play")
            self.cur = int(np.clip(self.cur + d, 0, self.src.n_out - 1))

    # ------------------------------------------------------------------ scheduler
    def renderer_failed(self,error):
        """One recovery attempt for a dead pool, otherwise latch until user retry."""
        logger().error('Preview render failure frame=%s backend=%s',self.cur,
                       self.renderer.backend,exc_info=(type(error),error,error.__traceback__))
        was_playing = self.playing
        self.playing = False
        self.buffering = False
        self.target = None
        self.btn_play.setText('Play')
        self.invalidate()
        if isinstance(error,BrokenExecutor) and self.renderer.recover():
            self.workers = self.renderer.workers
            self.render_notice = 'Worker exited; recovered using one background render thread. '
            self.lab_stat.setText(self.render_notice)
            self.playing = was_playing
            self.btn_play.setText('Pause' if was_playing else 'Play')
            return
        self.render_error = f'Renderer stopped: {error}. Logs: {log_directory()}'
        self.lab_stat.setText(self.render_error)
        self.btn_play.setEnabled(False)
        self.btn_retry.show()

    def retry_renderer(self):
        self.renderer.close()
        self.renderer = Renderer(self.requested_workers)
        self.workers = self.renderer.workers
        self.render_error = None
        self.render_notice = ''
        self.playing = self.buffering = False
        self.target = None
        self.invalidate()
        self.btn_play.setText('Play')
        self.btn_play.setEnabled(True)
        self.btn_retry.hide()

    def poll(self):
        for idx, (fut, g) in list(self.inflight.items()):
            if not fut.done():
                continue
            del self.inflight[idx]
            if fut.cancelled():
                continue
            try:
                rgb, taps = fut.result()
            except Exception as e:                   # noqa
                self.renderer_failed(e)
                return
            if g != self.gen:
                continue
            self.cache[idx] = rgb
            if taps:
                self.tapcache[idx] = taps
                while len(self.tapcache) > 2:
                    self.tapcache.popitem(last=False)
            self.stat_n += 1
            dt = time.time() - self.stat_t
            if dt > 1.5:
                self.fps_est, self.stat_n, self.stat_t = self.stat_n / dt, 0, time.time()

    def schedule(self):
        if self.render_error is not None:
            return
        n = self.src.n_out
        if self.playing:
            hi = self.target if self.target is not None else self.cur + self.workers * 3
            wanted = range(self.cur, min(hi, n - 1) + 1)
        else:
            wanted = [self.cur]
        for idx in wanted:
            if len(self.inflight) >= self.workers * 2:
                break
            # scope taps are ~15x the size of the picture: only the frame being inspected (paused) gets them
            need_taps = idx == self.cur and not self.playing and self.scope_widget.isVisible()
            if idx in self.inflight or (idx in self.cache and (idx in self.tapcache or not need_taps)):
                continue
            try:
                f1, f2 = self.src.fields(idx, self.params)
                future = self.renderer.submit(f1,f2,idx,self.params.to_dict(),need_taps)
                self.inflight[idx] = (future,self.gen)
            except Exception as e:
                self.renderer_failed(e)
                return
        for k in [k for k in self.cache if k < self.cur - 8 or k > self.cur + 150]:
            del self.cache[k]

    def advance(self):
        now = time.time()
        if self.buffering:
            have = sum(1 for i in range(self.cur, self.target + 1) if i in self.cache)
            self.lab_stat.setText(f"pre-rendering {have}/{self.target - self.cur + 1} frames ...")
            if have == self.target - self.cur + 1:
                self.buffering = False
            return
        interval = 0.04 if (self.target is not None or self.fps_est >= 25) else 0.0
        if now - self.t_last_adv >= interval and (self.cur + 1) in self.cache:
            self.cur += 1
            self.t_last_adv = now
        if self.cur >= (self.target if self.target is not None else self.src.n_out - 1) and (self.cur in self.cache):
            self.playing = False
            self.btn_play.setText("Play")

    def tick(self):
        if not self.src or self.render_error is not None:
            return
        self.poll()
        if self.render_error is not None:
            return
        if self.playing:
            self.advance()
        self.schedule()
        if self.render_error is not None:
            return
        key = (self.cur, self.gen, self.disp.currentIndex())
        if self.cur in self.cache and key != self.shown_key:
            self.shown_key = key
            self._redraw()
            self.update_scopes()
            self.seek.blockSignals(True)
            self.seek.setValue(self.cur)
            self.seek.blockSignals(False)
            t = self.cur / 25.0
            self.lab_pos.setText(f"frame {self.cur + 1}/{self.src.n_out}   t = {t:6.2f} s   "
                                 f"625 lines, 50 fields/s, field order TFF")
        if not (self.playing and self.buffering):
            self.lab_stat.setText(self.render_notice + f"render speed ~{self.fps_est:.1f} frames/s on {self.workers} render workers ({self.renderer.backend})   "
                                  f"cached {len(self.cache)} frames   "
                                  f"{'(playing slower than real time)' if self.playing and self.fps_est and self.fps_est < 25 else ''}")

    # ------------------------------------------------------------------ display / scopes
    def _redraw(self):
        rgb = self.cache.get(self.cur)
        if rgb is None:
            return
        m = self.disp.currentIndex()
        fi = self.field.currentIndex()
        ln = self.line.value() - C.ACTIVE_FIRST
        if m == 0:
            img, row = rgb, 2 * ln + fi
            tot = C.FRAME_H
        else:
            img, row, tot = rgb[m - 1::2], ln, C.ACTIVE_LINES
            if fi != m - 1:
                row = -1
        self.video.set_image(img)
        show = self.chk_marker.isChecked()
        self.video.marker = (row + 0.5) / tot if (show and 0 <= row < tot) else None
        self.video.update()

    def update_scopes(self):
        taps = self.tapcache.get(self.cur)
        key = (self.cur, self.gen, self.field.currentIndex(), self.line.value(),
               self.stage.currentData(), self.wid.currentData(), self.start.value())
        if key == self.scope_key:
            return
        if taps is None:
            if not self.playing:
                self.wave.set_traces([], (-0.5, 1.3), 0, 64, "waiting for render...")
            return
        self.scope_key = key
        fi, line = self.field.currentIndex(), self.line.value()
        skey = self.stage.currentData()
        _, rate, yr, trs = STAGES[skey]
        t = taps[fi]
        L = C.FIELD_LINES[fi]
        line = min(line, L - 1)
        traces, curves = [], []
        for tap, col in trs:
            if tap not in t:
                continue
            arr = t[tap].astype(np.float32)
            rate = len(arr) // (L * C.SPL)              # RF taps run at 2x or 1x depending on rf_rate
            n = C.SPL * rate
            seg = arr[line * n:(line + 1) * n]
            traces.append((np.arange(len(seg)) / (C.US * rate), seg, col))
        width = self.wid.currentData()
        x0 = (64 - width) * self.start.value() / 640.0
        msg = "stage not available (VHS bypass is on)" if not traces else ""
        self.wave.marks = True
        self.wave.set_traces(traces, yr, x0, x0 + width, msg)
        skey2 = (self.cur, self.gen, fi, skey)
        if skey2 != self.spec_key:
            self.spec_key = skey2
            for tap, col in trs:
                if tap in t:
                    f, db = welch_db(t[tap], C.FS * (len(t[tap]) // (L * C.SPL)))
                    curves.append((f, db, col))
            self.spec.set_curves(curves, 9.0, msg)

    # ------------------------------------------------------------------ export
    def export(self):
        if not self.path:
            return
        base = os.path.splitext(self.path)[0] + "_vhs.mp4"
        out, _ = W.QFileDialog.getSaveFileName(self, "Export", base, "MP4 (*.mp4)")
        if not out:
            return
        if not os.path.splitext(out)[1]:
            out += ".mp4"
        self.playing = False
        self.btn_play.setText("Play")
        self.timer.stop()
        self.invalidate()
        dlg = W.QProgressDialog("Rendering through the VCR...", "Cancel", 0, self.src.n_out, self)
        dlg.setWindowModality(QtCore.Qt.WindowModal)
        pdict = self.params.to_dict()
        if self.disp.currentIndex() > 0:                 # "Field 1/2 only" view selected: export that field, progressive
            pdict["export_fields"] = ["interlaced", "field 1 only", "field 2 only"][self.disp.currentIndex()]
        th = ExportWorker(self.path, out, pdict, self.workers)
        th.progress.connect(lambda d, n: dlg.setValue(d))
        th.failed.connect(lambda m: W.QMessageBox.warning(self, "Export", m))
        th.notice.connect(lambda m: W.QMessageBox.information(self, "Export note", m))
        th.finished.connect(dlg.close)
        th.finished.connect(lambda: self.timer.start(20))
        dlg.canceled.connect(lambda: setattr(th, "cancel", True))
        self.export_thread = th
        th.start()
        dlg.show()

    def closeEvent(self, e):
        self.timer.stop()
        self.renderer.close()
        if self.export_thread:
            self.export_thread.cancel = True
            self.export_thread.wait(3000)
        if self.src:
            self.src.close()
        super().closeEvent(e)


def run_gui(path=None, params=None, workers=None):
    app = W.QApplication.instance() or W.QApplication(sys.argv)
    w = MainWindow(path, params,workers=workers)
    w.show()
    app.exec()
