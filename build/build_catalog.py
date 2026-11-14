#!/usr/bin/env python3
"""Build data.js (+ cover/gallery thumbnails) for the Books in English catalog page.

Usage:
  python3 build_catalog.py catalog.csv [--photos PHOTOS_DIR] [--desc desc.json] [--out OUT_DIR]

catalog.csv  : export of the Google Sheet «Каталог книг» (text/csv)
PHOTOS_DIR   : local mirror of the Drive folder «Фото книг»: one sub-folder per book,
               images (first by name = cover) and optional short video.
desc.json    : auto-researched descriptions keyed by title (filled by Claude for rows
               whose «Описание заполнено» is empty). Sheet values always win.
OUT_DIR      : artifact working dir with index.html, img/, gallery/, video/ (default .)

Prints a JSON summary; writes OUT_DIR/data.js and resized images.
"""
import csv, json, os, re, sys, hashlib, shutil

def slug(s):
    s = re.sub(r"[^\w]+", "-", s.lower(), flags=re.U).strip("-")
    return s[:60] or hashlib.md5(s.encode()).hexdigest()[:8]

STATUS = {"в наличии": "in", "наличие": "in", "есть": "in", "available": "in",
          "бронь": "res", "забронирована": "res", "reserved": "res",
          "под заказ": "sold", "заказ": "sold", "order": "sold",
          "продана": "sold", "продано": "sold", "sold": "sold", "предзаказ": "sold"}
COND_EN = {"новая": "New", "б/у, как новая": "Used, like new", "б/у, очень хорошее": "Used, very good",
           "б/у, хорошее": "Used, good", "б/у, отличное": "Used, excellent", "б/у, удовлетворительное": "Used, fair"}
SECTION_EN = {"детские": "Children", "pop-up": "Pop-up", "искусство и дизайн": "Art & design",
              "каллиграфия": "Calligraphy & lettering", "иллюстрированные для взрослых": "Illustrated for grown-ups",
              "рождество": "Christmas", "классика": "Classics", "поэзия": "Poetry"}
BIND_EN = {"твёрдый": "Hardcover", "твердый": "Hardcover", "мягкий": "Paperback", "hardcover": "Hardcover", "paperback": "Paperback"}

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
VID_EXT = {".mp4", ".mov", ".m4v", ".webm"}

def col(row, *names):
    for n in names:
        for k in row:
            if k and k.strip().lower().startswith(n.lower()):
                return (row[k] or "").strip()
    return ""

def resize(src, dst, maxside, quality=78):
    from PIL import Image, ImageOps
    try:
        im = Image.open(src)
    except Exception:
        try:
            import pillow_heif; pillow_heif.register_heif_opener(); im = Image.open(src)
        except Exception as e:
            return False
    im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((maxside, maxside), Image.LANCZOS)
    im.save(dst, "JPEG", quality=quality, optimize=True)
    return True

def main():
    args = sys.argv[1:]
    if not args: print(__doc__); sys.exit(1)
    csv_path = args[0]
    def opt(name, default=None):
        return args[args.index(name)+1] if name in args else default
    photos = opt("--photos"); desc_path = opt("--desc"); out = opt("--out", ".")
    desc = json.load(open(desc_path)) if desc_path and os.path.exists(desc_path) else {}
    os.makedirs(os.path.join(out, "gallery"), exist_ok=True)
    os.makedirs(os.path.join(out, "video"), exist_ok=True)
    os.makedirs(os.path.join(out, "img"), exist_ok=True)

    rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))
    books, warnings, need_desc = [], [], []
    n = len(rows)
    for i, r in enumerate(rows):
        t = col(r, "Название")
        if not t: continue
        num = re.sub(r"\D", "", col(r, "№"))
        price_raw = col(r, "Цена")
        try: price = int(float(re.sub(r"[^\d.,]", "", price_raw).replace(",", ".") or 0))
        except ValueError: price = 0; warnings.append(f"{t}: цена «{price_raw}» не число")
        st = STATUS.get(col(r, "Статус").lower(), None)
        if st is None: warnings.append(f"{t}: статус «{col(r,'Статус')}» непонятен, считаю «в наличии»"); st = "in"
        cond = col(r, "Состояние"); cond_en = COND_EN.get(cond.lower(), cond)
        sec = col(r, "Раздел"); sec_en = SECTION_EN.get(sec.lower(), sec) or "Other"
        folder = col(r, "Папка")
        if not folder and num and photos and os.path.isdir(photos):
            for d in sorted(os.listdir(photos)):
                m = re.match(r"\s*№?\s*(\d+)(\D|$)", d)
                if m and m.group(1).lstrip("0") == num.lstrip("0") and os.path.isdir(os.path.join(photos, d)):
                    folder = d; break
        ig = col(r, "Фото из Instagram")
        sid = num if num else slug(t) + (f"-{i}" if any(b["id"] == slug(t) for b in books) else "")
        if num and any(b["id"] == num for b in books): warnings.append(f"№{num}: номер повторяется — у каждой книги должен быть свой"); sid = f"{num}-{i}"
        gallery, video = [], ""
        if photos and folder:
            fdir = os.path.join(photos, folder)
            if os.path.isdir(fdir):
                files = sorted(os.listdir(fdir), key=str.lower)
                k = 0
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in IMG_EXT:
                        dst = f"gallery/{sid}-{k:02d}.jpg"
                        if resize(os.path.join(fdir, f), os.path.join(out, dst), 1200 if k else 900): gallery.append(dst); k += 1
                    elif ext in VID_EXT and not video:
                        size = os.path.getsize(os.path.join(fdir, f))
                        if size > 25_000_000: warnings.append(f"{t}: видео {f} больше 25 МБ, пропущено — сожмите или дайте ссылку на Reel")
                        else:
                            video = f"video/{sid}{'.webm' if ext=='.webm' else '.mp4'}"
                            shutil.copy(os.path.join(fdir, f), os.path.join(out, video))
            else:
                warnings.append(f"№{num} {t}: папка «{folder}» не найдена в «Фото книг»")
        cover = gallery[0] if gallery else (f"img/{ig}.jpg" if ig and os.path.exists(os.path.join(out, "img", ig + ".jpg")) else "")
        if not cover: warnings.append(f"{t}: нет ни одного фото")
        d = desc.get(t, {})
        filled = col(r, "Описание заполнено").lower()
        def pick(sheet_name, key):
            v = col(r, sheet_name)
            return v if v else ("" if filled == "ок" else str(d.get(key, "")))
        pages = pick("Страниц", "pages"); binding = pick("Переплёт", "binding"); year = pick("Год", "year")
        publisher = pick("Издательство", "publisher"); about = pick("О книге", "about")
        if not (pages or about) and filled != "ок": need_desc.append(t)
        books.append({
            "id": sid, "num": num, "order": int(num) if num else n - i, "t": t, "a": col(r, "Автор"), "g": sec_en, "cond": cond_en, "price": price, "st": st,
            "cover": cover, "gallery": gallery[1:], "video": video, "reel": col(r, "Ссылка на видео"),
            "pages": pages, "binding": BIND_EN.get(binding.lower(), binding), "year": year, "publisher": publisher,
            "about": about, "note": col(r, "Заметка"),
            "auto": filled == "авто" or (bool(d) and filled != "ок" and not col(r, "О книге")),
        })
    with open(os.path.join(out, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.CATALOG=" + json.dumps({"books": books}, ensure_ascii=False) + ";")
    print(json.dumps({"books": len(books), "warnings": warnings, "need_description": need_desc}, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
