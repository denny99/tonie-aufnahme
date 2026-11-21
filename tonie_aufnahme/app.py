#!/usr/bin/env python3
"""Tonie-Aufnahme – Fenster-App: Spotify-Playlist aufnehmen, in Lieder schneiden, auf den Kreativ-Tonie laden."""
import glob
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recorder  # noqa: E402

from PySide6.QtCore import QObject, QSettings, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton,
                               QSizePolicy, QSlider, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

ACCENT = "#e4573d"
TONIE_URL = "https://my.tonies.com"
BILDER = Path(__file__).resolve().parent / "bilder"
ICON = BILDER / "app-icon.png"
HINTERGRUND = (BILDER / "hintergrund.jpg").as_posix()

STYLE = f"""
QWidget#root {{ border-image: url("{HINTERGRUND}") 0 0 0 0 stretch stretch; }}
QStackedWidget, QStackedWidget > QWidget {{ background: transparent; }}
QFrame[class="card"] {{ background: rgba(255, 255, 255, 215); border: 1px solid #ecd6cc; border-radius: 14px; }}
QLineEdit {{ padding: 4px 10px; border-radius: 8px; border: 1px solid palette(mid); background: palette(window); font-size: 14px; }}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QLabel[class="h1"] {{ font-size: 22px; font-weight: 600; }}
QLabel[class="h2"] {{ font-size: 14px; font-weight: 600; }}
QLabel[class="muted"] {{ color: palette(placeholder-text); }}
QLabel[class="big"] {{ font-size: 34px; font-weight: 600; }}
QLabel[class="ok"] {{ color: #4caf7a; }}
QLabel[class="warn"] {{ color: #e0a030; }}
QPushButton {{ padding: 7px 14px; border-radius: 10px; background: palette(button); border: 1px solid palette(mid); }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton#primary {{ background: {ACCENT}; color: white; font-size: 15px; font-weight: 600;
                       padding: 12px 22px; border: none; }}
QPushButton#primary:hover {{ background: #ef6a50; }}
QPushButton#primary:disabled {{ background: palette(mid); color: palette(placeholder-text); }}
QPushButton#stop {{ background: palette(button); border: 2px solid {ACCENT}; color: {ACCENT};
                    font-size: 15px; font-weight: 600; padding: 10px 22px; }}
QPushButton[class="preset"] {{ padding: 6px 12px; border: 1px solid palette(mid); background: palette(button); }}
QPushButton[class="preset"]:checked {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}
QProgressBar {{ border: none; border-radius: 6px; background: palette(mid); height: 12px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 6px; }}
QListWidget {{ border: none; background: transparent; font-size: 13px; }}
QListWidget::item {{ border-bottom: 1px solid palette(midlight); }}
QListWidget::item:selected, QListWidget::item:hover {{ background: transparent; }}
QPushButton[class="zeile"] {{ padding: 3px 10px; font-size: 12px; }}
"""


def mmss(sek):
    sek = max(0, int(sek))
    return f"{sek // 60}:{sek % 60:02d}"


def lbl(text="", cls=None, wrap=False):
    l = QLabel(text)
    if cls:
        l.setProperty("class", cls)
    l.setWordWrap(wrap)
    return l


def knopf(text, bild, gross=False, **kw):
    b = QPushButton(text, **kw)
    if (BILDER / f"{bild}.png").exists():
        b.setIcon(QIcon(str(BILDER / f"{bild}.png")))
        b.setIconSize(QSize(30, 30) if gross else QSize(22, 22))
    return b


