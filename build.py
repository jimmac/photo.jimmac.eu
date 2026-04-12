#!/usr/bin/env python3
"""
Build script for art.jimmac.eu picture gallery.
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
    ".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp", ".gif", ".avif", ".heic", ".heif",
}


def read_config():
    """Parse config.toml for site settings."""
    config = {}
    config_path = Path("config.toml")
    if not config_path.exists():
        return config
    for line in config_path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("[") or stripped.startswith("#") or not stripped:
            continue
        if "=" in stripped:
            key, val = stripped.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"')
            if val == "true":
                val = True
            elif val == "false":
                val = False
            config[key] = val
    return config


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


def get_dimensions(filepath):
    with Image.open(filepath) as img:
        return img.width, img.height


def slugify(name):
    slug = Path(name).stem.lower()
    slug = re.sub(r'[^a-z0-9\-]', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug


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
        pictures.append({
            "slug": slug,
            "filename": f"{slug}.webp",
            "width": width,
            "height": height,
            "exif_date": exif_date,
            "source_path": filepath,
        })

    pictures.sort(key=lambda p: p["exif_date"], reverse=True)
    return pictures


def process_image(src_path, slug):
    for size_name, max_dims in SIZES.items():
        out_dir = OUTPUT_DIR / "pictures" / size_name
        out_dir.mkdir(parents=True, exist_ok=True)
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

    lines = [
        f'      <li class="item" id="id-{slug}" title="{slug}">',
        f'        <figure>',
        f'          <img loading="lazy"',
        f'               src="/pictures/thumbnail/{safe_name}"',
        f'               srcset="/pictures/thumbnail/{safe_name} 640w, /pictures/large/{safe_name} 2048w"',
        f'               sizes="(min-width: 900px) 33vw, (min-width: 600px) 50vw, 100vw"',
        f'               width="{w}" height="{h}" alt="{slug}">',
        f'        </figure>',
        f'        <a class="open" href="#{slug}" data-target="id-{slug}">Open</a>',
    ]

    if index > 0:
        ps = pictures[index - 1]["slug"]
        lines.append(f'        <a href="#{ps}" class="previous" title="Previous"><span>Previous</span></a>')

    if index < len(pictures) - 1:
        ns = pictures[index + 1]["slug"]
        lines.append(f'        <a href="#{ns}" class="next" title="Next"><span>Next</span></a>')

    lines.append(f'        <div class="actions">')
    if config.get("allow_image_sharing"):
        lines.append(f'          <a class="share" href="#" data-share-slug="{slug}" data-share-title="{slug}" title="Share">Share</a>')
    if config.get("allow_original_download"):
        orig_name = quote(pic["source_path"].name)
        lines.append(f'          <a class="download" href="/pictures/original/{orig_name}" download="{orig_name}" title="Download">Download</a>')
    lines.append(f'          <a class="close" href="#" title="Close">Close</a>')
    lines.append(f'        </div>')
    lines.append(f'      </li>')

    return "\n".join(lines)


def generate_javascript(config):
    """Generate the inline JavaScript for the gallery."""
    site_title = config.get("title", "art.jimmac.eu")

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
  tintCanvas.width = tintCanvas.height = 1;
  const tintCtx = tintCanvas.getContext('2d', {{ willReadFrequently: true }});

  const avgColor = (img) => {{
    try {{
      tintCtx.drawImage(img, 0, 0, 1, 1);
      const [r, g, b] = tintCtx.getImageData(0, 0, 1, 1).data;
      return `rgb(${{r}},${{g}},${{b}})`;
    }} catch (e) {{ return null; }}
  }};

  let navDirection = null;

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
      const tint = avgColor(img);
      if (tint) photo.style.backgroundColor = tint;
      img.dataset.thumb = img.src;
      img.dataset.srcset = img.getAttribute('srcset') || '';
      img.dataset.sizes = img.getAttribute('sizes') || '';
      img.removeAttribute('srcset');
      img.removeAttribute('sizes');
      img.src = img.dataset.thumb.replace('/pictures/thumbnail/', '/pictures/large/');
      updateMeta(photo.title, img.dataset.thumb);
    }}
    document.title = photo.title;
  }};

  const closePhoto = () => {{
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
    if (e.target.closest('.' + TARGET_CLASS + ' figure')) {{
      navDirection = 'next';
      clickNav('.next');
      return;
    }}
    const s = e.target.closest('[data-share-slug]');
    if (s) {{
      e.preventDefault();
      shareImage(s.dataset.shareTitle, s.dataset.shareSlug);
    }}
  }});

  if (location.hash) handleHash();
</script>"""


def generate_index_html(pictures, config):
    """Generate the complete single-page HTML."""
    site_title = config.get("title", "art.jimmac.eu")
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
        social.append(f'        <li class="mastodon"><a rel="me" href="https://mastodon.social/@{mastodon}" title="Mastodon">Mastodon</a></li>')
    github = config.get("github_username", "")
    if github:
        social.append(f'        <li class="github"><a rel="me" href="https://github.com/{github}" title="Github">Github</a></li>')
    instagram = config.get("instagram_username", "")
    if instagram:
        social.append(f'        <li class="instagram"><a rel="me" href="https://instagram.com/{instagram}" title="Instagram">Instagram</a></li>')
    cname = config.get("custom_link_name", "")
    curl = config.get("custom_link_url", "")
    if cname and curl:
        social.append(f'        <li class="link"><a rel="me" href="{curl}" title="{cname}">{cname}</a></li>')
    social_html = "\n".join(social)

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
    site_title = config.get("title", "art.jimmac.eu")
    description = config.get("description", "")

    for pic in pictures:
        slug = pic["slug"]
        safe_name = quote(pic["filename"])
        og_image = f"{base_url}/pictures/large/{safe_name}"
        out_dir = OUTPUT_DIR / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{slug} - {site_title}</title>
  <meta property="og:title" content="{slug}">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{base_url}/{slug}/">
  <meta property="og:image" content="{og_image}">
  <meta property="og:site_name" content="{site_title}">
  <meta property="og:description" content="{description}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{slug}">
  <meta name="twitter:description" content="{description}">
  <meta name="twitter:image" content="{og_image}">
  <script>location.replace('/#' + '{slug}');</script>
</head>
<body></body>
</html>
""")


def generate_feed_xml(pictures, config):
    """Generate an Atom feed."""
    site_title = config.get("title", "art.jimmac.eu")
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

        entries.append(f"""  <entry>
    <title type="html">{html_escape(slug)}</title>
    <link href="{entry_url}" rel="alternate" type="text/html" title="{html_escape(slug)}" />
    <published>{date}</published>
    <updated>{date}</updated>
    <id>{entry_url}</id>
    <content type="html"><![CDATA[<figure><a href="{entry_url}"><img src="{img_url}" alt="{html_escape(slug)}" /></a></figure>]]></content>
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

    config = read_config()

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
    (OUTPUT_DIR / "index.html").write_text(generate_index_html(pictures, config))

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
