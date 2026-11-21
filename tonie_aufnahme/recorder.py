"""Kern der Tonie-Aufnahme: nimmt Spotify in Echtzeit auf und schneidet die Lieder in MP3s.

Spotify spielt währenddessen auf ein eigenes, stummes Gerät (null sink); parec nimmt dessen Monitor auf.
Liedwechsel kommen über MPRIS (playerctl). Geschnitten wird an der Byte-Position des Rohstroms.
"""
import json
import queue
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

SINK = "tonie_aufnahme"
RATE, CH, BPS = 44100, 2, 4  # s16le stereo
META_FMT = "\t".join("{{%s}}" % k for k in
                     ("mpris:trackid", "mpris:length", "xesam:artist", "xesam:title", "xesam:album"))


class Fehler(RuntimeError):
    pass


def sh(*a):
    return subprocess.run(a, check=True, text=True, capture_output=True).stdout.strip()


NOETIG = ("playerctl", "parec", "pactl", "ffmpeg", "ffprobe")


def fehlende_programme():
    """Die Programme, die die Aufnahme braucht und die auf diesem Rechner fehlen."""
    return [p for p in NOETIG if shutil.which(p) is None]


def pc(*a):
    try:
        return subprocess.run(["playerctl", "-p", "spotify", *a], text=True, capture_output=True)
    except FileNotFoundError:
        return subprocess.CompletedProcess(["playerctl"], 127, "", "playerctl fehlt")


def spotify_info():
    """(status, 'Interpret – Titel') oder (None, None), wenn Spotify nicht läuft."""
    r = pc("metadata", "--format", "{{status}}\t{{xesam:artist}} – {{xesam:title}}")
    if r.returncode != 0 or not r.stdout.strip():
        return None, None
    status, _, song = r.stdout.strip().partition("\t")
    return status, song


def standard_ziel():
    try:
        music = Path(sh("xdg-user-dir", "MUSIC"))
    except Exception:
        music = Path.home() / "Musik"
    return music / "Tonie"


def _spotify_stream():
    for s in json.loads(sh("pactl", "-f", "json", "list", "sink-inputs")):
        p = s.get("properties", {})
        names = " ".join(str(p.get(k, "")) for k in
                         ("application.name", "application.process.binary", "node.name")).lower()
        if "spotify" in names:
            return s["index"]
    return None


def _follow(args, tag, q):
    proc = subprocess.Popen(["playerctl", "-p", "spotify", "--follow", *args],
                            stdout=subprocess.PIPE, text=True)
    threading.Thread(target=lambda: [q.put((tag, l.rstrip("\n"))) for l in proc.stdout], daemon=True).start()
    return proc


def _safe(s):
    return re.sub(r'[/\\:*?"<>|]', "_", s).strip() or "unbekannt"


def _schluessel(interpret, titel):
    return (re.sub(r"\W+", " ", interpret).strip().casefold(), re.sub(r"\W+", " ", titel).strip().casefold())


def ordner_fuer(ziel, name):
    """Der Ordner, in den eine Aufnahme mit diesem Namen geht (ohne Namen: Datum und Uhrzeit)."""
    basis = _safe(name) if name and name.strip() else datetime.now().strftime("%Y-%m-%d_%H%M")
    return (Path(ziel) if ziel else standard_ziel()) / basis


def vorhandene(ordner):
    """Die Lieder, die schon im Ordner liegen: [{nr, interpret, titel, laenge}], nach Nummer sortiert."""
    lieder = []
    for f in sorted(Path(ordner).glob("*.mp3")) if Path(ordner).is_dir() else []:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags=title,artist,track",
                            "-of", "json", str(f)], text=True, capture_output=True)
        try:
            fmt = json.loads(r.stdout)["format"]
        except (ValueError, KeyError):
            continue
        tags = {k.lower(): v for k, v in fmt.get("tags", {}).items()}
        m = re.match(r"(\d+)\s+(.*?)\s+-\s+(.*)\.mp3$", f.name)
        nr = int(str(tags.get("track", "")).split("/")[0] or 0) or (int(m.group(1)) if m else 0)
        lieder.append({"nr": nr, "interpret": tags.get("artist") or (m.group(2) if m else ""),
                       "titel": tags.get("title") or (m.group(3) if m else f.stem),
                       "laenge": float(fmt.get("duration", 0))})
    return sorted(lieder, key=lambda l: l["nr"])


