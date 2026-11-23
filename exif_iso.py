"""Minimaler, abhängigkeitsfreier ISO-Leser für RAW-Dateien.

Unterstützt TIFF-basierte RAWs (CR2, NEF, NRW, ARW, SR2, SRF, DNG, PEF, ORF,
RW2, SRW, ERF, 3FR, IIQ, MEF, MOS, RWL ...), Canon CR3 (CMT-Boxen) sowie
Formate mit eingebettetem Exif-JPEG (z. B. Fuji RAF) über eine Exif-Suche.
"""

from __future__ import annotations

import struct

TAG_EXIF_IFD = 0x8769
TAG_ISO = 0x8827                 # ISOSpeedRatings / PhotographicSensitivity
TAG_REC_EXPOSURE_INDEX = 0x8832
TAG_ISO_SPEED = 0x8833
TAG_PANASONIC_ISO = 0x0017       # RW2 IFD0

TIFF_MAGICS = {42, 0x55, 0x4F52, 0x5352}  # TIFF, RW2, ORF ("RO", "RS")

SCAN_BYTES = 4 * 1024 * 1024
TYPE_SIZES = {1: 1, 3: 2, 4: 4, 7: 1, 8: 2, 9: 4, 16: 8}


class _Tiff:
    def __init__(self, f, base: int, file_size: int):
        self.f = f
        self.base = base
        self.size = file_size
        f.seek(base)
        hdr = f.read(8)
        if len(hdr) < 8 or hdr[:2] not in (b"II", b"MM"):
            raise ValueError("kein TIFF-Header")
        self.e = "<" if hdr[:2] == b"II" else ">"
        self.magic = struct.unpack(self.e + "H", hdr[2:4])[0]
        if self.magic not in TIFF_MAGICS:
            raise ValueError("unbekannte TIFF-Magic")
        self.ifd0 = struct.unpack(self.e + "I", hdr[4:8])[0]

    def read_ifd(self, offset: int, wanted: set[int]) -> dict[int, int]:
        """Liest die gewünschten Tags (erster Wert, numerisch) aus einer IFD."""
        out: dict[int, int] = {}
        pos = self.base + offset
        if offset < 8 or pos + 2 > self.size:
            return out
        self.f.seek(pos)
        raw = self.f.read(2)
        if len(raw) < 2:
            return out
        count = struct.unpack(self.e + "H", raw)[0]
        if count == 0 or count > 1000:
            return out
        data = self.f.read(count * 12)
        for i in range(len(data) // 12):
            entry = data[i * 12:(i + 1) * 12]
            tag, typ, cnt = struct.unpack(self.e + "HHI", entry[:8])
            if tag not in wanted or typ not in TYPE_SIZES or cnt == 0:
                continue
            val_bytes = entry[8:12]
            if TYPE_SIZES[typ] * cnt > 4:
                ptr = struct.unpack(self.e + "I", val_bytes)[0]
                if self.base + ptr + 4 > self.size:
                    continue
                here = self.f.tell()
                self.f.seek(self.base + ptr)
                val_bytes = self.f.read(4)
                self.f.seek(here)
            if typ in (1, 7):
                out[tag] = val_bytes[0]
            elif typ in (3, 8):
                out[tag] = struct.unpack(self.e + "H", val_bytes[:2])[0]
            elif typ in (4, 9):
                out[tag] = struct.unpack(self.e + "I", val_bytes[:4])[0]
        return out


def _pick_iso(tags: dict[int, int]) -> int | None:
    iso = tags.get(TAG_ISO)
    # 65535 bedeutet bei manchen Kameras "zu groß für SHORT" -> Alternativen nutzen
    if iso and iso != 65535:
        return iso
    for alt in (TAG_ISO_SPEED, TAG_REC_EXPOSURE_INDEX):
        if tags.get(alt):
            return tags[alt]
    return iso or None


def _iso_from_tiff(f, base: int, size: int) -> int | None:
    t = _Tiff(f, base, size)
    wanted = {TAG_EXIF_IFD, TAG_ISO, TAG_ISO_SPEED, TAG_REC_EXPOSURE_INDEX, TAG_PANASONIC_ISO}
    ifd0 = t.read_ifd(t.ifd0, wanted)
    if t.magic == 0x55 and ifd0.get(TAG_PANASONIC_ISO):
        return ifd0[TAG_PANASONIC_ISO]
    if TAG_EXIF_IFD in ifd0:
        exif = t.read_ifd(ifd0[TAG_EXIF_IFD], wanted)
        iso = _pick_iso(exif)
        if iso:
            return iso
    return _pick_iso(ifd0)


def read_iso(path: str) -> int | None:
    """Gibt den ISO-Wert der Datei zurück oder None, wenn er nicht lesbar ist."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            # 1) Datei ist selbst ein TIFF
            try:
                iso = _iso_from_tiff(f, 0, size)
                if iso:
                    return iso
            except (ValueError, struct.error):
                pass
            f.seek(0)
            buf = f.read(SCAN_BYTES)
            # 2) Canon CR3: CMT2 enthält die Exif-IFD als eigenes TIFF
            for marker in (b"CMT2", b"CMT1"):
                i = buf.find(marker)
                if i >= 0:
                    try:
                        iso = _iso_from_tiff(f, i + 4, size)
                        if iso:
                            return iso
                    except (ValueError, struct.error):
                        pass
            # 3) Eingebettetes Exif (RAF, JPEG-Vorschauen ...)
            start = 0
            while True:
                i = buf.find(b"Exif\x00\x00", start)
                if i < 0:
                    break
                try:
                    iso = _iso_from_tiff(f, i + 6, size)
                    if iso:
                        return iso
                except (ValueError, struct.error):
                    pass
                start = i + 1
    except OSError:
        pass
    return None


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        print(f"{read_iso(p)}\t{p}")
