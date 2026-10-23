from flask import Flask, request, jsonify, render_template, send_file
import requests, os, re, hashlib, io, json, time
from urllib.parse import quote
from PIL import Image, ImageOps
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A5, landscape
from reportlab.lib.utils import ImageReader

app = Flask(__name__)
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
IMAGES = os.path.join(DATA, "images")
os.makedirs(IMAGES, exist_ok=True)
MANIFEST = os.path.join(DATA, "manifest.json")
UA = "MangaPrintGenerator/1.0 (local personal-use app)"
TIMEOUT = 20
MAX_DOWNLOAD_BYTES = 18 * 1024 * 1024
ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff", ".bmp"}

def load_manifest():
    try:
        with open(MANIFEST, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_manifest(items):
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

def clean_query(q):
    return re.sub(r"\s+", " ", (q or "").strip())[:160]

def openverse_search(query, page=1, page_size=20):
    # Openverse returns openly licensed media with licence and attribution metadata.
    url = "https://api.openverse.org/v1/images/"
    r = requests.get(url, params={
        "q": query, "page": page, "page_size": min(page_size, 40),
        "mature": "false"
    }, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    out = []
    for x in data.get("results", []):
        image_url = x.get("url") or x.get("thumbnail")
        license_name = x.get("license")
        if not image_url or not license_name:
            continue
        out.append({
            "source": "Openverse",
            "title": x.get("title") or "Untitled image",
            "creator": x.get("creator") or "Unknown",
            "page_url": x.get("foreign_landing_url") or x.get("detail_url") or "",
            "image_url": image_url,
            "license": license_name,
            "license_url": x.get("license_url") or "",
            "thumbnail": x.get("thumbnail") or image_url,
            "query": query
        })
    return out

def commons_search(query, limit=25):
    api = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": "filetype:bitmap " + query, "gsrnamespace": 6,
        "gsrlimit": min(limit, 50), "prop": "imageinfo|info",
        "iiprop": "url|extmetadata", "iiurlwidth": 480,
        "inprop": "url"
    }
    r = requests.get(api, params=params, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", {})
    out = []
    for p in pages.values():
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata") or {}
        def val(key):
            return (meta.get(key) or {}).get("value", "")
        license_name = re.sub("<[^>]+>", "", val("LicenseShortName"))
        license_url = val("LicenseUrl")
        # Commons is a reuse-oriented repository, but retain its page and licence metadata.
        out.append({
            "source": "Wikimedia Commons",
            "title": p.get("title", "Untitled file").replace("File:", ""),
            "creator": re.sub("<[^>]+>", "", val("Artist")) or "Unknown",
            "page_url": p.get("fullurl") or ii.get("descriptionurl") or "",
            "image_url": ii.get("url") or "",
            "license": license_name or "Check source page",
            "license_url": license_url,
            "thumbnail": ii.get("thumburl") or ii.get("url") or "",
            "query": query
        })
    return out

def safe_image_name(content):
    return hashlib.sha256(content).hexdigest() + ".jpg"

def download_item(item):
    url = item.get("image_url", "")
    if not url.startswith("https://"):
        return None, "Skipped: image URL is not HTTPS"
    try:
        with requests.get(url, headers={"User-Agent": UA}, stream=True, timeout=TIMEOUT) as r:
            r.raise_for_status()
            ctype = r.headers.get("Content-Type", "").lower()
            if not ctype.startswith("image/"):
                return None, "Skipped: source did not return an image"
            chunks, total = [], 0
            for chunk in r.iter_content(65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    return None, "Skipped: image exceeds 18 MB limit"
                chunks.append(chunk)
            raw = b"".join(chunks)
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img).convert("RGB")
        if img.width < 250 or img.height < 250:
            return None, "Skipped: image is too small for print"
        digest = hashlib.sha256(img.tobytes()).hexdigest()
        path = os.path.join(IMAGES, digest + ".jpg")
        if not os.path.exists(path):
            img.save(path, "JPEG", quality=94, optimize=True)
        item["id"] = digest
        item["file"] = os.path.basename(path)
        item["width"] = img.width
        item["height"] = img.height
        item["downloaded_at"] = int(time.time())
        return item, None
    except Exception as e:
        return None, "Download failed: " + str(e)[:160]

@app.get("/")
def index():
    return render_template("index.html")

@app.post("/api/search")
def search():
    payload = request.get_json(force=True)
    query = clean_query(payload.get("query"))
    if not query:
        return jsonify({"error": "Enter a manga, series, or image query."}), 400
    results, errors = [], []
    try:
        results.extend(openverse_search(query, page=int(payload.get("page", 1))))
    except Exception as e:
        errors.append("Openverse: " + str(e)[:180])
    try:
        results.extend(commons_search(query))
    except Exception as e:
        errors.append("Wikimedia Commons: " + str(e)[:180])
    seen = set()
    unique = []
    existing_pages = {x.get("page_url") for x in load_manifest()}
    for item in results:
        key = item.get("page_url") or item.get("image_url")
        if key and key not in seen and key not in existing_pages:
            seen.add(key)
            unique.append(item)
    return jsonify({"results": unique, "errors": errors, "count": len(unique)})

@app.post("/api/collect")
def collect():
    payload = request.get_json(force=True)
    candidates = payload.get("items", [])
    if not isinstance(candidates, list):
        return jsonify({"error": "Invalid image list"}), 400
    manifest = load_manifest()
    known_ids = {x.get("id") for x in manifest}
    known_pages = {x.get("page_url") for x in manifest}
    added, skipped, messages = [], 0, []
    for item in candidates[:80]:
        if not isinstance(item, dict) or not item.get("image_url"):
            skipped += 1
            continue
        if item.get("page_url") in known_pages:
            skipped += 1
            continue
        # Require an identifiable licence; do not treat unlabelled images as permission.
        if not item.get("license") or item.get("license") == "Check source page":
            skipped += 1
            messages.append("Skipped an item without a clearly identified licence. Check its source page manually.")
            continue
        saved, error = download_item(dict(item))
        if error:
            skipped += 1
            messages.append(error)
            continue
        if saved["id"] in known_ids:
            skipped += 1
            try:
                os.remove(os.path.join(IMAGES, saved["file"]))
            except Exception:
                pass
            continue
        manifest.append(saved)
        added.append(saved)
        known_ids.add(saved["id"])
        known_pages.add(saved.get("page_url"))
    save_manifest(manifest)
    return jsonify({"added": added, "skipped": skipped, "total": len(manifest), "messages": messages[:12]})

@app.get("/api/collection")
def collection():
    items = load_manifest()
    return jsonify([{
        "id": x["id"], "title": x.get("title"), "creator": x.get("creator"),
        "source": x.get("source"), "page_url": x.get("page_url"),
        "license": x.get("license"), "license_url": x.get("license_url"),
        "width": x.get("width"), "height": x.get("height"),
        "thumbnail": "/image/" + x["id"]
    } for x in items])

@app.get("/image/<image_id>")
def image(image_id):
    if not re.fullmatch(r"[a-f0-9]{64}", image_id):
        return "Not found", 404
    path = os.path.join(IMAGES, image_id + ".jpg")
    if not os.path.isfile(path):
        return "Not found", 404
    return send_file(path, mimetype="image/jpeg", conditional=True)

@app.post("/api/remove")
def remove():
    payload = request.get_json(force=True)
    ids = set(payload.get("ids", []))
    items = load_manifest()
    keep = []
    removed = 0
    for x in items:
        if x.get("id") in ids:
            try:
                os.remove(os.path.join(IMAGES, x["file"]))
            except Exception:
                pass
            removed += 1
        else:
            keep.append(x)
    save_manifest(keep)
    return jsonify({"removed": removed, "total": len(keep)})

@app.get("/api/pdf")
def pdf():
    items = load_manifest()
    if not items:
        return "Your collection is empty. Search and collect licensed images first.", 400
    orientation = request.args.get("orientation", "portrait")
    pagesize = landscape(A5) if orientation == "landscape" else A5
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=pagesize, pageCompression=1)
    page_w, page_h = pagesize
    margin = 14  # points
    for item in items:
        path = os.path.join(IMAGES, item["file"])
        try:
            with Image.open(path) as im:
                im = im.convert("RGB")
                iw, ih = im.size
                scale = min((page_w - 2 * margin) / iw, (page_h - 2 * margin) / ih)
                dw, dh = iw * scale, ih * scale
                x, y = (page_w - dw) / 2, (page_h - dh) / 2
                c.drawImage(ImageReader(im), x, y, width=dw, height=dh, preserveAspectRatio=True, anchor="c", mask="auto")
                c.showPage()
        except Exception:
            continue
    c.save()
    buffer.seek(0)
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=f"manga-panels-A5-{len(items)}-pages.pdf")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
