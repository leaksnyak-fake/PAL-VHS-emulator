"""Cassette-front easy controls over the shared Params instance."""
from PySide6 import QtCore, QtGui, QtWidgets as W
from .experience import MACROS, macro_position, set_macro
from .headswitch import DECK_PROFILES, apply_deck_profile


class Cassette(W.QWidget):
    def __init__(self, params, parent=None):
        super().__init__(parent)
        self.params = params
        self.setMinimumHeight(125)
        self.setToolTip("Virtual cassette. Add damage with the buttons below; changes affect the whole clip and are saved with your settings.")

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(6, 6, self.width()-12, self.height()-12)
        p.setPen(QtGui.QColor("#50616b"))
        p.setBrush(QtGui.QColor("#182127"))
        p.drawRoundedRect(r, 10, 10)
        p.setBrush(QtGui.QColor("#c6c9b9"))
        p.drawRoundedRect(QtCore.QRectF(22, 17, self.width()-44, 29), 3, 3)
        p.setPen(QtGui.QColor("#20292c"))
        p.drawText(QtCore.QRectF(30, 17, self.width()-60, 29), QtCore.Qt.AlignCenter,
                   f"PAL  /  {self.params.tape_speed}     HOME VIDEO")
        for x in (self.width()*.28, self.width()*.72):
            p.setPen(QtGui.QColor("#65727a"))
            p.setBrush(QtGui.QColor("#0b1115"))
            p.drawEllipse(QtCore.QPointF(x, 76), 24, 24)
            p.setBrush(QtGui.QColor("#9aabb0"))
            p.drawEllipse(QtCore.QPointF(x, 76), 9, 9)
        p.setPen(QtGui.QColor("#7c9999"))
        p.drawText(QtCore.QRectF(15, 104, self.width()-30, 18), QtCore.Qt.AlignCenter,
                   "V H S    •    625 / 50    •    COLOUR UNDER")


