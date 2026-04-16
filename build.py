#!/usr/bin/env python3
"""
Build script for photo.jimmac.eu picture gallery.
Scans pictures/original/, extracts EXIF dates, generates thumbnails,
and produces a complete static site in public/.

Requires: pip install Pillow
"""

import os
import sys
import shutil
import re
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote
from html import escape as html_escape

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow is required. Install with: pip install Pillow")
    sys.exit(1)

SOURCE_DIR = Path("pictures/original")
STATIC_DIR = Path("static")
OUTPUT_DIR = Path("public")

SIZES = {
    "large": (2048, 2048),
    "thumbnail": (640, 640),
}

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp", ".gif", ".avif", ".heic", ".heif", ".jxl", 
}


CONFIG = {
    "base_url": "https://photo.jimmac.eu",
    "title": "photo.jimmac.eu",
    "description": "Photos by @jimmac",
    "author_name": "Jakub Steiner",
    "author_email": "jimmac@gmail.com",
    "author_website": "https://jimmac.eu",
    "allow_indexing": True,
    "allow_image_sharing": True,
    "allow_original_download": False,
    "mastodon_username": "jimmac",
    "github_username": "jimmac",
    "instagram_username": "jimmacfx",
    "pixelfed_username": "jimmac",
    "custom_link_name": "jimmac",
    "custom_link_url": "https://jimmac.eu",
}


def normalize_extensions():
    for path in SOURCE_DIR.iterdir():
        if path.suffix.lower() in IMAGE_EXTENSIONS and path.suffix != path.suffix.lower():
            new_path = path.with_suffix(path.suffix.lower())
            if path != new_path:
                path.rename(new_path)
                print(f"  Renamed: {path.name} -> {new_path.name}")


