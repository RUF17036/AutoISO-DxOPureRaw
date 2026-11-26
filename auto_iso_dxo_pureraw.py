"""Auto ISO DxO PureRaw – schickt alle RAWs eines Ordners über einer ISO-Grenze an DxO PureRAW.

Start ohne Argumente  -> grafische Oberfläche
Start mit --folder    -> Kommandozeilenmodus (siehe --help)
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from exif_iso import read_iso

FROZEN = getattr(sys, "frozen", False)   # True, wenn als EXE (PyInstaller) gestartet


def _settings_file() -> Path:
    """Als Skript: settings.json neben dem Skript. Als EXE: unter %APPDATA%.

    Eine --onefile-EXE entpackt sich bei jedem Start in einen temporären Ordner, der danach
    gelöscht wird. Neben der EXE ist es auch nicht sicher, denn unter C:\\Program Files
    darf ein normales Programm nicht schreiben.
    """
    if not FROZEN:
        return Path(__file__).resolve().parent / "settings.json"
    base = Path(os.environ.get("APPDATA") or Path.home()) / "AutoISO-DxOPureRaw"
    return base / "settings.json"


SETTINGS_FILE = _settings_file()

RAW_EXTENSIONS = {
    ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".dng",
    ".orf", ".rw2", ".raf", ".pef", ".srw", ".3fr", ".iiq", ".erf", ".mef",
    ".mos", ".rwl", ".kdc", ".dcr",
}
# Von PureRAW erzeugte Dateien tragen "DxO" im Namen (z. B. IMG_1234_DxO_DeepPRIMEXD2s.dng)
OUTPUT_PATTERN = re.compile(r"[_\- ]dxo", re.IGNORECASE)
# Übergabe-Modi von PureRAW (dieselben wie im Lightroom-Menü von DxO)
MODES = {
    "preview": ("--as-lightroom-preview-plugin", "Mit Vorschau – Einstellungen in PureRAW wählen"),
    "instant": ("--as-lightroom-plugin", "Sofort verarbeiten"),
    "last": ("--as-lightroom-last-settings-plugin", "Sofort mit zuletzt verwendeten Einstellungen"),
}

DEFAULTS = {
    "folder": "",
    "iso": 3200,
    "inclusive": False,
    "recursive": False,
    "skip_processed": True,
    "mode": "preview",
    "pureraw_exe": "",
}


# --------------------------------------------------------------------------- Logik

@dataclass
class Item:
    path: Path
    iso: int | None
    processed: bool
    selected: bool = False


def find_pureraw() -> str:
    patterns = [
        r"C:\Program Files\DxO\DxO PureRAW*\PureRAW*.exe",
        r"C:\Program Files (x86)\DxO\DxO PureRAW*\PureRAW*.exe",
    ]
    hits = []
    for pat in patterns:
        hits += [h for h in glob.glob(pat) if "saver" not in h.lower()]
    # höchste Version zuerst
    hits.sort(key=lambda h: [int(n) for n in re.findall(r"\d+", Path(h).parent.name)] or [0], reverse=True)
    return hits[0] if hits else ""


def load_settings() -> dict:
    s = dict(DEFAULTS)
    try:
        loaded = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        s.update({k: v for k, v in loaded.items() if k in DEFAULTS})  # veraltete Schlüssel ignorieren
    except (OSError, ValueError):
        pass
    if s["mode"] not in MODES:
        s["mode"] = DEFAULTS["mode"]
    if not s["pureraw_exe"] or not Path(s["pureraw_exe"]).is_file():
        s["pureraw_exe"] = find_pureraw()
    return s


def save_settings(s: dict) -> None:
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def list_raws(folder: Path, recursive: bool) -> tuple[list[Path], set[str]]:
    """Liefert RAW-Kandidaten und die Namen aller Dateien (für die 'schon verarbeitet'-Prüfung)."""
    raws: list[Path] = []
    all_names: set[str] = set()
    if recursive:
        walker = ((Path(d), files) for d, _, files in os.walk(folder))
    else:
        files = [p.name for p in folder.iterdir() if p.is_file()]
        walker = [(folder, files)]
        dxo_dir = folder / "DxO"           # Standard-Ausgabeordner von PureRAW
        if dxo_dir.is_dir():
            all_names.update(p.name.lower() for p in dxo_dir.iterdir() if p.is_file())
    for d, files in walker:
        for name in files:
            all_names.add(name.lower())
            p = d / name
            if p.suffix.lower() in RAW_EXTENSIONS and not OUTPUT_PATTERN.search(p.stem):
                raws.append(p)
    raws.sort(key=lambda p: str(p).lower())
    return raws, all_names


def processed_stems(all_names: set[str]) -> set[str]:
    """Basisnamen, zu denen bereits eine PureRAW-Ausgabe (…_DxO…) existiert."""
    stems = set()
    for n in all_names:
        m = re.match(r"(.+?)[_\- ]dxo", n, re.IGNORECASE)
        if m:
            stems.add(m.group(1).lower())
    return stems


def matches(item: Item, threshold: int, inclusive: bool, skip_processed: bool) -> bool:
    if item.iso is None or (skip_processed and item.processed):
        return False
    return item.iso >= threshold if inclusive else item.iso > threshold


def scan(folder: Path, recursive: bool, progress=None) -> list[Item]:
    raws, all_names = list_raws(folder, recursive)
    done = processed_stems(all_names)
    items = []
    for i, p in enumerate(raws, 1):
        items.append(Item(p, read_iso(str(p)), p.stem.lower() in done))
        if progress:
            progress(i, len(raws))
    return items


def send_to_pureraw(exe: str, files: list[Path], mode: str = "preview") -> Path:
    """Übergibt die Dateien an PureRAW – genauso wie DxOs eigenes Lightroom-Plugin.

    PureRAW ignoriert Bildpfade direkt auf der Kommandozeile. Es liest stattdessen eine
    Listendatei (ein Pfad pro Zeile) über --batch-file, aber nur im Plugin-Modus. Der
    Modus-Schalter verschluckt das nächste Argument als Wert, deshalb folgt wie beim
    Lightroom-Plugin zuerst --lr-version. PureRAW löscht die Liste nach dem Einlesen.
    """
    if not exe or not Path(exe).is_file():
        raise FileNotFoundError("DxO PureRAW wurde nicht gefunden. Bitte Pfad zur PureRAW-EXE angeben.")
    fd, batch = tempfile.mkstemp(prefix="AutoIsoDxoPureRaw_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(f"{f}\n" for f in files)
    subprocess.Popen([exe, MODES[mode][0], "--lr-version=14.0", "--batch-file", batch], close_fds=True)
    return Path(batch)


# --------------------------------------------------------------------------- CLI

def run_cli(argv: list[str]) -> int:
    s = load_settings()
    ap = argparse.ArgumentParser(description="RAWs über einer ISO-Grenze an DxO PureRAW übergeben.")
    ap.add_argument("--folder", required=True)
    ap.add_argument("--iso", type=int, default=s["iso"], help="ISO-Grenzwert (Standard: %(default)s)")
    ap.add_argument("--inclusive", action="store_true", help="Grenzwert selbst einschließen (>= statt >)")
    ap.add_argument("--recursive", action="store_true", help="Unterordner einbeziehen")
    ap.add_argument("--include-processed", action="store_true", help="bereits verarbeitete nicht überspringen")
    ap.add_argument("--pureraw", default=s["pureraw_exe"], help="Pfad zur PureRAW-EXE")
    ap.add_argument("--mode", choices=list(MODES), default=s["mode"],
                    help="preview = mit Vorschau, instant = sofort, last = sofort mit letzten Einstellungen "
                         "(Standard: %(default)s)")
    ap.add_argument("--dry-run", action="store_true", help="nur auflisten, nichts an PureRAW senden")
    a = ap.parse_args(argv)

    folder = Path(a.folder)
    if not folder.is_dir():
        print(f"Ordner nicht gefunden: {folder}", file=sys.stderr)
        return 2
    items = scan(folder, a.recursive)
    selected = [it for it in items if matches(it, a.iso, a.inclusive, not a.include_processed)]
    op = ">=" if a.inclusive else ">"
    for it in items:
        mark = "X" if it in selected else " "
        note = " (bereits verarbeitet)" if it.processed else ""
        print(f"[{mark}] ISO {it.iso if it.iso is not None else '?':>6}  {it.path}{note}")
    print(f"\n{len(selected)} von {len(items)} RAWs mit ISO {op} {a.iso}.")
    if selected and not a.dry_run:
        send_to_pureraw(a.pureraw, [it.path for it in selected], a.mode)
        print("An DxO PureRAW übergeben.")
    return 0


# --------------------------------------------------------------------------- GUI

def run_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    s = load_settings()
    items: list[Item] = []

    root = tk.Tk()
    root.title("Auto ISO DxO PureRaw – ISO-Filter für DxO PureRAW")
    root.geometry("900x620")
    root.minsize(700, 450)

    v_folder = tk.StringVar(value=s["folder"])
    v_iso = tk.IntVar(value=s["iso"])
    v_incl = tk.BooleanVar(value=s["inclusive"])
    v_rec = tk.BooleanVar(value=s["recursive"])
    v_skip = tk.BooleanVar(value=s["skip_processed"])
    mode_labels = {k: v[1] for k, v in MODES.items()}
    v_mode = tk.StringVar(value=mode_labels[s["mode"]])
    v_exe = tk.StringVar(value=s["pureraw_exe"])
    v_status = tk.StringVar(value="Ordner wählen und „Scannen“ klicken.")

    def current_settings() -> dict:
        try:
            iso = int(v_iso.get())
        except (tk.TclError, ValueError):
            iso = s["iso"]
        return {"folder": v_folder.get(), "iso": iso, "inclusive": v_incl.get(),
                "recursive": v_rec.get(), "skip_processed": v_skip.get(),
                "pureraw_exe": v_exe.get(),
                "mode": next((k for k, lbl in mode_labels.items() if lbl == v_mode.get()), "preview")}

    # --- Einstellungen
    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="x")
    frm.columnconfigure(1, weight=1)

    ttk.Label(frm, text="Ordner:").grid(row=0, column=0, sticky="w")
    ttk.Entry(frm, textvariable=v_folder).grid(row=0, column=1, sticky="ew", padx=5)
    ttk.Button(frm, text="Durchsuchen…",
               command=lambda: v_folder.set(filedialog.askdirectory(initialdir=v_folder.get() or None)
                                            or v_folder.get())).grid(row=0, column=2)

    ttk.Label(frm, text="PureRAW:").grid(row=1, column=0, sticky="w", pady=(6, 0))
    ttk.Entry(frm, textvariable=v_exe).grid(row=1, column=1, sticky="ew", padx=5, pady=(6, 0))
    ttk.Button(frm, text="Auswählen…",
               command=lambda: v_exe.set(filedialog.askopenfilename(filetypes=[("Programm", "*.exe")])
                                         or v_exe.get())).grid(row=1, column=2, pady=(6, 0))

    opts = ttk.Frame(frm)
    opts.grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
    ttk.Label(opts, text="ISO über:").pack(side="left")
    iso_box = ttk.Spinbox(opts, from_=50, to=409600, increment=100, width=8, textvariable=v_iso,
                          values=(100, 200, 400, 800, 1000, 1250, 1600, 2000, 2500, 3200, 4000, 5000,
                                  6400, 8000, 10000, 12800, 16000, 25600, 51200, 102400))
    iso_box.pack(side="left", padx=(5, 15))
    ttk.Checkbutton(opts, text="Grenzwert einschließen (≥)", variable=v_incl).pack(side="left", padx=5)
    ttk.Checkbutton(opts, text="Unterordner", variable=v_rec).pack(side="left", padx=5)
    ttk.Checkbutton(opts, text="Bereits verarbeitete überspringen", variable=v_skip).pack(side="left", padx=5)
    opts2 = ttk.Frame(frm)
    opts2.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
    ttk.Label(opts2, text="Übergabe:").pack(side="left", padx=(0, 5))
    ttk.Combobox(opts2, textvariable=v_mode, values=list(mode_labels.values()), state="readonly",
                 width=44).pack(side="left")

    # --- Liste
    lst = ttk.Frame(root, padding=(10, 0))
    lst.pack(fill="both", expand=True)
    tree = ttk.Treeview(lst, columns=("sel", "iso", "file", "note"), show="headings", selectmode="extended")
    for col, text, w, anchor, stretch in (("sel", "✔", 40, "center", False), ("iso", "ISO", 80, "e", False),
                                          ("file", "Datei", 520, "w", True), ("note", "Hinweis", 160, "w", False)):
        tree.heading(col, text=text)
        tree.column(col, width=w, anchor=anchor, stretch=stretch)
    tree.tag_configure("off", foreground="#888888")
    sb = ttk.Scrollbar(lst, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    # --- Fußzeile
    bottom = ttk.Frame(root, padding=10)
    bottom.pack(fill="x")
    progress = ttk.Progressbar(bottom, mode="determinate")
    progress.pack(fill="x", pady=(0, 6))
    ttk.Label(bottom, textvariable=v_status).pack(side="left")
    btn_send = ttk.Button(bottom, text="An PureRAW senden")
    btn_send.pack(side="right")
    btn_scan = ttk.Button(bottom, text="Scannen")
    btn_scan.pack(side="right", padx=6)

    def update_status():
        sel = sum(it.selected for it in items)
        op = "≥" if v_incl.get() else ">"
        v_status.set(f"{sel} von {len(items)} Dateien ausgewählt (ISO {op} {current_settings()['iso']}). "
                     "Klick auf eine Zeile schaltet sie um.")

    def refresh_tree():
        tree.delete(*tree.get_children())
        base = Path(v_folder.get())
        for idx, it in enumerate(items):
            try:
                name = str(it.path.relative_to(base))
            except ValueError:
                name = str(it.path)
            note = "bereits verarbeitet" if it.processed else ("ISO nicht lesbar" if it.iso is None else "")
            tree.insert("", "end", iid=str(idx), tags=() if it.selected else ("off",),
                        values=("✔" if it.selected else "", it.iso if it.iso is not None else "?", name, note))
        update_status()

    def apply_filter(*_):
        cfg = current_settings()
        for it in items:
            it.selected = matches(it, cfg["iso"], cfg["inclusive"], cfg["skip_processed"])
        refresh_tree()

    def set_rows(rows, state):
        for r in rows:
            items[int(r)].selected = state
            tree.set(r, "sel", "✔" if state else "")
            tree.item(r, tags=() if state else ("off",))
        update_status()

    def on_click(event):
        # Klick in die ✔-Spalte schaltet die Zeile um
        row = tree.identify_row(event.y)
        if row and tree.identify_column(event.x) == "#1":
            set_rows([row], not items[int(row)].selected)

    def on_double(event):
        row = tree.identify_row(event.y)
        if row:
            set_rows([row], not items[int(row)].selected)

    def on_space(_):
        rows = tree.selection()
        if rows:
            set_rows(rows, not items[int(rows[0])].selected)

    tree.bind("<ButtonRelease-1>", on_click)
    tree.bind("<Double-1>", on_double)
    tree.bind("<space>", on_space)

    def do_scan():
        folder = Path(v_folder.get())
        if not folder.is_dir():
            messagebox.showerror("Fehler", "Bitte einen gültigen Ordner wählen.")
            return
        save_settings(current_settings())
        btn_scan.state(["disabled"])
        btn_send.state(["disabled"])
        v_status.set("Scanne …")
        progress["value"] = 0

        def prog(i, n):
            root.after(0, lambda: (progress.configure(maximum=max(n, 1), value=i),
                                   v_status.set(f"Lese EXIF {i}/{n} …")))

        def work():
            try:
                result = scan(folder, v_rec.get(), prog)
                err = None
            except OSError as e:
                result, err = [], e

            def done():
                items[:] = result
                btn_scan.state(["!disabled"])
                btn_send.state(["!disabled"])
                if err:
                    messagebox.showerror("Fehler", str(err))
                apply_filter()
                if not result and not err:
                    v_status.set("Keine passenden Bilddateien gefunden.")
            root.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def do_send():
        files = [it.path for it in items if it.selected]
        if not files:
            messagebox.showinfo("Nichts zu tun", "Keine Dateien ausgewählt.")
            return
        cfg = current_settings()
        save_settings(cfg)
        exe, mode = cfg["pureraw_exe"], cfg["mode"]
        if not exe or not Path(exe).is_file():
            messagebox.showerror("Fehler", "DxO PureRAW wurde nicht gefunden. Bitte Pfad zur PureRAW-EXE angeben.")
            return
        btn_send.state(["disabled"])
        v_status.set(f"Übergebe {len(files)} Dateien an DxO PureRAW …")

        def work():
            try:
                send_to_pureraw(exe, files, mode)
                msg = None
            except OSError as e:
                msg = str(e)

            def done():
                btn_send.state(["!disabled"])
                if msg:
                    messagebox.showerror("Fehler", msg)
                    update_status()
                else:
                    v_status.set(f"{len(files)} Dateien an DxO PureRAW übergeben – Verarbeitung dort starten.")
            root.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    btn_scan.configure(command=do_scan)
    btn_send.configure(command=do_send)
    for var in (v_iso, v_incl, v_skip):
        var.trace_add("write", lambda *_: items and apply_filter())

    def on_close():
        save_settings(current_settings())
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(run_cli(sys.argv[1:]))
    run_gui()