class EasyPanel(W.QWidget):
    changed = QtCore.Signal()

    def __init__(self, params):
        super().__init__()
        self.params = params
        self.sliders = {}
        self.history = []
        v = W.QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        self.cassette = Cassette(params)
        v.addWidget(self.cassette)
        hint = W.QLabel("YOUR TAPE, YOUR DAMAGE\nChoose a preset above, then tune the cassette.")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self.deck = W.QComboBox()
        self.deck.addItems(list(DECK_PROFILES))
        self.deck.setCurrentText('Domestic 2-head / aligned')
        self.deck.setSizeAdjustPolicy(W.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.deck.setMinimumContentsLength(18)
        self.deck.setToolTip('Choose a playback deck, then Apply deck. Preserves tape condition and source. Head count is not a quality guarantee.')
        for i,(name,(tip,values)) in enumerate(DECK_PROFILES.items()):
            self.deck.setItemData(i,tip,QtCore.Qt.ToolTipRole)
        deck_row = W.QHBoxLayout()
        deck_row.addWidget(self.deck,1)
        b = W.QPushButton('Apply deck')
        b.setToolTip('Apply playback settings only. Undo reverses this button action too.')
        b.clicked.connect(self._apply_deck)
        deck_row.addWidget(b)
        v.addLayout(deck_row)
        row = W.QHBoxLayout()
        row.addWidget(W.QLabel("Record speed"))
        self.speed = W.QComboBox()
        self.speed.addItems(["SP", "LP", "EP"])
        self.speed.setToolTip("SP: everyday PAL VHS. LP: longer recording, more noise. EP: optional legacy model; availability depends on the real deck.")
        self.speed.currentTextChanged.connect(self._speed)
        row.addWidget(self.speed, 1)
        v.addLayout(row)
        for name, (label, tip, mapping) in MACROS.items():
            line = W.QHBoxLayout()
            title = W.QLabel(label)
            title.setMinimumWidth(105)
            sl = W.QSlider(QtCore.Qt.Horizontal)
            sl.setRange(0, 100)
            val = W.QLabel()
            val.setMinimumWidth(35)
            for w in (title, sl, val):
                w.setToolTip(tip + "\nThis is a macro controlling several Advanced parameters. Moving it replaces that family only.")
            sl.valueChanged.connect(lambda x, name=name: self._macro(name, x))
            self.sliders[name] = (sl, val)
            line.addWidget(title)
            line.addWidget(sl, 1)
            line.addWidget(val)
            v.addLayout(line)
        snow_row = W.QHBoxLayout()
        snow_row.addWidget(W.QLabel('Head-switch snow'))
        self.snow_strength = W.QSlider(QtCore.Qt.Horizontal)
        self.snow_strength.setRange(0,100)
        self.snow_strength.setToolTip('Visible narrow head-switch snow strength. Set above zero to see it; width, height and motion are in Advanced / Head switching.')
        self.snow_strength.valueChanged.connect(self._snow_strength)
        snow_row.addWidget(self.snow_strength,1)
        self.snow_motion = W.QCheckBox('Moving')
        self.snow_motion.setToolTip('Move the snow horizontally while playing or stepping frames. Does not enable image-line jitter. Advanced provides drift, scatter and sweep settings.')
        self.snow_motion.toggled.connect(self._snow_motion)
        snow_row.addWidget(self.snow_motion)
        v.addLayout(snow_row)
        line = W.QHBoxLayout()
        title = W.QLabel("Tracking − / +")
        self.tracking = W.QSlider(QtCore.Qt.Horizontal)
        self.tracking.setRange(-100, 100)
        self.track_value = W.QLabel()
        self.tracking.setToolTip("0 = aligned. Negative adds noise from the bottom; positive from the top. Independent of the moving smear band.")
        self.tracking.valueChanged.connect(self._tracking)
        line.addWidget(title)
        line.addWidget(self.tracking, 1)
        line.addWidget(self.track_value)
        v.addLayout(line)
        actions = W.QGridLayout()
        for i, (label, action, tip) in enumerate([
            ("+ Smear", "smear", "Increase the travelling tracking smear by 15%."),
            ("+ Crease", "crease", "Increase ordinary crease severity by 15%."),
            ("+ Dropouts", "dropouts", "Add two expected dropout events per frame. DOC can conceal some losses."),
            ("White band", "white", "Toggle recurring travelling white crease bands."),
            ("Undo", "undo", "Undo the last damage-button action. Slider edits are not added to this history."),
            ("Repair damage", "repair", "Remove deliberate tape damage, tracking errors, dropouts, and RF wear; preserve colour and wobble settings."),
        ]):
            b = W.QPushButton(label)
            b.setToolTip(tip + " Effects apply to the whole clip, not just the current time.")
            b.clicked.connect(lambda checked=False, action=action: self.damage(action))
            actions.addWidget(b, i//2, i%2)
        v.addLayout(actions)
        self.status = W.QLabel()
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        note = W.QLabel("Macro positions follow the first Advanced parameter in each family.\nDamage is repeatable across preview and export. Audio passes through unchanged.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#91a6af;font-size:11px")
        v.addWidget(note)
        v.addStretch()
        self.refresh()

    def _speed(self, value):
        self.params.set("tape_speed", value)
        self.cassette.update()
        self.changed.emit()

    def _apply_deck(self):
        before = self.params.to_dict()
        apply_deck_profile(self.params,self.deck.currentText())
        self.history.append({k:v for k,v in before.items() if getattr(self.params,k) != v})
        self.history = self.history[-20:]
        self.refresh()
        self.changed.emit()

    def _macro(self, name, amount):
        set_macro(self.params, name, amount)
        self.refresh()
        self.changed.emit()

    def _snow_strength(self,value):
        self.params.set('hs_residual',value/100)
        self.refresh()
        self.changed.emit()

    def _snow_motion(self,moving):
        self.params.set('hs_residual_motion','Drift + jitter' if moving else 'Stationary')
        self.refresh()
        self.changed.emit()

    def _tracking(self, value):
        self.params.set("tracking", value/100)
        self.refresh()
        self.changed.emit()

    def damage(self, action):
        if action == "undo":
            if not self.history:
                return
            self.params.update(self.history.pop())
        else:
            before = self.params.to_dict()
            if action in ("smear", "crease"):
                set_macro(self.params, action, macro_position(self.params, action)+15)
            elif action == "dropouts":
                self.params.set("dropout_rate", self.params.dropout_rate+2)
            elif action == "white":
                self.params.set("wr_travel", not self.params.wr_travel)
            elif action == "repair":
                set_macro(self.params, "wear", 0)
                set_macro(self.params, "smear", 0)
                set_macro(self.params, "crease", 0)
                self.params.update(dict(tracking=0, wr_travel=False, snow_sparse=0))
            self.history.append({k: v for k, v in before.items() if getattr(self.params, k) != v})
            self.history = self.history[-20:]
        self.refresh()
        self.changed.emit()

    def refresh(self):
        self.snow_strength.blockSignals(True)
        self.snow_strength.setValue(round(self.params.hs_residual*100))
        self.snow_strength.blockSignals(False)
        self.snow_motion.blockSignals(True)
        self.snow_motion.setChecked(self.params.hs_residual_motion != 'Stationary')
        self.snow_motion.blockSignals(False)
        active = self.params.hs_model == 'RF switch' and not self.params.bypass_tape
        self.snow_strength.setEnabled(active)
        self.snow_motion.setEnabled(active)
        self.speed.blockSignals(True)
        self.speed.setCurrentText(self.params.tape_speed)
        self.speed.blockSignals(False)
        for name, (sl, label) in self.sliders.items():
            x = macro_position(self.params, name)
            sl.blockSignals(True)
            sl.setValue(x)
            sl.blockSignals(False)
            label.setText(f"{x}%")
        self.tracking.blockSignals(True)
        self.tracking.setValue(round(self.params.tracking*100))
        self.tracking.blockSignals(False)
        self.track_value.setText(f"{self.params.tracking:+.2f}")
        self.status.setText(f"White bands: {'ON' if self.params.wr_travel else 'OFF'}  •  Dropouts: {self.params.dropout_rate:g}/frame"
                            + ("\nVHS bypass is ON — tape controls are inactive." if self.params.bypass_tape else ""))
        self.cassette.update()