def get_exif_date(filepath):
    try:
        img = Image.open(filepath)
        exif = img._getexif()
        if exif:
            dto = exif.get(36867) or exif.get(36868)
            if dto:
                return datetime.strptime(dto, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return datetime.fromtimestamp(os.path.getmtime(filepath))


def get_exif_metadata(filepath):
    """Extract photo-specific EXIF metadata: camera, shutter, iso, aperture, focal length, lens."""
    result = {}
    try:
        img = Image.open(filepath)
        exif = img._getexif()
        if not exif:
            return result
        make = (exif.get(271) or "").strip()
        model = (exif.get(272) or "").strip()
        # DJI camera code to drone name mapping
        DJI_CAMERA_MAP = {
            "FC7303": "Mini 3 Pro",
            "FC3582": "Mini 3",
            "FC3411": "Air 2S",
            "FC3170": "Mavic Air 2",
            "FC2103": "Mavic 2 Pro",
            "FC2204": "Mavic 2 Zoom",
            "FC220": "Mavic Pro",
            "FC330": "Phantom 4",
            "FC6310": "Phantom 4 Pro",
            "FC6520": "Mavic Pro Platinum",
            "FC7203": "Mini 2",
            "FC3170": "Air 2",
        }

        # Use model, but prepend make if model doesn't already contain it
        if model:
            if make and make.lower() not in model.lower():
                result["camera"] = f"{make} {model}"
            else:
                result["camera"] = model
        elif make:
            result["camera"] = make

        # Map DJI camera codes to friendly drone names
        if result.get("camera") and "DJI" in result["camera"]:
            for code, drone_name in DJI_CAMERA_MAP.items():
                if code in result["camera"]:
                    result["camera"] = f"DJI {drone_name}"
                    break
        # Exposure time (tag 33434)
        exp = exif.get(33434)
        if exp:
            if exp < 1:
                result["shutter"] = f"1/{int(round(1 / exp))}s"
            else:
                result["shutter"] = f"{exp}s"
        # F-number (tag 33437)
        fn = exif.get(33437)
        if fn:
            result["aperture"] = f"f/{float(fn):g}"
        # ISO (tag 34855)
        iso = exif.get(34855)
        if iso:
            result["iso"] = str(iso)
        # Focal length (tag 37386)
        fl = exif.get(37386)
        if fl:
            result["focal_length"] = f"{float(fl):g}mm"
        # Lens model (tag 42036)
        lens = (exif.get(42036) or "").strip()
        if lens:
            result["lens"] = lens
    except Exception:
        pass
    return result


def generate_sidecar(filepath, exif_meta):
    """Generate a .md sidecar file from EXIF metadata."""
    sidecar_path = filepath.with_suffix(".md")
    lines = ["---"]
    for key in ("camera", "lens", "focal_length", "aperture", "shutter", "iso"):
        if key in exif_meta:
            lines.append(f"{key}: {exif_meta[key]}")
    lines.append("---")
    lines.append("")
    sidecar_path.write_text("\n".join(lines), encoding="utf-8")
    return sidecar_path


def get_dimensions(filepath):
    with Image.open(filepath) as img:
        return img.width, img.height


def slugify(name):
    slug = Path(name).stem.lower()
    slug = re.sub(r'[^a-z0-9\-]', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug


def inline_markdown(text):
    """Convert inline markdown (links, code, bold, italic) to HTML."""
    text = html_escape(text)
    # inline code: `code`
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # links: [text](url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    # bold: **text** or __text__
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__([^_]+)__', r'<strong>\1</strong>', text)
    # italic: *text* or _text_
    text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)
    text = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', r'<em>\1</em>', text)
    return text


def parse_sidecar(sidecar_path):
    """Parse a markdown sidecar file with optional YAML-like front matter."""
    text = sidecar_path.read_text(encoding="utf-8")
    meta = {}
    body = text

    # Extract front matter between --- delimiters
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            current_key = None
            for line in parts[1].strip().splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                # List item (  - value)
                if stripped.startswith("- ") and current_key:
                    meta.setdefault(current_key, []).append(stripped[2:].strip())
                elif ":" in stripped:
                    key, val = stripped.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    current_key = key
                    if val:
                        meta[key] = val
            body = parts[2].strip()

    # Extract title from first # heading, rest is description
    title = None
    description_lines = []
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# ") and title is None:
            title = stripped[2:].strip()
        elif title is not None:
            description_lines.append(line)

    description = "\n".join(description_lines).strip()

    # Normalize tags to list
    tags = meta.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    return {
        "title": title,
        "description": description if description else None,
        "author": meta.get("author"),
        "tags": tags,
        "camera": meta.get("camera"),
        "lens": meta.get("lens"),
        "focal_length": meta.get("focal_length"),
        "aperture": meta.get("aperture"),
        "shutter": meta.get("shutter"),
        "iso": meta.get("iso"),
        "has_metadata": True,
    }


def scan_and_sort_pictures():
    """Scan source directory and return sorted picture list."""
    image_files = sorted(
        p for p in SOURCE_DIR.iterdir()
        if p.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not image_files:
        print("   No image files found!")
        sys.exit(1)

    pictures = []
    for filepath in image_files:
        slug = slugify(filepath.name)
        exif_date = get_exif_date(filepath)
        width, height = get_dimensions(filepath)
        ext = ".gif" if filepath.suffix.lower() == ".gif" else ".webp"
        pic = {
            "slug": slug,
            "filename": f"{slug}{ext}",
            "width": width,
            "height": height,
            "exif_date": exif_date,
            "source_path": filepath,
            "has_metadata": False,
            "title": None,
            "description": None,
            "author": None,
            "tags": [],
            "camera": None,
            "lens": None,
            "focal_length": None,
            "aperture": None,
            "shutter": None,
            "iso": None,
        }
        sidecar = filepath.with_suffix(".md")
        if not sidecar.exists():
            exif_meta = get_exif_metadata(filepath)
            if exif_meta:
                generate_sidecar(filepath, exif_meta)
        if sidecar.exists():
            pic.update(parse_sidecar(sidecar))
        pictures.append(pic)

    pictures.sort(key=lambda p: p["exif_date"], reverse=True)
    return pictures


def calculate_library_stats(pictures):
    """Calculate statistics about the photo library."""
    stats = {
        "total": len(pictures),
        "cameras": {},
        "apertures": {},
        "focal_lengths": {},
        "orientations": {"portrait": 0, "landscape": 0, "square": 0},
        "time_of_day": {"night": 0, "morning": 0, "afternoon": 0, "evening": 0},
        "seasons": {"winter": 0, "spring": 0, "summer": 0, "fall": 0},
        "oldest_date": None,
        "newest_date": None
    }

    for pic in pictures:
        # Orientation
        if pic["width"] < pic["height"]:
            stats["orientations"]["portrait"] += 1
        elif pic["width"] > pic["height"]:
            stats["orientations"]["landscape"] += 1
        else:
            stats["orientations"]["square"] += 1

        # Camera
        if pic.get("camera"):
            camera = pic["camera"]
            stats["cameras"][camera] = stats["cameras"].get(camera, 0) + 1

        # Aperture
        if pic.get("aperture"):
            aperture = pic["aperture"]
            stats["apertures"][aperture] = stats["apertures"].get(aperture, 0) + 1

        # Focal length
        if pic.get("focal_length"):
            fl = pic["focal_length"]
            stats["focal_lengths"][fl] = stats["focal_lengths"].get(fl, 0) + 1

        # Date range
        if pic.get("exif_date"):
            date = pic["exif_date"]
            if stats["oldest_date"] is None or date < stats["oldest_date"]:
                stats["oldest_date"] = date
            if stats["newest_date"] is None or date > stats["newest_date"]:
                stats["newest_date"] = date

            # Time of day (hour 0-23)
            hour = date.hour
            if 0 <= hour < 6 or 20 <= hour < 24:
                stats["time_of_day"]["night"] += 1
            elif 6 <= hour < 12:
                stats["time_of_day"]["morning"] += 1
            elif 12 <= hour < 17:
                stats["time_of_day"]["afternoon"] += 1
            else:  # 17-20
                stats["time_of_day"]["evening"] += 1

            # Season (month 1-12)
            month = date.month
            if month in [12, 1, 2]:
                stats["seasons"]["winter"] += 1
            elif month in [3, 4, 5]:
                stats["seasons"]["spring"] += 1
            elif month in [6, 7, 8]:
                stats["seasons"]["summer"] += 1
            else:  # 9, 10, 11
                stats["seasons"]["fall"] += 1

    # Sort by frequency (descending)
    stats["cameras"] = dict(sorted(stats["cameras"].items(), key=lambda x: x[1], reverse=True))
    stats["apertures"] = dict(sorted(stats["apertures"].items(), key=lambda x: x[1], reverse=True))
    stats["focal_lengths"] = dict(sorted(stats["focal_lengths"].items(), key=lambda x: x[1], reverse=True))

    return stats


def generate_stats_modal_html(stats):
    """Generate HTML for the library statistics modal."""
    total = stats["total"]

    # Format date range
    date_range = ""
    if stats["oldest_date"] and stats["newest_date"]:
        oldest = stats["oldest_date"].strftime("%B %Y")
        newest = stats["newest_date"].strftime("%B %Y")
        date_range = f"{oldest} – {newest}"

    # Orientation percentages
    orientations = stats["orientations"]
    portrait_pct = round(100 * orientations["portrait"] / total) if total > 0 else 0
    landscape_pct = round(100 * orientations["landscape"] / total) if total > 0 else 0
    square_pct = round(100 * orientations["square"] / total) if total > 0 else 0

    # Top cameras (limit to top 8)
    camera_rows = ""
    for camera, count in list(stats["cameras"].items())[:8]:
        pct = round(100 * count / total) if total > 0 else 0
        camera_rows += f'''
        <tr>
          <td>{html_escape(camera)}</td>
          <td>{count}</td>
          <td>
            <div class="stat-bar">
              <div class="stat-fill" style="width: {pct}%"></div>
            </div>
          </td>
        </tr>'''

    # Top 2 apertures
    aperture_items = list(stats["apertures"].items())[:2]
    aperture_text = " · ".join([f'<span class="aperture-badge">{html_escape(ap)}</span> ({count})' for ap, count in aperture_items]) if aperture_items else "—"

    # Top 2 focal lengths
    focal_items = list(stats["focal_lengths"].items())[:2]
    focal_text = " · ".join([f"{html_escape(fl)} ({count})" for fl, count in focal_items]) if focal_items else "—"

    # Time of day percentages
    tod = stats["time_of_day"]
    tod_total = sum(tod.values())
    morning_pct = round(100 * tod["morning"] / tod_total) if tod_total > 0 else 0
    afternoon_pct = round(100 * tod["afternoon"] / tod_total) if tod_total > 0 else 0
    evening_pct = round(100 * tod["evening"] / tod_total) if tod_total > 0 else 0
    night_pct = round(100 * tod["night"] / tod_total) if tod_total > 0 else 0

    # Season percentages
    seasons = stats["seasons"]
    season_total = sum(seasons.values())
    winter_pct = round(100 * seasons["winter"] / season_total) if season_total > 0 else 0
    spring_pct = round(100 * seasons["spring"] / season_total) if season_total > 0 else 0
    summer_pct = round(100 * seasons["summer"] / season_total) if season_total > 0 else 0
    fall_pct = round(100 * seasons["fall"] / season_total) if season_total > 0 else 0

    # Determine the most common time of day and season
    tod_pcts = {"morning": morning_pct, "afternoon": afternoon_pct, "evening": evening_pct, "night": night_pct}
    top_tod = max(tod_pcts, key=tod_pcts.get)
    season_pcts = {"spring": spring_pct, "summer": summer_pct, "fall": fall_pct, "winter": winter_pct}
    top_season = max(season_pcts, key=season_pcts.get)

    # Read season icon SVGs for inlining
    icon_dir = STATIC_DIR / "img"
    icon_winter = (icon_dir / "icon-winter.svg").read_text().strip()
    icon_spring = (icon_dir / "icon-spring.svg").read_text().strip()
    icon_summer = (icon_dir / "icon-summer.svg").read_text().strip()
    icon_fall = (icon_dir / "icon-fall.svg").read_text().strip()

    return f'''
<div id="library-stats" class="stats-modal" style="display: none;">
  <div class="stats-overlay"></div>
  <div class="stats-content">
    <div class="stats-header">
      <h2>Jakub Steiner: Shooting Stats</h2>
      <a href="#" class="button close" title="Close">Close</a>
    </div>

    <div class="stats-body">
      <div class="stats-hero">
        <div class="stat-big">{total} Photos</div>
        <div class="stat-subtitle">{date_range}</div>
      </div>

      <section class="stats-section">
        <h3>Camera Models</h3>
        <table class="stats-table">
          <tbody>{camera_rows}
          </tbody>
        </table>
      </section>

      <div class="stats-grid">
        <section class="stats-section">
          <h3>Aperture</h3>
          <div class="stat-text">{aperture_text}</div>
        </section>

        <section class="stats-section">
          <h3>Focal Length</h3>
          <div class="stat-text">{focal_text}</div>
        </section>
      </div>

      <section class="stats-section">
        <h3>Orientation</h3>
        <div class="orientation-bars">
          <div class="orientation-row">
            <span>Portrait</span>
            <div class="stat-bar">
              <div class="stat-fill" style="width: {portrait_pct}%"></div>
            </div>
            <span>{portrait_pct}%</span>
          </div>
          <div class="orientation-row">
            <span>Landscape</span>
            <div class="stat-bar">
              <div class="stat-fill" style="width: {landscape_pct}%"></div>
            </div>
            <span>{landscape_pct}%</span>
          </div>
          <div class="orientation-row">
            <span>Square</span>
            <div class="stat-bar">
              <div class="stat-fill" style="width: {square_pct}%"></div>
            </div>
            <span>{square_pct}%</span>
          </div>
        </div>
      </section>

      <section class="stats-section">
        <h3>Time of Day</h3>
        <div class="stat-badges">
          <div class="stat-badge{' top' if top_tod == 'morning' else ''}"><span class="stat-label">Morning</span><span class="stat-pct">{morning_pct}%</span><div class="stat-bar"><div class="stat-fill" style="width: {morning_pct}%"></div></div></div>
          <div class="stat-badge{' top' if top_tod == 'afternoon' else ''}"><span class="stat-label">Afternoon</span><span class="stat-pct">{afternoon_pct}%</span><div class="stat-bar"><div class="stat-fill" style="width: {afternoon_pct}%"></div></div></div>
          <div class="stat-badge{' top' if top_tod == 'evening' else ''}"><span class="stat-label">Evening</span><span class="stat-pct">{evening_pct}%</span><div class="stat-bar"><div class="stat-fill" style="width: {evening_pct}%"></div></div></div>
          <div class="stat-badge{' top' if top_tod == 'night' else ''}"><span class="stat-label">Night</span><span class="stat-pct">{night_pct}%</span><div class="stat-bar"><div class="stat-fill" style="width: {night_pct}%"></div></div></div>
        </div>
      </section>

      <section class="stats-section">
        <h3>Seasons</h3>
        <div class="stat-badges">
          <div class="stat-badge{' top' if top_season == 'spring' else ''}"><span class="stat-label">{icon_spring} Spring</span><span class="stat-pct">{spring_pct}%</span><div class="stat-bar"><div class="stat-fill" style="width: {spring_pct}%"></div></div></div>
          <div class="stat-badge{' top' if top_season == 'summer' else ''}"><span class="stat-label">{icon_summer} Summer</span><span class="stat-pct">{summer_pct}%</span><div class="stat-bar"><div class="stat-fill" style="width: {summer_pct}%"></div></div></div>
          <div class="stat-badge{' top' if top_season == 'fall' else ''}"><span class="stat-label">{icon_fall} Fall</span><span class="stat-pct">{fall_pct}%</span><div class="stat-bar"><div class="stat-fill" style="width: {fall_pct}%"></div></div></div>
          <div class="stat-badge{' top' if top_season == 'winter' else ''}"><span class="stat-label">{icon_winter} Winter</span><span class="stat-pct">{winter_pct}%</span><div class="stat-bar"><div class="stat-fill" style="width: {winter_pct}%"></div></div></div>
        </div>
      </section>
      <p class="stats-footer">Like the photos? Check out <a href="https://blog.jimmac.eu">my blog</a> and <a href="https://art.jimmac.eu">digital art</a>.</p>
    </div>
  </div>
</div>'''


def process_image(src_path, slug):
    is_gif = src_path.suffix.lower() == ".gif"
    for size_name, max_dims in SIZES.items():
        out_dir = OUTPUT_DIR / "pictures" / size_name
        out_dir.mkdir(parents=True, exist_ok=True)

        if is_gif:
            out_path = out_dir / f"{slug}.gif"
            if out_path.exists() and out_path.stat().st_mtime > src_path.stat().st_mtime:
                continue
            shutil.copy2(src_path, out_path)
        else:
            out_path = out_dir / f"{slug}.webp"
            if out_path.exists() and out_path.stat().st_mtime > src_path.stat().st_mtime:
                continue
            with Image.open(src_path) as img:
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA" if img.mode in ("LA", "PA") or "transparency" in img.info else "RGB")
                img.thumbnail(max_dims, Image.Resampling.LANCZOS)
                img.save(out_path, "WEBP", quality=85)


def copy_static_assets():
    """Copy static assets (CSS, icons, favicons) to public/."""
    for subdir in ("css", "img"):
        src = STATIC_DIR / subdir
        dst = OUTPUT_DIR / subdir
        if src.exists():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    for filename in ("favicon.svg", "favicon.png", "social-preview.png", "touch-icon-iphone.png"):
        src = STATIC_DIR / filename
        if src.exists():
            shutil.copy2(src, OUTPUT_DIR / filename)


def copy_originals(pictures):
    """Copy original pictures for download."""
    orig_dir = OUTPUT_DIR / "pictures" / "original"
    orig_dir.mkdir(parents=True, exist_ok=True)
    for pic in pictures:
        src = pic["source_path"]
        dst = orig_dir / src.name
        if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
            shutil.copy2(src, dst)


def generate_picture_html(pic, index, pictures, config):
    """Generate the HTML for a single picture <li> element."""
    slug = pic["slug"]
    safe_name = quote(pic["filename"])
    w, h = pic["width"], pic["height"]
    has_meta = pic.get("has_metadata", False)
    display_name = pic.get("title") or slug
    meta_attr = ' data-has-meta="true"' if has_meta else ""

    lines = [
        f'      <li class="item" id="id-{slug}" title="{html_escape(display_name)}"{meta_attr}>',
        f'        <figure>',
        f'          <img loading="lazy"',
        f'               src="/pictures/thumbnail/{safe_name}"',
        f'               srcset="/pictures/thumbnail/{safe_name} 640w, /pictures/large/{safe_name} 2048w"',
        f'               sizes="(min-width: 900px) 33vw, (min-width: 600px) 50vw, 100vw"',
        f'               width="{w}" height="{h}" alt="{html_escape(display_name)}">',
    ]

    if has_meta:
        lines.append(f'          <figcaption class="caption">')
        pin_btn = '<button class="caption-pin" aria-label="Pin caption" title="Pin caption"></button>'
        if pic.get("title"):
            lines.append(f'            <strong class="caption-title">{html_escape(pic["title"])}{pin_btn}</strong>')
        elif pic.get("description"):
            lines.append(f'            {pin_btn}')
        if pic.get("description"):
            lines.append(f'            <span class="caption-desc">{inline_markdown(pic["description"])}</span>')
        # EXIF info line: camera + exposure details, f-stop as badge
        exif_parts = []
        if pic.get("camera"):
            exif_parts.append(html_escape(pic["camera"]))

        # Build exposure string with aperture as special badge (with bullets)
        exposure = []
        if pic.get("focal_length"):
            exposure.append(html_escape(pic["focal_length"]))
        if pic.get("aperture"):
            exposure.append(f'<span class="aperture-badge">{html_escape(pic["aperture"])}</span>')
        if pic.get("shutter"):
            exposure.append(html_escape(pic["shutter"]))
        if pic.get("iso"):
            exposure.append(f'ISO {html_escape(pic["iso"])}')

        if exif_parts or exposure:
            camera_str = exif_parts[0] if exif_parts else ""
            exposure_str = " \u2022 ".join(exposure)
            if camera_str and exposure_str:
                info = f'{camera_str} \u2014 {exposure_str}'
            else:
                info = camera_str or exposure_str
            lines.append(f'            <span class="caption-exif">{info}</span>')
        if pic.get("tags"):
            tags_str = ", ".join(pic["tags"])
            lines.append(f'            <span class="caption-tags">{html_escape(tags_str)}</span>')
        lines.append(f'          </figcaption>')

    lines.append(f'        </figure>')
    lines.append(f'        <a class="open" href="#{slug}" data-target="id-{slug}">Open</a>')

    if index > 0:
        ps = pictures[index - 1]["slug"]
        lines.append(f'        <a href="#{ps}" class="previous" title="Previous"><span class="button large">Previous</span></a>')

    if index < len(pictures) - 1:
        ns = pictures[index + 1]["slug"]
        lines.append(f'        <a href="#{ns}" class="next" title="Next"><span class="button large">Next</span></a>')

    lines.append(f'        <div class="actions">')
    if config.get("allow_image_sharing"):
        lines.append(f'          <a class="button share" href="#" data-share-slug="{slug}" data-share-title="{html_escape(display_name)}" title="Share">Share</a>')
    if config.get("allow_original_download"):
        orig_name = quote(pic["source_path"].name)
        lines.append(f'          <a class="button download" href="/pictures/original/{orig_name}" download="{orig_name}" title="Download">Download</a>')
    lines.append(f'          <a class="button close" href="#" title="Close">Close</a>')
    lines.append(f'        </div>')
    lines.append(f'      </li>')

    return "\n".join(lines)


def generate_javascript(config):
    """Generate the inline JavaScript for the gallery."""
    site_title = config.get("title", "photo.jimmac.eu")

    return f"""<script>
  const TARGET_CLASS = 'target';

  let xDown = null;
  document.addEventListener('touchstart', (e) => {{
    if (currentId()) xDown = e.touches[0].clientX;
  }});
  document.addEventListener('touchmove', (e) => {{
    if (!xDown) return;
    e.preventDefault();
    const diff = xDown - e.touches[0].clientX;
    if (Math.abs(diff) < 30) return;
    if (diff > 0) {{ navDirection = 'next'; clickNav('.next'); }}
    else {{ navDirection = 'prev'; clickNav('.previous'); }}
    xDown = null;
  }}, {{ passive: false }});

  const showToast = (msg) => {{
    const el = document.createElement('div');
    el.className = 'toast';
    el.textContent = msg;
    document.body.appendChild(el);
    el.addEventListener('animationend', () => el.remove());
  }};

  const shareImage = (title, slug) => {{
    const url = window.location.origin + '/' + slug + '/';
    if (navigator.canShare) {{
      navigator.share({{ title, url }});
    }} else {{
      navigator.clipboard.writeText(url).then(() => showToast('Link copied to clipboard'));
    }}
  }};

  const currentId = () => {{
    const hash = location.hash.slice(1);
    return hash ? 'id-' + hash : null;
  }};

  const clickNav = (cls) => {{
    const id = currentId();
    if (id) {{
      const btn = document.querySelector('#' + CSS.escape(id) + ' ' + cls);
      btn?.click();
    }}
  }};

  const tintCanvas = document.createElement('canvas');
  const tintCtx = tintCanvas.getContext('2d', {{ willReadFrequently: true }});

  const sampleBorderColors = (img) => {{
    try {{
      // Make sure image is loaded and complete
      if (!img.complete || !img.naturalWidth) {{
        return 'radial-gradient(ellipse at center, rgb(28,28,28) 0%, rgb(14,14,14) 100%)';
      }}

      // Sample size for edge detection
      const sampleSize = 64;
      const edgeWidth = 8; // How many pixels from the edge to sample

      tintCanvas.width = sampleSize;
      tintCanvas.height = sampleSize;
      tintCtx.drawImage(img, 0, 0, sampleSize, sampleSize);

      let r = 0, g = 0, b = 0, count = 0;

      // Sample top edge
      for (let x = 0; x < sampleSize; x++) {{
        for (let y = 0; y < edgeWidth; y++) {{
          const pixel = tintCtx.getImageData(x, y, 1, 1).data;
          r += pixel[0]; g += pixel[1]; b += pixel[2]; count++;
        }}
      }}

      // Sample bottom edge
      for (let x = 0; x < sampleSize; x++) {{
        for (let y = sampleSize - edgeWidth; y < sampleSize; y++) {{
          const pixel = tintCtx.getImageData(x, y, 1, 1).data;
          r += pixel[0]; g += pixel[1]; b += pixel[2]; count++;
        }}
      }}

      // Sample left edge
      for (let x = 0; x < edgeWidth; x++) {{
        for (let y = edgeWidth; y < sampleSize - edgeWidth; y++) {{
          const pixel = tintCtx.getImageData(x, y, 1, 1).data;
          r += pixel[0]; g += pixel[1]; b += pixel[2]; count++;
        }}
      }}

      // Sample right edge
      for (let x = sampleSize - edgeWidth; x < sampleSize; x++) {{
        for (let y = edgeWidth; y < sampleSize - edgeWidth; y++) {{
          const pixel = tintCtx.getImageData(x, y, 1, 1).data;
          r += pixel[0]; g += pixel[1]; b += pixel[2]; count++;
        }}
      }}

      r = Math.round(r / count);
      g = Math.round(g / count);
      b = Math.round(b / count);

      // Darken the color for better contrast with photo
      const darkenFactor = 0.55;
      const r1 = Math.round(r * darkenFactor);
      const g1 = Math.round(g * darkenFactor);
      const b1 = Math.round(b * darkenFactor);

      // Even darker for outer edges
      const darkerFactor = 0.35;
      const r2 = Math.round(r * darkerFactor);
      const g2 = Math.round(g * darkerFactor);
      const b2 = Math.round(b * darkerFactor);

      // Create a radial gradient for depth
      return `radial-gradient(ellipse at center, rgb(${{r1}},${{g1}},${{b1}}) 0%, rgb(${{r2}},${{g2}},${{b2}}) 100%)`;
    }} catch (e) {{
      // Fallback to dark gray gradient on error
      return 'radial-gradient(ellipse at center, rgb(28,28,28) 0%, rgb(14,14,14) 100%)';
    }}
  }};

  let navDirection = null;
  let captionTimer = null;
  let captionPinned = false;
  let captionManuallyHidden = false;

  const showCaption = (item, animate) => {{
    const caption = item.querySelector('.caption');
    if (!caption) return;
    caption.classList.remove('faded');
    const kids = caption.querySelectorAll(':scope > *');
    if (animate) {{
      kids.forEach(c => {{ c.style.animation = 'none'; c.offsetHeight; c.style.animation = ''; }});
    }} else {{
      kids.forEach(c => c.style.animation = 'none');
    }}

    // Show pager and action buttons
    const previous = item.querySelector('.previous');
    const next = item.querySelector('.next');
    const actions = item.querySelector('.actions');
    if (previous) previous.classList.remove('faded');
    if (next) next.classList.remove('faded');
    if (actions) actions.classList.remove('faded');

    clearTimeout(captionTimer);
    if (!captionPinned) {{
      captionTimer = setTimeout(() => {{
        caption.classList.add('faded');
        if (previous) previous.classList.add('faded');
        if (next) next.classList.add('faded');
        if (actions) actions.classList.add('faded');
      }}, 2000);
    }}
  }};

  const hideCaption = (item) => {{
    const caption = item.querySelector('.caption');
    if (!caption) return;
    caption.classList.add('faded');

    // Hide pager and action buttons
    const previous = item.querySelector('.previous');
    const next = item.querySelector('.next');
    const actions = item.querySelector('.actions');
    if (previous) previous.classList.add('faded');
    if (next) next.classList.add('faded');
    if (actions) actions.classList.add('faded');

    clearTimeout(captionTimer);
  }};

  const toggleCaption = () => {{
    const id = currentId();
    if (!id) return;
    const item = document.getElementById(id);
    if (!item) return;
    const caption = item.querySelector('.caption');
    if (!caption) return;
    if (caption.classList.contains('faded')) {{
      captionManuallyHidden = false;
      showCaption(item);
    }} else {{
      captionManuallyHidden = true;
      captionPinned = false;
      item.querySelectorAll('.caption-pin.pinned').forEach(p => p.classList.remove('pinned'));
      hideCaption(item);
    }}
  }};

  const setMeta = (prop, content) => {{
    const el = document.querySelector('meta[property="' + prop + '"],meta[name="' + prop + '"]');
    if (el) el.setAttribute('content', content);
  }};

  const updateMeta = (slug, imgUrl) => {{
    const url = window.location.origin + '/' + slug + '/';
    setMeta('og:title', slug);
    setMeta('og:url', url);
    setMeta('og:image', imgUrl);
    setMeta('twitter:title', slug);
    setMeta('twitter:image', imgUrl);
    setMeta('thumbnail', imgUrl);
  }};

  const resetMeta = () => {{
    const t = document.querySelector('title');
    const title = t.dataset.title;
    const origin = window.location.origin;
    const preview = origin + '/social-preview.png';
    setMeta('og:title', title);
    setMeta('og:url', origin + '/');
    setMeta('og:image', preview);
    setMeta('twitter:title', title);
    setMeta('twitter:image', preview);
    setMeta('thumbnail', preview);
  }};

  const openPhoto = (id) => {{
    const photo = document.getElementById(id);
    if (!photo) return;
    removeTargetClass();
    captionPinned = false;
    captionManuallyHidden = false;
    document.querySelectorAll('.caption-pin.pinned').forEach(p => p.classList.remove('pinned'));
    document.body.style.overflow = 'hidden';
    photo.classList.add(TARGET_CLASS);
    if (navDirection) {{
      photo.classList.add(navDirection === 'next' ? 'slide-next' : 'slide-prev');
      photo.addEventListener('animationend', () => {{
        photo.classList.remove('slide-next', 'slide-prev');
      }}, {{ once: true }});
      navDirection = null;
    }}
    const img = photo.querySelector('img');
    if (img) {{
      // Set backdrop based on border colors
      const tint = sampleBorderColors(img);
      photo.style.backgroundImage = tint;

      img.dataset.thumb = img.src;
      img.dataset.srcset = img.getAttribute('srcset') || '';
      img.dataset.sizes = img.getAttribute('sizes') || '';
      img.removeAttribute('srcset');
      img.removeAttribute('sizes');
      img.src = img.dataset.thumb.replace('/pictures/thumbnail/', '/pictures/large/');
      updateMeta(photo.title, img.dataset.thumb);
    }}
    showCaption(photo, true);
    document.title = photo.title;
  }};

  const closePhoto = () => {{
    clearTimeout(captionTimer);
    captionPinned = false;
    document.querySelectorAll('.caption-pin.pinned').forEach(p => p.classList.remove('pinned'));
    document.querySelectorAll('.' + TARGET_CLASS).forEach(item => {{
      item.style.backgroundImage = '';
    }});
    document.querySelectorAll('.' + TARGET_CLASS + ' img[data-thumb]').forEach(img => {{
      img.src = img.dataset.thumb;
      if (img.dataset.srcset) img.setAttribute('srcset', img.dataset.srcset);
      if (img.dataset.sizes) img.setAttribute('sizes', img.dataset.sizes);
      delete img.dataset.thumb;
      delete img.dataset.srcset;
      delete img.dataset.sizes;
    }});
    removeTargetClass();
    document.body.style.overflow = '';
    document.title = document.querySelector('title').dataset.title;
    resetMeta();
  }};

  const removeTargetClass = () => {{
    document.querySelectorAll('.' + TARGET_CLASS).forEach(el => {{
      el.style.backgroundColor = '';
      el.classList.remove(TARGET_CLASS);
    }});
  }};

  const handleHash = () => {{
    const hash = location.hash.slice(1);
    if (hash) openPhoto('id-' + hash);
    else closePhoto();
  }};

  window.addEventListener('hashchange', handleHash);

  document.addEventListener('keydown', (e) => {{
    if (e.key === 'Escape')     {{ location.hash = ''; e.preventDefault(); }}
    if (e.key === 'ArrowRight') {{ navDirection = 'next'; clickNav('.next'); e.preventDefault(); }}
    if (e.key === 'ArrowLeft')  {{ navDirection = 'prev'; clickNav('.previous'); e.preventDefault(); }}
    if (e.key === 'i' || e.key === 'I') {{ toggleCaption(); e.preventDefault(); }}
  }});

  document.addEventListener('mousemove', () => {{
    if (captionManuallyHidden) return;
    const id = currentId();
    if (!id) return;
    const item = document.getElementById(id);
    if (item) showCaption(item);
  }});

  document.addEventListener('click', (e) => {{
    const nav = e.target.closest('.previous[href], .next[href]');
    if (nav) {{
      e.preventDefault();
      navDirection = nav.classList.contains('previous') ? 'prev' : 'next';
      location.hash = nav.getAttribute('href').slice(1);
      return;
    }}
    const t = e.target.closest('[data-target][href]');
    if (t) {{
      e.preventDefault();
      location.hash = t.getAttribute('href').slice(1);
      return;
    }}
    const c = e.target.closest('.close[href]');
    if (c) {{
      e.preventDefault();
      history.replaceState(null, '', location.pathname);
      closePhoto();
      return;
    }}
    const pin = e.target.closest('.caption-pin');
    if (pin) {{
      e.preventDefault();
      e.stopPropagation();
      captionPinned = !captionPinned;
      pin.classList.toggle('pinned', captionPinned);
      pin.animate([
        {{ transform: 'scale(1)' }},
        {{ transform: 'scale(1.5)' }},
        {{ transform: 'scale(1)' }}
      ], {{ duration: 300, easing: 'cubic-bezier(.22, 1.07, .36, 1)' }});
      if (captionPinned) {{
        clearTimeout(captionTimer);
      }} else {{
        const id = currentId();
        if (id) {{
          const item = document.getElementById(id);
          if (item) showCaption(item);
        }}
      }}
      return;
    }}
    const s = e.target.closest('[data-share-slug]');
    if (s) {{
      e.preventDefault();
      shareImage(s.dataset.shareTitle, s.dataset.shareSlug);
      return;
    }}
    // Click on empty canvas area toggles caption/buttons visibility
    if (currentId() && e.target.closest('.' + TARGET_CLASS)) {{
      toggleCaption();
    }}
  }});

  if (location.hash) handleHash();

  const statsModal = document.getElementById('library-stats');
  const statsClose = document.querySelector('.stats-header .close');
  const statsOverlay = document.querySelector('.stats-overlay');

  // Open stats modal
  document.addEventListener('click', (e) => {{
    if (e.target.closest('a[href="#library-stats"]')) {{
      e.preventDefault();
      statsModal.style.display = 'grid';
      document.body.style.overflow = 'hidden';
    }}
  }});

  // Close stats modal
  const closeStats = () => {{
    statsModal.style.display = 'none';
    document.body.style.overflow = '';
  }};

  if (statsClose) statsClose.addEventListener('click', (e) => {{
    e.preventDefault();
    closeStats();
  }});
  if (statsOverlay) statsOverlay.addEventListener('click', closeStats);

  // Close on Escape key
  document.addEventListener('keydown', (e) => {{
    if (e.key === 'Escape' && statsModal.style.display !== 'none') {{
      closeStats();
    }}
  }});
</script>"""


def generate_index_html(pictures, stats, config):
    """Generate the complete single-page HTML."""
    site_title = config.get("title", "photo.jimmac.eu")
    description = config.get("description", "")
    base_url = config.get("base_url", "")
    mastodon = config.get("mastodon_username", "")

    noindex = ""
    if not config.get("allow_indexing", True):
        noindex = '\n    <meta name="robots" content="noindex">'

    mastodon_link = ""
    if mastodon:
        mastodon_link = f'\n    <link rel="me" href="https://mastodon.social/@{mastodon}">'

    picture_items = "\n".join(
        generate_picture_html(p, i, pictures, config)
        for i, p in enumerate(pictures)
    )

    social = []
    if mastodon:
        social.append(f'        <li class="mastodon"><a class="button" rel="me" href="https://mastodon.social/@{mastodon}" title="Mastodon">Mastodon</a></li>')
    github = config.get("github_username", "")
    if github:
        social.append(f'        <li class="github"><a class="button" rel="me" href="https://github.com/{github}" title="Github">Github</a></li>')
    instagram = config.get("instagram_username", "")
    if instagram:
        social.append(f'        <li class="instagram"><a class="button" rel="me" href="https://instagram.com/{instagram}" title="Instagram">Instagram</a></li>')
    pixelfed = config.get("pixelfed_username", "")
    if pixelfed:
        social.append(f'        <li class="pixelfed"><a class="button" rel="me" href="https://pixelfed.social/{pixelfed}" title="Pixelfed">Pixelfed</a></li>')
    cname = config.get("custom_link_name", "")
    curl = config.get("custom_link_url", "")
    if cname and curl:
        social.append(f'        <li class="avatar"><a class="button" rel="me" href="{curl}" title="{cname}"><img src="/img/avatar.svg" alt="{cname}" /></a></li>')
    social.append(f'        <li class="info"><a class="button" href="#library-stats" title="Library Summary">Info</a></li>')
    social.append(f'        <li class="rss"><a class="button" href="{base_url}/feed.xml" title="RSS Feed">RSS</a></li>')
    social_html = "\n".join(social)

    stats_modal_html = generate_stats_modal_html(stats)

    js = generate_javascript(config)

    return f"""<!doctype html>
<html lang="en" class="notranslate" translate="no">
<head>
    <meta charset="utf-8">
    <meta name="google" content="notranslate">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">{noindex}
    <title data-title="{site_title}">{site_title}</title>
    <link rel="alternate" type="application/atom+xml" title="Atom Feed" href="{base_url}/feed.xml">
    <meta property="og:title" content="{site_title}">
    <meta property="og:type" content="website">
    <meta property="og:url" content="{base_url}/">
    <meta property="og:image" content="{base_url}/social-preview.png">
    <meta property="og:site_name" content="{site_title}">
    <meta property="og:description" content="{description}">
    <meta name="thumbnail" content="{base_url}/social-preview.png">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{site_title}">
    <meta name="twitter:description" content="{description}">
    <meta name="twitter:image" content="{base_url}/social-preview.png">
    <meta name="description" content="{description}">{mastodon_link}
    <link rel="stylesheet" href="/css/master.css">
    <link rel="icon" type="image/svg+xml" href="/favicon.svg">
    <link rel="icon" type="image/png" href="/favicon.png">
    <link rel="apple-touch-icon" href="/touch-icon-iphone.png">
    <link rel="mask-icon" href="/favicon.svg">
</head>
<body>
  <main>
    <ul class="grid" id="grid" role="list">
{picture_items}
    </ul>
  </main>
  <nav aria-label="Social links">
    <ul class="links">
{social_html}
    </ul>
  </nav>
{stats_modal_html}
{js}
</body>
</html>
"""


def generate_404_html(config):
    """Generate the 404 error page."""
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Not Even a Stopped Clock</title>
  <link rel="stylesheet" href="/css/master.css">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <link rel="icon" type="image/png" href="/favicon.png">
</head>
<body>
  <div class="four-oh-four">
    <h1>Not Even a Stopped Clock</h1>
    <p>404 - Page not found</p>
    <a href="/">Go home</a>
  </div>
</body>
</html>
"""


def generate_picture_stubs(pictures, config):
    """Generate lightweight stub pages for social media sharing."""
    base_url = config.get("base_url", "")
    site_title = config.get("title", "photo.jimmac.eu")
    description = config.get("description", "")

    for pic in pictures:
        slug = pic["slug"]
        safe_name = quote(pic["filename"])
        og_image = f"{base_url}/pictures/large/{safe_name}"
        display_name = html_escape(pic.get("title") or slug)
        pic_desc = html_escape(pic.get("description") or description)
        out_dir = OUTPUT_DIR / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{display_name} - {site_title}</title>
  <meta property="og:title" content="{display_name}">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{base_url}/{slug}/">
  <meta property="og:image" content="{og_image}">
  <meta property="og:site_name" content="{site_title}">
  <meta property="og:description" content="{pic_desc}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{display_name}">
  <meta name="twitter:description" content="{pic_desc}">
  <meta name="twitter:image" content="{og_image}">
  <script>location.replace('/#' + '{slug}');</script>
</head>
<body></body>
</html>
""")


def generate_feed_xml(pictures, config):
    """Generate an Atom feed."""
    site_title = config.get("title", "photo.jimmac.eu")
    description = config.get("description", "")
    base_url = config.get("base_url", "")
    author_name = config.get("author_name", "")
    author_email = config.get("author_email", "")
    author_website = config.get("author_website", "")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    author_block = ""
    if author_name or author_email or author_website:
        parts = []
        if author_name:
            parts.append(f"      <name>{html_escape(author_name)}</name>")
        if author_email:
            parts.append(f"      <email>{html_escape(author_email)}</email>")
        if author_website:
            parts.append(f"      <uri>{html_escape(author_website)}</uri>")
        author_block = "  <author>\n" + "\n".join(parts) + "\n  </author>\n"

    entries = []
    for pic in pictures[:20]:
        slug = pic["slug"]
        safe_name = quote(pic["filename"])
        date = pic["exif_date"].strftime("%Y-%m-%dT%H:%M:%S+00:00")
        entry_url = f"{base_url}/{slug}/"
        img_url = f"{base_url}/pictures/large/{safe_name}"

        entry_author = ""
        if author_name:
            a_parts = []
            if author_name:
                a_parts.append(f"        <name>{html_escape(author_name)}</name>")
            if author_email:
                a_parts.append(f"        <email>{html_escape(author_email)}</email>")
            if author_website:
                a_parts.append(f"        <uri>{html_escape(author_website)}</uri>")
            entry_author = "    <author>\n" + "\n".join(a_parts) + "\n    </author>\n"

        display_name = pic.get("title") or slug
        pic_desc = pic.get("description") or ""
        desc_html = f"<p>{html_escape(pic_desc)}</p>" if pic_desc else ""
        entries.append(f"""  <entry>
    <title type="html">{html_escape(display_name)}</title>
    <link href="{entry_url}" rel="alternate" type="text/html" title="{html_escape(display_name)}" />
    <published>{date}</published>
    <updated>{date}</updated>
    <id>{entry_url}</id>
    <content type="html"><![CDATA[<figure><a href="{entry_url}"><img src="{img_url}" alt="{html_escape(display_name)}" /></a></figure>{desc_html}]]></content>
{entry_author}    <media:thumbnail xmlns:media="http://search.yahoo.com/mrss/" url="{img_url}" />
    <media:content medium="image" url="{img_url}" xmlns:media="http://search.yahoo.com/mrss/" />
  </entry>""")

    entries_xml = "\n".join(entries)

    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <link href="{base_url}/feed.xml" rel="self" type="application/atom+xml" />
  <link href="{base_url}/" rel="alternate" type="text/html" />
  <updated>{now}</updated>
  <id>{base_url}/feed.xml</id>
  <title type="html"><![CDATA[{html_escape(site_title)}]]></title>
  <subtitle><![CDATA[{html_escape(description)}]]></subtitle>
{author_block}{entries_xml}
</feed>
"""


def main():
    if not SOURCE_DIR.exists():
        print(f"Error: Source directory '{SOURCE_DIR}' not found.")
        sys.exit(1)

    config = CONFIG

    clean = "--clean" in sys.argv
    if clean and OUTPUT_DIR.exists():
        print("Cleaning output directory...")
        shutil.rmtree(OUTPUT_DIR)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=== Building site ===\n")

    print("1. Normalizing file extensions...")
    normalize_extensions()

    print("2. Scanning pictures and extracting EXIF data...")
    pictures = scan_and_sort_pictures()
    stats = calculate_library_stats(pictures)
    print(f"   Found {len(pictures)} pictures")

    print("3. Processing images...")
    for i, pic in enumerate(pictures):
        sys.stdout.write(f"\r   Processing {i+1}/{len(pictures)}: {pic['source_path'].name}...")
        sys.stdout.flush()
        process_image(pic["source_path"], pic["slug"])
    print("\n   Done!")

    if config.get("allow_original_download"):
        print("4. Copying originals for download...")
        copy_originals(pictures)
    else:
        print("4. Skipping originals (download disabled)")

    print("5. Copying static assets...")
    copy_static_assets()

    print("6. Generating index.html...")
    (OUTPUT_DIR / "index.html").write_text(generate_index_html(pictures, stats, config))

    print("7. Generating 404.html...")
    (OUTPUT_DIR / "404.html").write_text(generate_404_html(config))

    print("8. Generating feed.xml...")
    (OUTPUT_DIR / "feed.xml").write_text(generate_feed_xml(pictures, config))

    print("9. Generating share stubs...")
    generate_picture_stubs(pictures, config)
    print(f"   Generated {len(pictures)} stubs")

    print(f"\n=== Build complete: {len(pictures)} pictures ===")


if __name__ == "__main__":
    main()