def _unvollstaendig(t):
    return t["end"] - t["start"] < t["len"] * 0.97 - 1


def _zaehlt(t, verwerfen):
    return not t["ad"] and not t["skip"] and t["nr"] not in verwerfen


def aufnehmen(minuten=90, ziel=None, mithoeren=False, kbit=192, melde=print, stopp=None, name=None, verwerfen=None,
              fortsetzen=True):
    """Nimmt auf, bis das Limit erreicht, die Playlist zu Ende oder `stopp` gesetzt ist.

    melde(art, **daten) bekommt: start, lied, vorhanden, werbung, uebersprungen, limit, ende, schneide, fertig.
    verwerfen: Menge von Liednummern, die nicht gespeichert werden (darf sich während der Aufnahme ändern).
    fortsetzen: Gibt es den Ordner schon, kommen neue Lieder dazu; Lieder, die schon drin liegen, überspringt
    Spotify sofort (melde vorhanden). Sonst geht die Aufnahme in einen neuen Ordner „Name (2)“.
    Gibt (Ordner, Anzahl Lieder, Minuten) zurück.
    """
    stopp = stopp or threading.Event()
    verwerfen = verwerfen if verwerfen is not None else set()  # Nummern, die der Mensch weggeklickt hat
    if spotify_info()[0] is None:
        raise Fehler("Spotify läuft nicht: Spotify starten und das erste Lied der Playlist anklicken.")
    out = ordner_fuer(ziel, name)
    alt = vorhandene(out) if fortsetzen else []
    if not fortsetzen:
        basis, i = out, 2
        while out.exists() and any(out.iterdir()):  # nie in eine vorhandene Aufnahme schreiben
            out, i = basis.parent / f"{basis.name} ({i})", i + 1
    out.mkdir(parents=True, exist_ok=True)
    raw = out / ".aufnahme.raw"
    limit = minuten * 60
    bekannt = {_schluessel(l["interpret"], l["titel"]) for l in alt}
    alt_sek = sum(l["laenge"] for l in alt)
    erste_nr = max((l["nr"] for l in alt), default=0)  # neue Lieder nummerieren dahinter weiter

    modules, parec, followers, tracks = [], None, [], []
    grund = "gestoppt"
    try:
        modules.append(sh("pactl", "load-module", "module-null-sink", f"sink_name={SINK}",
                          "sink_properties=device.description=Tonie-Aufnahme"))
        if mithoeren:
            modules.append(sh("pactl", "load-module", "module-loopback",
                              f"source={SINK}.monitor", "latency_msec=100"))

        idx = _spotify_stream()
        if idx is None:  # Spotify öffnet seinen Audiostrom erst beim Abspielen
            pc("play")
            for _ in range(50):
                time.sleep(0.2)
                if (idx := _spotify_stream()) is not None:
                    break
            else:
                raise Fehler("Kein Audiostrom von Spotify gefunden.")
        pc("pause")
        time.sleep(0.5)
        pc("position", "0")
        sh("pactl", "move-sink-input", str(idx), SINK)

        parec = subprocess.Popen(["parec", "-d", f"{SINK}.monitor", "--format=s16le", f"--rate={RATE}",
                                  f"--channels={CH}", "--latency-msec=50"], stdout=open(raw, "wb"))
        pos = lambda: raw.stat().st_size / (RATE * BPS)
        time.sleep(0.3)
        q = queue.Queue()
        for args, tag in ((["status"], "status"), (["metadata", "--format", META_FMT], "meta")):
            followers.append(_follow(args, tag, q))
        time.sleep(0.3)
        pc("play")
        melde("start", ordner=out, limit=minuten)

        status, meta, cur, paused_since = "", None, None, None
        while not stopp.is_set():
            try:
                tag, line = q.get(timeout=0.5)
            except queue.Empty:
                if paused_since and time.monotonic() - paused_since > 15:
                    grund = "Playlist zu Ende"
                    break
                continue
            if tag == "status":
                status = line
            else:
                f = line.split("\t")
                meta = dict(zip(("id", "len", "artist", "title", "album"), f + [""] * (5 - len(f))))
            paused_since = None if status == "Playing" else (paused_since or time.monotonic())
            if status != "Playing" or not meta or meta["id"] == cur:
                continue
            cur, now = meta["id"], pos()
            if tracks:
                prev = tracks[-1]
                prev["end"] = now
                if not prev["ad"] and _unvollstaendig(prev):
                    prev["skip"] = True
                    melde("uebersprungen", nr=prev["nr"])
            ad = "/ad/" in cur or cur.startswith("spotify:ad")
            length = int(meta["len"] or 0) / 1e6
            used = alt_sek + sum(t["len"] for t in tracks if _zaehlt(t, verwerfen))
            if not ad and used + length > limit:
                melde("limit", titel=meta["title"])
                grund = "Limit erreicht"
                break
            schl = _schluessel(meta["artist"], meta["title"])
            if not ad and schl in bekannt:  # liegt schon im Ordner: gleich weiter zum nächsten Lied
                tracks.append({**meta, "start": now, "end": None, "len": length, "ad": True, "skip": True, "nr": 0})
                melde("vorhanden", interpret=meta["artist"], titel=meta["title"])
                pc("next")
                continue
            nr = erste_nr + sum(not t["ad"] for t in tracks) + (0 if ad else 1)
            tracks.append({**meta, "start": now, "end": None, "len": length, "ad": ad, "skip": False, "nr": nr})
            if ad:
                melde("werbung")
            else:
                bekannt.add(schl)  # läuft die Playlist im Kreis, nicht doppelt aufnehmen
                melde("lied", nr=nr, interpret=meta["artist"],
                      titel=meta["title"], laenge=length, gesamt=used + length)
    finally:
        pc("pause")
        time.sleep(0.3)
        end = raw.stat().st_size / (RATE * BPS) if raw.exists() else 0
        if parec:
            parec.terminate()
            parec.wait()
        for p in followers:
            p.terminate()
        for m in reversed(modules):  # Spotify fällt dabei auf das Standardgerät zurück
            subprocess.run(["pactl", "unload-module", m], capture_output=True)
    melde("ende", grund=grund)

    if tracks and tracks[-1]["end"] is None:
        tracks[-1]["end"] = end
    if tracks and not tracks[-1]["ad"] and _unvollstaendig(tracks[-1]):
        tracks[-1]["skip"] = True
        melde("uebersprungen", nr=tracks[-1]["nr"])
    lieder = [t for t in tracks if _zaehlt(t, verwerfen)]
    n, total = erste_nr, alt_sek
    for i, t in enumerate(lieder, 1):
        dur = t["end"] - t["start"]
        n += 1
        total += t["len"]
        melde("schneide", i=i, von=len(lieder), titel=t["title"])
        name = out / f"{n:02d} {_safe(t['artist'])} - {_safe(t['title'])}.mp3"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "s16le", "-ar", str(RATE), "-ac", str(CH),
                        "-ss", f"{t['start']:.3f}", "-t", f"{dur:.3f}", "-i", str(raw),
                        "-af", "silenceremove=start_periods=1:start_threshold=-55dB:"
                               "stop_periods=-1:stop_duration=1.5:stop_threshold=-55dB",
                        "-c:a", "libmp3lame", "-b:a", f"{kbit}k",
                        "-metadata", f"title={t['title']}", "-metadata", f"artist={t['artist']}",
                        "-metadata", f"album={t['album']}", "-metadata", f"track={n}", str(name)], check=True)
    raw.unlink(missing_ok=True)
    neu = n - erste_nr
    if n == 0:
        try:
            out.rmdir()
        except OSError:
            pass
    melde("fertig", ordner=out, anzahl=len(alt) + neu, neu=neu, minuten=total / 60)
    return out, neu, total / 60