def card():
    f = QFrame()
    f.setProperty("class", "card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(10)
    return f, lay


def crossfade_an():
    """True/False aus Spotifys prefs-Datei, None wenn nicht lesbar."""
    werte = []
    for p in glob.glob(str(Path.home() / ".config/spotify/Users/*/prefs")):
        try:
            for z in open(p, encoding="utf-8"):
                if z.startswith("audio.crossfade_v2="):
                    werte.append(z.strip().endswith("true"))
        except OSError:
            pass
    return any(werte) if werte else None


class Arbeiter(QObject):
    ereignis = Signal(str, dict)
    fehler = Signal(str)
    erledigt = Signal()

    def __init__(self, **opts):
        super().__init__()
        self.opts, self.stopp = opts, threading.Event()

    def run(self):
        try:
            recorder.aufnehmen(**self.opts, stopp=self.stopp,
                               melde=lambda art, **d: self.ereignis.emit(art, d))
        except Exception as e:  # noqa: BLE001 – jeder Fehler gehört ins Fenster
            self.fehler.emit(str(e))
        self.erledigt.emit()


class Fenster(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tonie-Aufnahme")
        self.setWindowIcon(QIcon(str(ICON)))
        self.resize(580, 900)
        self.setMinimumSize(520, 880)
        self.cfg = QSettings("tonie-aufnahme", "app")
        self.thread = self.arbeiter = None
        self.stack = QStackedWidget()
        root = QWidget(objectName="root")
        lay = QVBoxLayout(root)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.addWidget(self.stack)
        self.setCentralWidget(root)
        self.stack.addWidget(self._seite_vorbereiten())
        self.stack.addWidget(self._seite_aufnahme())
        self.stack.addWidget(self._seite_fertig())
        self.poll = QTimer(self, interval=1500, timeout=self._spotify_pruefen)
        self.poll.start()
        self.uhr = QTimer(self, interval=250, timeout=self._uhr)
        self._spotify_pruefen()

    # ---------- Seite 1: vorbereiten ----------
    def _seite_vorbereiten(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(14)
        kopf = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(str(ICON)).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        kopf.addWidget(logo)
        kopf.addWidget(lbl("Tonie-Aufnahme", "h1"), 1)
        v.addLayout(kopf)
        v.addWidget(lbl("Nimmt eine Spotify-Playlist auf und macht daraus einzelne MP3s "
                        "für den Kreativ-Tonie.", "muted", True))

        c, cl = card()
        cl.addWidget(lbl("1  Spotify", "h2"))
        self.sp_status = lbl("", wrap=True)
        cl.addWidget(self.sp_status)
        self.sp_btn = knopf("Spotify öffnen", "spotify")
        self.sp_btn.clicked.connect(self._spotify_starten)
        h = QHBoxLayout()
        h.addWidget(self.sp_btn)
        h.addStretch()
        cl.addLayout(h)
        self.chk_zufall = lbl("", wrap=True)
        self.chk_cross = lbl("", wrap=True)
        cl.addWidget(self.chk_zufall)
        cl.addWidget(self.chk_cross)
        cl.addWidget(lbl("Klick in Spotify das erste Lied deiner Playlist an. Die Aufnahme startet "
                         "es von vorn.", "muted", True))
        v.addWidget(c)

        c, cl = card()
        cl.addWidget(lbl("2  Wie lang?", "h2"))
        h = QHBoxLayout()
        self.min_slider = QSlider(Qt.Horizontal, minimum=5, maximum=90, singleStep=5, pageStep=10)
        self.min_spin = QSpinBox(minimum=1, maximum=90, suffix=" min")
        self.min_slider.valueChanged.connect(self.min_spin.setValue)
        self.min_spin.valueChanged.connect(self._minuten_geaendert)
        h.addWidget(self.min_slider, 1)
        h.addWidget(self.min_spin)
        cl.addLayout(h)
        h = QHBoxLayout()
        self.presets = QButtonGroup(self)
        for m, t in ((30, "30 min"), (60, "60 min"), (90, "90 min · voller Tonie")):
            b = QPushButton(t, checkable=True)
            b.setProperty("class", "preset")
            b.clicked.connect(lambda _=False, m=m: self.min_spin.setValue(m))
            self.presets.addButton(b, m)
            h.addWidget(b)
        h.addStretch()
        cl.addLayout(h)
        cl.addWidget(lbl("Es kommen nur ganze Lieder drauf: Das Lied, das nicht mehr passt, "
                         "wird nicht mehr aufgenommen.", "muted", True))
        v.addWidget(c)

        c, cl = card()
        cl.addWidget(lbl("3  Speichern", "h2"))
        self.name = QLineEdit(placeholderText="Name der Aufnahme, z. B. Weihnachten")
        self.name.setMinimumHeight(34)
        self.name.textChanged.connect(lambda _: self._ziel_setzen(self.ziel_pfad))
        cl.addWidget(self.name)
        h = QHBoxLayout()
        self.ziel = lbl("", wrap=True)
        b = QPushButton("Ändern …")
        b.clicked.connect(self._ziel_waehlen)
        h.addWidget(self.ziel, 1)
        h.addWidget(b)
        cl.addLayout(h)
        self.alt_info = lbl("", "muted", True)
        self.alt_info.setMinimumHeight(40)
        self.fortsetzen = QCheckBox("Vorhandene Lieder behalten und weitermachen")
        self.fortsetzen.setChecked(True)
        self.fortsetzen.toggled.connect(lambda _: self._alt_pruefen())
        cl.addWidget(self.alt_info)
        cl.addWidget(self.fortsetzen)
        self.mithoeren = QCheckBox("Während der Aufnahme mithören")
        cl.addWidget(self.mithoeren)
        v.addWidget(c)

        v.addStretch()
        self.start_btn = knopf("Aufnahme starten", "start", True, objectName="primary")
        self.start_btn.clicked.connect(self._start)
        v.addWidget(self.start_btn)
        self.start_hinweis = lbl("", "muted", True)
        self.start_hinweis.setAlignment(Qt.AlignCenter)
        v.addWidget(self.start_hinweis)

        self.min_spin.setValue(int(self.cfg.value("minuten", 90)))
        self.min_slider.setValue(self.min_spin.value())
        self._ziel_setzen(self.cfg.value("ziel", str(recorder.standard_ziel())))
        self.mithoeren.setChecked(self.cfg.value("mithoeren", "false") == "true")
        return w

    def _minuten_geaendert(self, m):
        self.min_slider.blockSignals(True)
        self.min_slider.setValue(m)
        self.min_slider.blockSignals(False)
        for b in self.presets.buttons():
            b.setChecked(self.presets.id(b) == m)

    def _ziel_setzen(self, pfad):
        self.ziel_pfad = pfad
        name = self.name.text().strip() if hasattr(self, "name") else ""
        self.ziel.setText(pfad.replace(str(Path.home()), "~") + "/" + (name or "<Datum>"))
        self._alt_pruefen()

    def _alt_pruefen(self):
        """Liegen im gewählten Ordner schon Lieder? Dann Fortsetzen anbieten."""
        if not hasattr(self, "fortsetzen"):
            return
        name = self.name.text().strip()
        self.alt = recorder.vorhandene(recorder.ordner_fuer(self.ziel_pfad, name)) if name else []
        da = bool(self.alt)
        self.fortsetzen.setVisible(da)
        self.alt_info.setVisible(da)
        if da:
            minuten = sum(l["laenge"] for l in self.alt) / 60
            if self.fortsetzen.isChecked():
                self.alt_info.setText(f"Hier liegen schon {len(self.alt)} Lieder ({minuten:.0f} min). Starte die "
                                      "Playlist von vorn: Vorhandene werden übersprungen, der Rest kommt dazu.")
            else:
                self.alt_info.setText(f"Neue Aufnahme in „{name} (2)“, die {len(self.alt)} vorhandenen "
                                      "Lieder bleiben unberührt.")

    def _ziel_waehlen(self):
        p = QFileDialog.getExistingDirectory(self, "Speicherort wählen", self.ziel_pfad)
        if p:
            self._ziel_setzen(p)

    def _spotify_starten(self):
        """Spotify öffnen, egal ob als Arch-Paket, .deb/Snap oder Flatpak installiert."""
        import shutil
        for befehl in (["spotify-launcher"], ["spotify"], ["flatpak", "run", "com.spotify.Client"]):
            if shutil.which(befehl[0]) and (befehl[0] != "flatpak" or subprocess.run(
                    ["flatpak", "info", "com.spotify.Client"], capture_output=True).returncode == 0):
                subprocess.Popen(befehl, start_new_session=True)
                return
        QMessageBox.information(self, "Spotify fehlt",
                                "Die Spotify-App ist nicht installiert. Installiere sie über die Softwareverwaltung "
                                "deines Systems (z. B. „Spotify“ in Discover oder GNOME Software) und versuch es noch einmal.")

    def _spotify_pruefen(self):
        if self.stack.currentIndex() != 0:
            return
        status, song = recorder.spotify_info()
        bereit = status is not None and song.strip(" –") != ""
        fehlt = recorder.fehlende_programme()
        if fehlt:
            status, bereit = None, False
            self.sp_status.setText("Auf diesem Rechner fehlt noch: " + ", ".join(fehlt)
                                   + ". Installiere es (siehe README) und starte die App neu.")
            self.sp_status.setProperty("class", "warn")
        elif status is None:
            self.sp_status.setText("Spotify ist nicht offen.")
            self.sp_status.setProperty("class", "warn")
        elif not bereit:
            self.sp_status.setText("Spotify ist offen – such dir die Playlist aus und klick das erste Lied an.")
            self.sp_status.setProperty("class", "warn")
        else:
            icon = "▶" if status == "Playing" else "⏸"
            self.sp_status.setText(f"{icon}  Startet mit: {song}")
            self.sp_status.setProperty("class", "ok")
        self.sp_btn.setVisible(status is None)
        self.sp_status.style().polish(self.sp_status)

        zufall = recorder.pc("shuffle").stdout.strip() if status else ""
        self._check(self.chk_zufall, zufall != "On",
                    "Zufallswiedergabe ist aus" if zufall == "Off" else "Zufallswiedergabe aus",
                    "Zufallswiedergabe ist an – in Spotify ausschalten, sonst stimmt die Reihenfolge nicht")
        cf = crossfade_an()
        self._check(self.chk_cross, cf is False,
                    "Crossfade ist aus",
                    "Crossfade ist an – in Spotify ausschalten"
                    if cf else "Crossfade und Automix in Spotify aus? (Einstellungen → Wiedergabe)")
        self.start_btn.setEnabled(bereit)
        self.start_hinweis.setText("" if bereit else "Starten geht, sobald Spotify ein Lied ausgewählt hat.")

    @staticmethod
    def _check(label, ok, text_ok, text_warn):
        label.setText(("✓  " + text_ok) if ok else ("!  " + text_warn))
        label.setProperty("class", "ok" if ok else "warn")
        label.style().polish(label)

    # ---------- Seite 2: Aufnahme ----------
    def _seite_aufnahme(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(14)
        self.auf_titel = lbl("Aufnahme läuft", "h1")
        v.addWidget(self.auf_titel)
        c, cl = card()
        self.auf_zeit = lbl("0:00", "big")
        self.auf_von = lbl("von 90:00", "muted")
        h = QHBoxLayout()
        h.addWidget(self.auf_zeit)
        h.addWidget(self.auf_von, 0, Qt.AlignBottom)
        h.addStretch()
        cl.addLayout(h)
        self.auf_bar = QProgressBar(textVisible=False)
        cl.addWidget(self.auf_bar)
        self.auf_jetzt = lbl("Warte auf Spotify …", wrap=True)
        self.auf_jetzt.setFont(QFont(self.font().family(), 13))
        cl.addWidget(self.auf_jetzt)
        v.addWidget(c)
        c, cl = card()
        cl.addWidget(lbl("Aufgenommen", "h2"))
        self.auf_liste = QListWidget()
        self.auf_liste.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        cl.addWidget(self.auf_liste, 1)
        v.addWidget(c, 1)
        self.auf_hinweis = lbl("Spotify spielt gerade stumm in die Aufnahme. Bitte nichts in Spotify "
                               "anklicken, bis die Aufnahme fertig ist.", "muted", True)
        v.addWidget(self.auf_hinweis)
        self.stop_btn = knopf("Aufnahme beenden", "stop", True, objectName="stop")
        self.stop_btn.clicked.connect(self._stop)
        v.addWidget(self.stop_btn)
        return w

    def _start(self):
        m = self.min_spin.value()
        self.cfg.setValue("minuten", m)
        self.cfg.setValue("ziel", self.ziel_pfad)
        self.cfg.setValue("mithoeren", "true" if self.mithoeren.isChecked() else "false")
        self.limit, self.lied_start, self.cur = m * 60, None, None
        self.lieder, self.verwerfen = {}, set()
        self.auf_liste.clear()
        self._alt_pruefen()
        if self.fortsetzen.isChecked():
            for l in self.alt:
                key = f"alt{l['nr']}"
                self.lieder[key] = {"len": l["laenge"], "zustand": "da", "zeile": self._zeile_neu(
                    key, f"{l['nr']:>2}.  {l['interpret']} – {l['titel']}   ({mmss(l['laenge'])})")}
                self._zustand(key, "da")
        self.auf_titel.setText("Aufnahme läuft")
        self.auf_von.setText(f"von {mmss(self.limit)}")
        self.auf_bar.setRange(0, self.limit)
        self.auf_bar.setValue(0)
        self.auf_zeit.setText("0:00")
        self.auf_jetzt.setText("Spotify wird vorbereitet …")
        self.auf_hinweis.setVisible(True)
        self.stop_btn.setEnabled(True)
        self.stop_btn.setText("Aufnahme beenden")
        self.stack.setCurrentIndex(1)

        self.thread = QThread(self)
        self.arbeiter = Arbeiter(minuten=m, ziel=self.ziel_pfad, mithoeren=self.mithoeren.isChecked(),
                                 name=self.name.text().strip() or None, verwerfen=self.verwerfen,
                                 fortsetzen=self.fortsetzen.isChecked())
        self.arbeiter.moveToThread(self.thread)
        self.thread.started.connect(self.arbeiter.run)
        self.arbeiter.ereignis.connect(self._ereignis)
        self.arbeiter.fehler.connect(self._fehler)
        self.arbeiter.erledigt.connect(self.thread.quit)
        self.thread.start()
        self.uhr.start()

    def _stop(self):
        if self.arbeiter:
            self.arbeiter.stopp.set()
            self.stop_btn.setEnabled(False)
            self.stop_btn.setText("Wird beendet …")

    def _behalten_sek(self):
        return sum(l["len"] for l in self.lieder.values() if l["zustand"] in ("ok", "da"))

    def _uhr(self):
        l = self.lieder.get(self.cur)
        lauf = min(time.monotonic() - self.lied_start, l["len"]) if l and l["zustand"] == "laeuft" else 0
        t = self._behalten_sek() + lauf
        self.auf_zeit.setText(mmss(t))
        self.auf_bar.setValue(int(min(t, self.limit)))

    # Eine Zeile je Lied: Zustand, Titel, Knopf (Überspringen / Verwerfen / Zurückholen)
    ZUSTAND = {"laeuft": ("●", "Überspringen", "Dieses Lied überspringen, es kommt nicht auf den Tonie"),
               "ok": ("✓", "Verwerfen", "Dieses Lied nicht speichern"),
               "weg": ("✗", "Zurückholen", "Doch speichern"),
               "skip": ("⏭", None, None),
               "da": ("✓", None, None)}

    def _zeile_neu(self, nr, text):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(4, 2, 4, 2)
        icon, label, btn = QLabel(), QLabel(text), QPushButton()
        icon.setFixedWidth(18)
        label.setTextFormat(Qt.PlainText)
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)  # lange Titel abschneiden statt scrollen
        btn.setProperty("class", "zeile")
        btn.clicked.connect(lambda: self._zeile_klick(nr))
        h.addWidget(icon)
        h.addWidget(label, 1)
        h.addWidget(btn)
        it = QListWidgetItem()
        it.setSizeHint(QSize(0, w.sizeHint().height()))
        self.auf_liste.addItem(it)
        self.auf_liste.setItemWidget(it, w)
        self.auf_liste.scrollToBottom()
        return {"icon": icon, "label": label, "btn": btn, "text": text}

    def _zustand(self, nr, zustand, zusatz=""):
        l = self.lieder.get(nr)
        if not l:
            return
        l["zustand"] = zustand
        icon, knopf, tip = self.ZUSTAND[zustand]
        z = l["zeile"]
        z["icon"].setText(icon)
        z["label"].setText(z["text"] + zusatz)
        f = z["label"].font()
        f.setStrikeOut(zustand in ("weg", "skip"))
        z["label"].setFont(f)
        z["label"].setProperty("class", "muted" if zustand in ("weg", "skip", "da") else None)
        z["label"].style().polish(z["label"])
        z["btn"].setVisible(knopf is not None and self.stop_btn.isEnabled())
        if knopf:
            z["btn"].setText(knopf)
            z["btn"].setToolTip(tip)

    def _zeile_klick(self, nr):
        z = self.lieder[nr]["zustand"]
        if z == "laeuft":
            self.verwerfen.add(nr)
            self._zustand(nr, "weg", "  – übersprungen")
            self.lieder[nr]["zeile"]["btn"].setVisible(False)  # nicht ganz aufgenommen, nicht zurückholbar
            recorder.pc("next")
        elif z == "ok":
            self.verwerfen.add(nr)
            self._zustand(nr, "weg")
        elif z == "weg" and self.lieder[nr].get("fertig"):
            self.verwerfen.discard(nr)
            self._zustand(nr, "ok")

    def _letztes_fertig(self):
        l = self.lieder.get(self.cur)
        if l:
            l["fertig"] = True
            if l["zustand"] == "laeuft":
                self._zustand(self.cur, "ok")
            elif "übersprungen" in l["zeile"]["label"].text():
                l["fertig"] = False

    def _ereignis(self, art, d):
        if art == "lied":
            self._letztes_fertig()
            self.cur, self.lied_start = d["nr"], time.monotonic()
            self.auf_jetzt.setText(f"♪  {d['interpret']} – {d['titel']}")
            self.lieder[d["nr"]] = {"len": d["laenge"], "zustand": "laeuft",
                                    "zeile": self._zeile_neu(d["nr"], f"{d['nr']:>2}.  {d['interpret']} – "
                                                                      f"{d['titel']}   ({mmss(d['laenge'])})")}
            self._zustand(d["nr"], "laeuft")
        elif art == "uebersprungen":
            l = self.lieder.get(d["nr"])
            if l and "übersprungen" not in l["zeile"]["label"].text():
                self._zustand(d["nr"], "skip", "  – nicht ganz gelaufen")
            if l:
                l["fertig"] = False
        elif art == "vorhanden":
            self._letztes_fertig()
            self.cur = None
            self.auf_jetzt.setText(f"⏩  Schon da, übersprungen: {d['interpret']} – {d['titel']}")
        elif art == "werbung":
            self._letztes_fertig()
            self.cur = None
            self.auf_jetzt.setText("Werbung – wird nicht aufgenommen")
        elif art == "limit":
            self._letztes_fertig()
            self.cur = None
            self.auf_jetzt.setText(f"Limit erreicht – „{d['titel']}“ hätte nicht mehr gepasst.")
        elif art == "ende":
            self._letztes_fertig()
            self.uhr.stop()
            self.cur = None
            self.auf_titel.setText("Lieder werden geschnitten …")
            self.auf_hinweis.setVisible(False)
            self.stop_btn.setEnabled(False)
            self.stop_btn.setText("Bitte warten …")
            self.auf_jetzt.setText(d["grund"])
            for l in self.lieder.values():
                l["zeile"]["btn"].setVisible(False)
        elif art == "schneide":
            self.auf_jetzt.setText(f"Schneide {d['i']} von {d['von']}: {d['titel']}")
        elif art == "fertig":
            self._fertig(d)

    def _fehler(self, text):
        self.uhr.stop()
        QMessageBox.warning(self, "Aufnahme nicht möglich", text)
        self.stack.setCurrentIndex(0)

    # ---------- Seite 3: fertig ----------
    def _seite_fertig(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(14)
        v.addStretch()
        self.f_titel = lbl("Fertig!", "h1")
        self.f_titel.setAlignment(Qt.AlignCenter)
        v.addWidget(self.f_titel)
        self.f_info = lbl("", "big")
        self.f_info.setAlignment(Qt.AlignCenter)
        v.addWidget(self.f_info)
        self.f_pfad = lbl("", "muted", True)
        self.f_pfad.setAlignment(Qt.AlignCenter)
        v.addWidget(self.f_pfad)
        c, cl = card()
        cl.addWidget(lbl("So kommen die Lieder auf den Tonie", "h2"))
        cl.addWidget(lbl("1.  „Zu my.tonies.com“ öffnen und den Kreativ-Tonie auswählen.\n"
                         "2.  Die MP3s aus dem Ordner ins Fenster ziehen.\n"
                         "3.  Tonie auf die Box stellen – sie lädt die Lieder über WLAN.", wrap=True))
        v.addWidget(c)
        h = QHBoxLayout()
        b = knopf("Ordner öffnen", "ordner")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.f_ordner))))
        h.addWidget(b)
        b = knopf("Zu my.tonies.com", "tonie", objectName="primary")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(TONIE_URL)))
        h.addWidget(b)
        v.addLayout(h)
        b = knopf("Neue Aufnahme", "neu")
        b.clicked.connect(lambda: (self.stack.setCurrentIndex(0), self._spotify_pruefen()))
        v.addWidget(b)
        v.addStretch()
        return w

    def _fertig(self, d):
        self.f_ordner = d["ordner"]
        n = d["anzahl"]
        if n == 0:
            self.f_titel.setText("Nichts aufgenommen")
            self.f_info.setText("0 Lieder")
            self.f_pfad.setText("Es ist kein Lied vollständig durchgelaufen.")
        else:
            self.f_titel.setText("Fertig!")
            self.f_info.setText(f"{n} Lieder · {d['minuten']:.0f} min")
            neu = f"{d['neu']} neu · " if d.get("neu", n) != n else ""
            self.f_pfad.setText(neu + str(d["ordner"]).replace(str(Path.home()), "~"))
        self.stack.setCurrentIndex(2)

    def closeEvent(self, e):
        if self.thread and self.thread.isRunning():
            if QMessageBox.question(self, "Aufnahme läuft",
                                    "Aufnahme beenden und fertige Lieder speichern?") != QMessageBox.Yes:
                e.ignore()
                return
            self._stop()
            self.thread.wait(120000)
        e.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Tonie-Aufnahme")
    app.setDesktopFileName("tonie-aufnahme")
    app.setStyle("Fusion")
    pal = QPalette()
    for rolle, farbe in ((QPalette.Window, "#fff6ef"), (QPalette.WindowText, "#3b2b26"), (QPalette.Base, "#ffffff"),
                         (QPalette.AlternateBase, "#fdeee6"), (QPalette.Text, "#3b2b26"), (QPalette.Button, "#ffffff"),
                         (QPalette.ButtonText, "#3b2b26"), (QPalette.Mid, "#e8cfc4"), (QPalette.Midlight, "#f3e2da"),
                         (QPalette.PlaceholderText, "#8a726a"), (QPalette.Highlight, ACCENT),
                         (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, "#fff6ef"),
                         (QPalette.ToolTipText, "#3b2b26")):
        pal.setColor(rolle, QColor(farbe))
    app.setPalette(pal)
    app.setStyleSheet(STYLE)
    f = Fenster()
    f.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
