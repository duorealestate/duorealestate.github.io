#!/usr/bin/env python3
"""Genera la web de dûo (una ficha por propiedad) desde el catálogo público de Notion.

Uso:
  python3 generar.py              # genera el sitio en WEB/sitio
  python3 generar.py --publicar   # además sube los cambios a GitHub Pages
  python3 generar.py --solo D079  # genera solo esas fichas (para probar)

Fuente: el Catálogo DÚO publicado en notion.site (solo lo que está en el catálogo;
las propiedades que salen del catálogo se borran del sitio). No necesita claves de Notion.
Fotos: en macOS usa `sips`; en otros sistemas (GitHub Actions en Linux) usa Pillow + pillow-heif.
"""
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

import enviar

RAIZ = Path(__file__).resolve().parent
# En GitHub Actions el código vive en <repo>/_fuente y el sitio es la raíz del repo (DUO_SITIO).
SITIO = Path(os.environ["DUO_SITIO"]) if os.environ.get("DUO_SITIO") else RAIZ / "sitio"
FUENTE = ["generar.py", "enviar.py", "config.json", "plantilla", "marca"]
MARCA = RAIZ / "marca"
# Sitio neutro para colegas (fichas-dre.github.io): mismas fichas sin marca, contacto ni rastro de dûo.
FICHAS = Path(os.environ["DUO_FICHAS"]) if os.environ.get("DUO_FICHAS") else RAIZ / "fichas"
CFG = json.loads((RAIZ / "config.json").read_text())

UA = "Mozilla/5.0 (Macintosh) duo-web/1.0"


# ---------- Notion (sitio público) ----------

def api(endpoint, payload, intentos=4):
    url = f"{CFG['notion_sitio']}/api/v3/{endpoint}"
    datos = json.dumps(payload).encode()
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, data=datos, headers={"content-type": "application/json", "user-agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # red inestable o límite de Notion
            if i == intentos - 1:
                raise
            time.sleep(2 * (i + 1))


def valor(registro):
    v = registro.get("value", {})
    return v.get("value", v)


def texto_plano(rich):
    return "".join(seg[0] for seg in (rich or []))


def leer_catalogo():
    space = CFG["notion_space_id"]
    r = api("queryCollection", {
        "collection": {"id": CFG["catalogo_collection_id"], "spaceId": space},
        "collectionView": {"id": CFG["catalogo_view_id"], "spaceId": space},
        "loader": {"type": "reducer", "reducers": {"collection_group_results": {"type": "results", "limit": 1000}},
                   "searchQuery": "", "userTimeZone": "America/Bogota"},
    })
    rm = r["recordMap"]
    coleccion = valor(next(iter(rm["collection"].values())))
    nombres = {k: s["name"] for k, s in coleccion["schema"].items()}
    props = []
    for bid in r["result"]["reducerResults"]["collection_group_results"]["blockIds"]:
        b = valor(rm["block"].get(bid, {}))
        if not b.get("properties") or not b.get("alive", True):
            continue
        p = {nombres.get(k, k): texto_plano(v) for k, v in b["properties"].items()}
        p["_id"] = bid
        props.append(p)
    return props


# ---------- Fuente: PROPIEDADES - interno (API oficial de Notion, solo lectura) ----------

# "Por verificar" es lo que deja el formulario: si ya trae fotos, sale de una vez (decisión de Camila, 26 oct. 2026).
# El estado en Notion lo cambia después Claude (la llave del generador es de solo lectura).
PUBLICABLES = {"Activa", "Oferta recibida", "Por completar", "Por verificar"}


def leer_interno():
    """Lee el interno y devuelve las propiedades publicables en el mismo formato que leer_catalogo(),
    con su cuerpo ya armado en "_cuerpo". Solo usa campos públicos: nunca Título (edificio), Número,
    propietario, Lo wow ni dirección."""
    token = enviar.secreto("NOTION_TOKEN", "duo-notion-token")
    if not token:
        sys.exit("Falta NOTION_TOKEN (llave de solo lectura de PROPIEDADES - interno).")
    filas, cursor = [], None
    while True:
        cuerpo = {"page_size": 100}
        if cursor:
            cuerpo["start_cursor"] = cursor
        for i in range(4):
            try:
                req = urllib.request.Request(
                    f"https://api.notion.com/v1/databases/{enviar.DB_INTERNA}/query", data=json.dumps(cuerpo).encode(),
                    headers={"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    d = json.load(r)
                break
            except Exception:
                if i == 3:
                    raise
                time.sleep(3 * (i + 1))
        filas += d["results"]
        if not d.get("has_more"):
            break
        cursor = d["next_cursor"]

    def v(pr, nombre):
        x = pr.get(nombre) or {}
        tipo = x.get("type")
        if tipo in ("title", "rich_text"):
            return "".join(t["plain_text"] for t in x[tipo]).strip()
        if tipo == "number":
            return x["number"]
        if tipo in ("select", "status"):
            return (x[tipo] or {}).get("name")
        if tipo == "multi_select":
            return [o["name"] for o in x[tipo]]
        if tipo == "formula":
            return (x["formula"] or {}).get((x["formula"] or {}).get("type"))
        if tipo == "files":
            return x["files"]
        return None

    texto = lambda n: "" if n in (None, "") else (str(int(n)) if float(n) == int(n) else str(n))
    props = []
    for fila in filas:
        pr = fila["properties"]
        codigo = (v(pr, "Código DÚO") or "").strip().upper()
        if v(pr, "Estado comercial") not in PUBLICABLES or not re.fullmatch(r"D\d{3}", codigo):
            continue
        tipo, sector = v(pr, "Tipo propiedad") or "", v(pr, "Sector") or ""
        area = v(pr, "Área lote m²") if tipo == "Lote" else v(pr, "Área construida m²")
        hab = v(pr, "Habitación de servicio")
        per = v(pr, "Periodicidad predial")
        titulo_web = v(pr, "Título web") or (f"{tipo} en {sector}" if sector else tipo)
        p = {"Código": codigo, "Tipo propiedad": tipo, "Sector": sector,
             "Título": f"{tipo} | {titulo_web} | {sector}",
             "Operación": ", ".join(v(pr, "Operación") or []),
             "Precio venta COP": texto(v(pr, "Precio venta COP")), "Canon mensual COP": texto(v(pr, "Canon arriendo COP")),
             "Área m²": texto(area), "Área exterior m²": texto(v(pr, "Área exterior m²")),
             "Alcobas": texto(v(pr, "Alcobas")), "Baños": texto(v(pr, "Baños")), "Parqueaderos": texto(v(pr, "Parqueaderos")),
             "Estrato": texto(v(pr, "Estrato")), "Hab servicio": hab if hab in ("Sí", "No") else "",
             "Administración COP": texto(v(pr, "Administración mensual COP")), "Predial COP": texto(v(pr, "Predial COP")),
             "Periodicidad predial": per if per and per != "Por confirmar" else "",
             "Lote m²": texto(v(pr, "Área lote m²")) if tipo == "Casa" else "",
             "Características": v(pr, "Características") or [], "Amenidades": v(pr, "Amenidades unidad") or [],
             "_id": fila["id"]}
        # Cuerpo con la misma forma que las fichas del catálogo: viñetas, y la descripción con la primera frase en negrita.
        cuerpo = [("texto", [["\n".join("• " + l.strip() for l in (v(pr, "Lo que tiene") or "").split("\n") if l.strip())]])]
        for i, parrafo in enumerate(x.strip() for x in re.split(r"\n\s*\n", v(pr, "Descripción pública") or "") if x.strip()):
            m = re.match(r"(.+?[.!?])\s+(.+)", parrafo, re.S) if i == 0 else None
            cuerpo.append(("texto", [[m.group(1), [["b"]]], [" " + m.group(2)]] if m else [[parrafo]]))
        cuerpo += fotos_de(v(pr, "Fotos") or [])
        p["_cuerpo"] = cuerpo
        props.append(p)
    return props


def fotos_de(archivos):
    """[('foto', (fuente, url firmada))] en orden. La fuente (attachment:<id>:<nombre>) no cambia aunque la URL venza."""
    salida = []
    for arch in archivos:
        url = (arch.get("file") or arch.get("external") or {}).get("url")
        if not url:
            continue
        ruta = urllib.parse.urlparse(url).path.strip("/").split("/")
        fuente = f"attachment:{ruta[-2]}:{urllib.parse.unquote(ruta[-1])}" if len(ruta) >= 2 else url
        salida.append(("foto", (fuente, url)))
    return salida


def fotos_al_dia(codigo, cuerpo):
    """True si todas las fotos ya están descargadas (no hace falta pedir URLs nuevas a Notion)."""
    carpeta = SITIO / "fotos" / codigo
    for k, x in cuerpo:
        if k == "foto":
            clave = hashlib.sha1(x[0].encode()).hexdigest()[:10]
            if not ((carpeta / f"{clave}.jpg").exists() and (carpeta / f"{clave}-800.jpg").exists()):
                return False
    return any(k == "foto" for k, _ in cuerpo)


def refrescar_fotos(p):
    """Las URLs firmadas de Notion vencen en minutos: se piden de nuevo justo antes de descargar."""
    token = enviar.secreto("NOTION_TOKEN", "duo-notion-token")
    req = urllib.request.Request(f"https://api.notion.com/v1/pages/{p['_id']}",
                                 headers={"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28"})
    with urllib.request.urlopen(req, timeout=60) as r:
        archivos = json.load(r)["properties"].get("Fotos", {}).get("files", [])
    p["_cuerpo"] = [x for x in p["_cuerpo"] if x[0] != "foto"] + fotos_de(archivos)


def leer_cuerpo(page_id):
    """Devuelve los bloques del cuerpo en orden: ('texto', rich) o ('foto', url)."""
    bloques, cursor, n = {}, {"stack": []}, 0
    while True:
        r = api("loadPageChunk", {"pageId": page_id, "limit": 100, "cursor": cursor,
                                  "chunkNumber": n, "verticalColumns": False})
        for k, v in r["recordMap"].get("block", {}).items():
            bloques[k] = valor(v)
        cursor = r.get("cursor", {"stack": []})
        n += 1
        if not cursor.get("stack"):
            break
    pagina = bloques.get(page_id, {})
    salida = []
    for cid in pagina.get("content", []):
        b = bloques.get(cid, {})
        if not b.get("alive", True):
            continue
        tipo = b.get("type")
        if tipo in ("text", "quote", "callout", "bulleted_list"):
            rich = b.get("properties", {}).get("title")
            if rich and texto_plano(rich).strip():
                salida.append(("texto", rich))
        elif tipo == "image":
            fuente = (b.get("format") or {}).get("display_source") or texto_plano(b.get("properties", {}).get("source"))
            if fuente:
                salida.append(("foto", url_foto(fuente, cid)))
    return salida


def url_foto(fuente, block_id):
    q = urllib.parse.urlencode({"table": "block", "id": block_id, "spaceId": CFG["notion_space_id"],
                                "width": 2000, "cache": "v2"})
    return f"{CFG['notion_sitio']}/image/{urllib.parse.quote(fuente, safe='')}?{q}"


# ---------- Reglas de privacidad (CLAUDE.md) ----------

PROHIBIDO = [
    (re.compile(r"\bpiso\s+(n[°º.]?\s*)?\d", re.I), "número de piso"),
    (re.compile(r"\b\d{1,2}\s*(°|º)?\s*piso\b", re.I), "número de piso"),
    (re.compile(r"\b(apto|apartamento|unidad|casa|torre|bloque)\.?\s*(n[°º.]?\s*)?#?\s*\d{2,4}\b(?!\s*(m²|m2|mts|metros|%))", re.I), "número de unidad"),
    (re.compile(r"\btorre\s+[A-Z0-9]\b", re.I), "torre"),
    (re.compile(r"\b(edificio|urbanizaci[oó]n|conjunto)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+"), "nombre de edificio"),
    (re.compile(r"\b(calle|carrera|cra|cl|cr|transversal|tv|diagonal|dg|circular|avenida|av)\.?\s*\d+", re.I), "dirección"),
    (re.compile(r"#\s*\d+\s*[-–]\s*\d+"), "dirección"),
]


def revisar_privacidad(*textos):
    problemas = []
    for t in textos:
        for patron, motivo in PROHIBIDO:
            m = patron.search(t or "")
            if m:
                problemas.append(f"{motivo}: «{m.group(0)}»")
    return problemas


# ---------- Formatos ----------

def numero(v):
    try:
        f = float(str(v).replace(",", "."))
    except ValueError:
        return None
    return f


def fmt_num(f):
    if f is None:
        return ""
    f = round(f, 1)  # 248,96 → 249 (y no "249,0")
    if f == int(f):
        return f"{int(f):,}".replace(",", ".")
    return f"{f:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_precio_venta(f):
    millones = f / 1_000_000
    return f"${fmt_num(round(millones, 1))} millones"


def fmt_pesos(f):
    return f"${fmt_num(f)}"


def esc(t):
    return html.escape(t or "", quote=True)


def rich_html(rich):
    partes = []
    for seg in rich:
        t = esc(seg[0]).replace("\n", "<br>")
        for a in (seg[1] if len(seg) > 1 else []):
            if a[0] == "b":
                t = f"<strong>{t}</strong>"
            elif a[0] == "i":
                t = f"<em>{t}</em>"
            elif a[0] == "a" and str(a[1]).startswith("http"):
                t = f'<a href="{esc(a[1])}" rel="noopener">{t}</a>'
        partes.append(t)
    return "".join(partes)


# ---------- Fotos ----------

def sips(*args):
    subprocess.run(["sips", *args], check=True, capture_output=True)


HAY_SIPS = shutil.which("sips") is not None


def _pil():
    """Pillow (y pillow-heif para las HEIC del iPhone) si está instalado; si no, None y se usa sips."""
    try:
        from PIL import Image, ImageOps, ImageChops
    except ImportError:
        return None
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    return Image, ImageOps, ImageChops


def sin_borde(im, ImageChops):
    """Quita franjas blancas parejas (arriba y abajo, o a los lados) si la foto sigue siendo horizontal.
    Las fotos verticales con franjas a los lados se dejan como están."""
    w, h = im.size
    blanco = im.copy()
    blanco.paste((255, 255, 255), (0, 0, w, h))
    caja = ImageChops.difference(im, blanco).convert("L").point(lambda p: 255 if p > 18 else 0).getbbox()
    if not caja:
        return im
    l, t, r, b = caja
    arriba, abajo, izq, der = t, h - b, l, w - r
    minimo = max(6, 0.012 * max(w, h))
    franjas_h = arriba >= minimo and abajo >= minimo and abs(arriba - abajo) <= 0.02 * h and max(izq, der) <= 4
    franjas_v = izq >= minimo and der >= minimo and abs(izq - der) <= 0.02 * w and max(arriba, abajo) <= 4
    if not (franjas_h or franjas_v) or (r - l) < (b - t):
        return im
    return im.crop(caja)


def reducir(orig, destino, lado_max, calidad):
    """JPEG con el lado mayor en lado_max px (sin agrandar), sin franjas blancas."""
    pil = _pil()
    if pil is None:
        sips("-s", "format", "jpeg", "-s", "formatOptions", str(calidad), "-Z", str(lado_max), str(orig), "--out", str(destino))
        return
    Image, ImageOps, ImageChops = pil
    with Image.open(orig) as im:
        im = sin_borde(ImageOps.exif_transpose(im).convert("RGB"), ImageChops)
        im.thumbnail((lado_max, lado_max), Image.LANCZOS)
        im.save(destino, "JPEG", quality=calidad, optimize=True, progressive=True)


def imagen_og(base, og):
    """Imagen 1200×630 para la vista previa de WhatsApp, recortada al centro."""
    if _pil() is None:
        sips("-s", "format", "jpeg", "-s", "formatOptions", "70", "--resampleWidth", "1200", str(base), "--out", str(og))
        alto = int(re.search(r"pixelHeight: (\d+)", subprocess.run(
            ["sips", "-g", "pixelHeight", str(og)], capture_output=True, text=True).stdout).group(1))
        if alto < 630:
            sips("--resampleHeight", "630", str(og))
        sips("-c", "630", "1200", str(og))
        return
    Image, ImageOps, _ = _pil()
    with Image.open(base) as im:
        ImageOps.fit(im.convert("RGB"), (1200, 630), Image.LANCZOS).save(og, "JPEG", quality=70, optimize=True)


def descargar(url, destino, intentos=4):
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"user-agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r, open(destino, "wb") as f:
                shutil.copyfileobj(r, f)
            return
        except Exception:
            if i == intentos - 1:
                raise
            time.sleep(3 * (i + 1))


def preparar_fotos(codigo, urls):
    """Descarga y comprime las fotos (solo las nuevas). Devuelve la lista de claves en orden."""
    carpeta = SITIO / "fotos" / codigo
    carpeta.mkdir(parents=True, exist_ok=True)
    claves = []
    for url in urls:
        # La clave sale de la fuente (attachment:…), no de la URL firmada, para que no cambie.
        if isinstance(url, tuple):
            fuente, url = url
        else:
            fuente = urllib.parse.unquote(url.split("/image/", 1)[1].split("?", 1)[0])
        clave = hashlib.sha1(fuente.encode()).hexdigest()[:10]
        claves.append(clave)
        grande, chica = carpeta / f"{clave}.jpg", carpeta / f"{clave}-800.jpg"
        if grande.exists() and chica.exists():
            continue
        with tempfile.TemporaryDirectory() as tmp:
            orig = Path(tmp) / "orig"
            descargar(url, orig)
            reducir(orig, grande, 1600, 72)
            reducir(orig, chica, 800, 70)
    # Versión grande de la primera foto para la portada de la web (pantallas grandes y de alta densidad).
    if claves:
        hd = carpeta / f"{claves[0]}-2400.jpg"
        if not hd.exists():
            with tempfile.TemporaryDirectory() as tmp:
                orig = Path(tmp) / "orig"
                descargar(urls[0][1] if isinstance(urls[0], tuple) else urls[0], orig)
                reducir(orig, hd, 2400, 82)
    # Imagen para WhatsApp (1200×630) a partir de la primera foto.
    if claves:
        og = carpeta / f"og-{claves[0]}.jpg"
        if not og.exists():
            for viejo in carpeta.glob("og-*.jpg"):
                viejo.unlink()
            base = carpeta / f"{claves[0]}.jpg"
            imagen_og(base, og)
    # Borrar fotos que ya no están en la ficha.
    vigentes = {f"{c}.jpg" for c in claves} | {f"{c}-800.jpg" for c in claves} | (
        {f"og-{claves[0]}.jpg", f"{claves[0]}-2400.jpg"} if claves else set())
    for f in carpeta.iterdir():
        if f.name not in vigentes:
            f.unlink()
    return claves


# ---------- Páginas ----------

FUENTES = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
           '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
           '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Gilda+Display'
           '&family=IBM+Plex+Mono:wght@500&family=Red+Hat+Display:wght@400;500;700&display=swap">')


def wa_link(mensaje):
    numero_wa = re.sub(r"\D", "", CFG.get("whatsapp", ""))
    q = urllib.parse.quote(mensaje)
    return f"https://wa.me/{numero_wa}?text={q}" if numero_wa else f"https://wa.me/?text={q}"


def cabeza(titulo, descripcion, url, imagen=None):
    og_img = ""
    if imagen:
        og_img = (f'<meta property="og:image" content="{esc(imagen)}">'
                  f'<meta property="og:image:secure_url" content="{esc(imagen)}">'
                  '<meta property="og:image:type" content="image/jpeg">'
                  '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">'
                  f'<meta name="twitter:image" content="{esc(imagen)}">')
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{esc(titulo)}</title>
<meta name="description" content="{esc(descripcion)}">
<link rel="canonical" href="{esc(url)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="dûo real estate">
<meta property="og:locale" content="es_CO">
<meta property="og:title" content="{esc(titulo)}">
<meta property="og:description" content="{esc(descripcion)}">
<meta property="og:url" content="{esc(url)}">
{og_img}
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#435E86">
<link rel="icon" type="image/png" href="/marca/favicon.png">
<link rel="apple-touch-icon" href="/marca/apple-touch-icon.png">
{FUENTES}
<link rel="stylesheet" href="/estilos.css?v={VERSION_CSS}">
</head>"""


# Secciones del menú por tipo de propiedad (solo se muestran las que tienen inventario).
SECCIONES = [("Apartamento", "apartamentos", "Apartamentos"), ("Casa", "casas", "Casas"),
             ("Lote", "lotes", "Lotes"), ("Oficina", "oficinas", "Oficinas")]
TIPOS_CON_INVENTARIO = set()


def encabezado(wa, activo="", sobre_foto=False):
    enlaces = "".join(
        f'<a href="/{slug}/"{" aria-current=page" if slug == activo else ""}>{nombre}</a>'
        for tipo, slug, nombre in SECCIONES if tipo in TIPOS_CON_INVENTARIO)
    return f"""<header class="top{' sobre' if sobre_foto else ''}">
  <a href="/" class="logo"><img src="/marca/logo-crema-transparente.png" alt="dûo real estate" width="680" height="475"></a>
  <nav class="menu" aria-label="Menú">
    <a href="/#propiedades"{" aria-current=page" if activo == "inicio" else ""}>Propiedades</a>{enlaces}<a href="/#nosotras">Nosotras</a>
  </nav>
  <a class="top-wa" href="{esc(wa)}" rel="noopener">WHATSAPP</a>
</header>""" + ("""
<script>(function(){var t=document.currentScript.previousElementSibling;function f(){t.classList.toggle('solido',scrollY>40)}
addEventListener('scroll',f,{passive:true});f()})()</script>""" if sobre_foto else "")


def pie(wa):
    ig = CFG.get("instagram", "")
    return f"""<footer class="pie">
  <img src="/marca/isotipo-crema.png" alt="" width="56" height="56">
  <p class="tag">Dos generaciones, un criterio.</p>
  <p class="dato">EL POBLADO · ALTO DE LAS PALMAS · LLANOGRANDE</p>
  <p><a href="{esc(wa)}" rel="noopener">WhatsApp</a> · <a href="https://instagram.com/{esc(ig)}" rel="noopener">@{esc(ig)}</a></p>
</footer>"""


def contacto(wa, titulo_bloque="¿Quieres conocerla?"):
    ig = CFG.get("instagram", "")
    ig_html = (f'<a class="ig" href="https://instagram.com/{esc(ig)}" rel="noopener">@{esc(ig)}</a>' if ig else "")
    return f"""<section class="contacto" id="contacto">
  <img src="/marca/isotipo-crema.png" alt="" width="80" height="80">
  <h2>{esc(titulo_bloque)}</h2>
  <p class="rol">DÛO REAL ESTATE · MEDELLÍN</p>
  <a class="btn" href="{esc(wa)}" rel="noopener">Escríbenos por WhatsApp</a>
  {ig_html}
  <p class="tag">Dos generaciones, un criterio.</p>
</section>"""


def singular(n, uno, varios):
    return uno if n == 1 else varios


def ficha(p, cuerpo, claves):
    codigo = p["Código"].strip().upper()
    partes = [x.strip() for x in p.get("Título", "").split("|")]
    tipo = p.get("Tipo propiedad") or (partes[0] if len(partes) > 1 else "")
    sector = p.get("Sector") or (partes[-1] if len(partes) > 2 else "")
    gancho = partes[1] if len(partes) >= 3 else partes[0]
    ops = [o.strip() for o in (p.get("Operación") or "").split(",") if o.strip()]
    venta, canon = numero(p.get("Precio venta COP") or ""), numero(p.get("Canon mensual COP") or "")
    if not ops:
        ops = (["Venta"] if venta else []) + (["Alquiler"] if canon else [])

    precios = []
    if "Venta" in ops and venta:
        precios.append(("VENTA", fmt_precio_venta(venta)))
    if "Alquiler" in ops and canon:
        precios.append(("ARRIENDO", f"{fmt_pesos(canon)} / mes"))
    etiquetas = []
    if "Venta" in ops:
        etiquetas.append('<span class="etq venta">EN VENTA</span>')
    if "Alquiler" in ops:
        etiquetas.append('<span class="etq arriendo">EN ARRIENDO</span>')

    # Tarjetas de datos
    area, ext = numero(p.get("Área m²") or ""), numero(p.get("Área exterior m²") or "")
    alc, ban, parq = (numero(p.get(k) or "") for k in ("Alcobas", "Baños", "Parqueaderos"))
    es_lote = (tipo or "").lower() == "lote"
    tarjetas = []
    if area:
        tarjetas.append((fmt_num(area), "M² DE LOTE" if es_lote else "M² CONSTRUIDOS"))
    lote = numero(p.get("Lote m²") or "")
    if lote and not es_lote:
        tarjetas.append((fmt_num(lote), "M² DE LOTE"))
    if ext:
        tarjetas.append((fmt_num(ext), "M² EXTERIORES"))
    if alc:
        tarjetas.append((fmt_num(alc), singular(alc, "ALCOBA", "ALCOBAS")))
    if ban:
        tarjetas.append((fmt_num(ban), singular(ban, "BAÑO", "BAÑOS")))
    if parq:
        tarjetas.append((fmt_num(parq), singular(parq, "PARQUEADERO", "PARQUEADEROS")))

    # Textos del cuerpo: el primero trae las viñetas; los siguientes, la descripción.
    textos = [rich for k, rich in cuerpo if k == "texto"]
    vinetas, descripcion_html, lead = [], [], ""
    if textos:
        for linea in texto_plano(textos[0]).split("\n"):
            l = linea.strip().lstrip("•·-").strip()
            if not l or "📍" in l or re.match(r"^\d", l) or l.lower().startswith(("venta", "arriendo", "alquiler")):
                continue
            vinetas.append(l)
        for i, rich in enumerate(textos[1:]):
            if i == 0 and rich and len(rich[0]) > 1 and any(a[0] == "b" for a in rich[0][1]):
                lead = rich[0][0].strip()
                resto = rich_html(rich[1:]).strip()
                if resto:
                    descripcion_html.append(f"<p>{resto}</p>")
            else:
                descripcion_html.append(f"<p>{rich_html(rich)}</p>")

    problemas = revisar_privacidad(p.get("Título", ""), *(texto_plano(t) for t in textos))
    if problemas:
        return None, problemas, None, None

    url = f"{CFG['url_sitio']}/{codigo}"
    og_img = f"{CFG['url_sitio']}/fotos/{codigo}/og-{claves[0]}.jpg" if claves else None
    titulo = f"{gancho} · {sector}" if sector else gancho
    datos_cortos = " · ".join(x for x in [
        f"{fmt_num(area)} m²" + (f" + {fmt_num(ext)} m² exteriores" if ext else "") if area else "",
        f"{fmt_num(alc)} {singular(alc, 'alcoba', 'alcobas')}" if alc else "",
        f"{fmt_num(ban)} {singular(ban, 'baño', 'baños')}" if ban else "",
    ] if x)
    precio_txt = " · ".join(f"{n.capitalize()} {v}" for n, v in precios)
    descripcion = " · ".join(x for x in [precio_txt, datos_cortos] if x) + " | dûo real estate"

    wa = wa_link(f"Hola, me interesa la propiedad {codigo} ({gancho}, {sector}). {url}")

    fotos = [f"/fotos/{codigo}/{c}" for c in claves]
    hero = (f'<img src="{fotos[0]}.jpg" srcset="{fotos[0]}-800.jpg 800w, {fotos[0]}.jpg 1600w" '
            f'sizes="(max-width: 760px) 100vw, 760px" alt="{esc(gancho)}" fetchpriority="high">') if fotos else ""
    galeria = "".join(
        f'<button class="g" data-i="{i}" aria-label="Ver foto {i + 1} de {len(fotos)}">'
        f'<img src="{f}-800.jpg" alt="Foto {i + 1}" loading="lazy" decoding="async"></button>'
        for i, f in enumerate(fotos))
    visor = "".join(f'<figure><img data-src="{f}.jpg" alt="Foto {i + 1} de {len(fotos)}"></figure>'
                    for i, f in enumerate(fotos))

    detalles = [("Código", codigo), ("Tipo", tipo), ("Sector", sector)]
    if p.get("Estrato"):
        detalles.append(("Estrato", fmt_num(numero(p["Estrato"]))))
    if p.get("Hab servicio"):
        detalles.append(("Alcoba de servicio", p["Hab servicio"]))
    if numero(p.get("Administración COP") or ""):
        detalles.append(("Administración", fmt_pesos(numero(p["Administración COP"]))))
    if numero(p.get("Predial COP") or ""):
        per = p.get("Periodicidad predial", "")
        detalles.append(("Predial", fmt_pesos(numero(p["Predial COP"])) + (f" ({per.lower()})" if per else "")))

    eyebrow = " · ".join(x.upper() for x in [tipo, sector] if x)
    slides = "".join(
        f'<figure><img src="{f}.jpg" srcset="{f}-800.jpg 800w, {f}.jpg 1600w" sizes="(max-width: 1240px) 100vw, 1240px" '
        f'alt="{esc(gancho)} · foto {i + 1}"{" fetchpriority=high" if i == 0 else " loading=lazy"} data-i="{i}"></figure>'
        for i, f in enumerate(fotos))
    flechas = ('<button class="car-ant" aria-label="Foto anterior">&#8249;</button>'
               '<button class="car-sig" aria-label="Foto siguiente">&#8250;</button>') if len(fotos) > 1 else ""
    html_out = cabeza(titulo, descripcion, url, og_img) + f"""
<body class="pg-ficha">
{encabezado(wa, slug_tipo(tipo))}
<section class="carrusel" aria-label="Fotos de la propiedad">
  <div class="car-tira">{slides}</div>
  <div class="etqs">{''.join(etiquetas)}</div>
  {flechas}
  <button class="car-pos" data-i="0" aria-label="Ver fotos en pantalla completa"><span class="car-n">1</span> / {len(fotos)} · PANTALLA COMPLETA</button>
</section>
<main class="ficha">
  <div class="ficha-cab">
    <p class="eyebrow">{esc(eyebrow)} · {esc(codigo)}</p>
    <h1>{esc(gancho)}</h1>
  </div>
  <div class="ficha-txt">
    {f'<p class="lead">{esc(lead)}</p>' if lead else ''}
    {''.join(descripcion_html)}
    {('<h2>Lo que tiene</h2><ul class="lista">' + ''.join(f'<li>{esc(v)}</li>' for v in vinetas) + '</ul>') if vinetas else ''}
    <h2>Detalles</h2>
    <dl class="detalles">{''.join(f'<dt>{esc(k)}</dt><dd>{esc(v)}</dd>' for k, v in detalles if v)}</dl>
    <p class="nota">Los valores pueden cambiar sin previo aviso. Confírmalos con nosotras antes de visitar.</p>
  </div>
  <aside class="ficha-lat">
    <div class="resumen">
      <div class="precios">{''.join(f'<div class="precio"><small>{n}</small>{esc(v)}</div>' for n, v in precios)}</div>
      {'<div class="tarjetas">' + ''.join(f'<div><b>{esc(v)}</b><span>{esc(l)}</span></div>' for v, l in tarjetas) + '</div>' if tarjetas else ''}
      <a class="btn btn-azul" href="{esc(wa)}" rel="noopener">Agenda tu visita por WhatsApp</a>
      <p class="resumen-nota">Coordinamos la visita contigo, sin compromiso.</p>
    </div>
  </aside>
</main>
{contacto(wa)}
{pie(wa)}
<a class="flota" href="{esc(wa)}" rel="noopener" aria-label="Escríbenos por WhatsApp">WhatsApp</a>
<div class="visor" hidden role="dialog" aria-label="Fotos">
  <div class="tira">{visor}</div>
  <button class="cerrar" aria-label="Cerrar">✕</button>
  <span class="pos"></span>
</div>
<script src="/visor.js?v={VERSION_CSS}" defer></script>
</body>
</html>
"""
    colega = neutra(html_out, codigo, wa, slug_tipo(tipo), og_img, descripcion)
    tarjeta = {"codigo": codigo, "tipo": tipo, "sector": sector, "titulo": gancho, "ops": ops,
               "venta": venta or 0, "canon": canon or 0, "area": area or 0, "ext": ext or 0,
               "alc": alc or 0, "ban": ban or 0, "parq": parq or 0,
               "foto": f"{fotos[0]}-800.jpg" if fotos else "", "precios": precios,
               # Para desplegar en Enviar: lo mismo que ya muestra la ficha pública, nada privado.
               "det": {"lista": vinetas, "carac": p.get("Características") or [], "amen": p.get("Amenidades") or [],
                       "detalles": [[k, v] for k, v in detalles if v and k not in ("Código", "Tipo", "Sector")]}}
    return html_out, [], tarjeta, colega


def neutra(html_out, codigo, wa, activo, og_img, descripcion):
    """Ficha para colegas: la misma página sin logo, menú, WhatsApp, contacto ni nada que diga dûo."""
    url_d, url_f = f"{CFG['url_sitio']}/{codigo}", f"{CFG['url_fichas']}/{codigo}"
    h = html_out
    for bloque in (encabezado(wa, activo) + "\n", contacto(wa) + "\n", pie(wa) + "\n",
                   f'<a class="flota" href="{esc(wa)}" rel="noopener" aria-label="Escríbenos por WhatsApp">WhatsApp</a>\n',
                   f'      <a class="btn btn-azul" href="{esc(wa)}" rel="noopener">Agenda tu visita por WhatsApp</a>\n',
                   '      <p class="resumen-nota">Coordinamos la visita contigo, sin compromiso.</p>\n',
                   '<meta property="og:site_name" content="dûo real estate">\n',
                   '<link rel="icon" type="image/png" href="/marca/favicon.png">\n',
                   '<link rel="apple-touch-icon" href="/marca/apple-touch-icon.png">\n'):
        assert bloque in h, bloque[:40]
        h = h.replace(bloque, "")
    h = h.replace(" Confírmalos con nosotras antes de visitar.", "")
    h = h.replace(esc(descripcion), esc(descripcion.replace(" | dûo real estate", "")))
    h = h.replace(f'"{esc(url_d)}"', f'"{esc(url_f)}"')
    if og_img:
        h = h.replace(esc(og_img), esc(og_img.replace(CFG["url_sitio"], CFG["url_fichas"])))
    h = h.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n<meta name="robots" content="noindex">', 1)
    rastro = re.findall(r"\bd[uûú]o\b|duorealestate|" + re.escape(re.sub(r"\D", "", CFG.get("whatsapp", ""))[-7:] or "x"), h, re.I)
    if rastro:
        raise ValueError(f"la ficha neutra conserva rastro de dûo: {rastro}")
    return h


def publicar_fichas(publicadas, neutras):
    """Escribe el sitio neutro: una página por propiedad con sus fotos, estilos y visor."""
    FICHAS.mkdir(exist_ok=True)
    for nombre in ("estilos.css", "visor.js"):  # sin comentarios: pueden mencionar a dûo
        codigo_fuente = re.sub(r"/\*.*?\*/", "", (SITIO / nombre).read_text(), flags=re.S)
        if re.search(r"\bd[uûú]o\b|duorealestate", codigo_fuente, re.I):
            raise ValueError(f"{nombre} menciona a dûo fuera de un comentario")
        (FICHAS / nombre).write_text(codigo_fuente)
    (FICHAS / ".nojekyll").write_text("")
    vacia = ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="robots" content="noindex">'
             '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Fichas</title></head>'
             '<body style="font-family:sans-serif;padding:40px;color:#565F78">Esta ficha no está disponible.</body></html>')
    (FICHAS / "index.html").write_text(vacia)
    (FICHAS / "404.html").write_text(vacia)
    for codigo, html_c in neutras.items():
        (FICHAS / codigo).mkdir(exist_ok=True)
        (FICHAS / codigo / "index.html").write_text(html_c)
        origen, destino = SITIO / "fotos" / codigo, FICHAS / "fotos" / codigo
        if origen.exists():
            shutil.copytree(origen, destino, dirs_exist_ok=True)
            for f in destino.iterdir():
                if not (origen / f.name).exists():
                    f.unlink()
    for d in list(FICHAS.iterdir()) + (list((FICHAS / "fotos").iterdir()) if (FICHAS / "fotos").exists() else []):
        if d.is_dir() and re.fullmatch(r"D\d{3}", d.name) and d.name not in publicadas:
            shutil.rmtree(d)
    print(f"Fichas para colegas: {len(neutras)}")


def slug_tipo(tipo):
    return next((slug for t, slug, _ in SECCIONES if t == tipo), "")


def tarjeta_html(t):
    datos = " · ".join(x for x in [
        f"{fmt_num(t['area'])} m²" if t["area"] else "",
        f"{fmt_num(t['alc'])} {singular(t['alc'], 'alcoba', 'alcobas')}" if t["alc"] else "",
        f"{fmt_num(t['ban'])} {singular(t['ban'], 'baño', 'baños')}" if t["ban"] else "",
    ] if x)
    etq = "".join(f'<span class="etq-s {"venta" if o == "Venta" else "arriendo"}">{"EN VENTA" if o == "Venta" else "EN ARRIENDO"}</span>'
                  for o in t["ops"])
    precio = " · ".join(v for _, v in t["precios"])
    attrs = (f'data-tipo="{esc(t["tipo"])}" data-sector="{esc(t["sector"])}" data-ops="{esc(",".join(t["ops"]))}" '
             f'data-venta="{int(t["venta"])}" data-canon="{int(t["canon"])}" data-alc="{int(t["alc"])}" '
             f'data-area="{int(t["area"])}" data-cod="{esc(t["codigo"])}"')
    return f"""<a class="card" href="/{esc(t['codigo'])}" {attrs}>
  <div class="card-foto"><img src="{esc(t['foto'])}" srcset="{esc(t['foto'])} 800w, {esc(t['foto'].replace('-800.jpg', '.jpg'))} 1600w" sizes="(min-width:760px) 33vw, 50vw" alt="{esc(t['titulo'])}" loading="lazy" decoding="async"><div class="card-etqs">{etq}</div></div>
  <div class="card-in">
    <p class="card-eye">{esc((t['tipo'] + ' · ' + t['sector']).upper())}</p>
    <h3>{esc(t['titulo'])}</h3>
    <p class="card-precio">{esc(precio)}</p>
    <p class="card-datos">{esc(datos)}</p>
  </div>
</a>"""


# Pasos de la barra de precio (millones). El último significa "sin límite".
PASOS_PRECIO = [0, 300, 500, 700, 1000, 1300, 1600, 2000, 2500, 3000, 4000, 5000, 7000, 10000]


def filtros(tarjetas, tipo_fijo=""):
    sectores = sorted({t["sector"] for t in tarjetas if t["sector"]})
    tipos = [(t, n) for t, _, n in SECCIONES if any(x["tipo"] == t for x in tarjetas)]
    op_tipo = "" if tipo_fijo else ('<label><span>Tipo</span><select data-f="tipo"><option value="">Todos</option>'
                                     + "".join(f'<option value="{esc(t)}">{esc(n)}</option>' for t, n in tipos) + "</select></label>")
    precios = [(500, "$500 millones"), (1000, "$1.000 millones"), (1500, "$1.500 millones"), (2000, "$2.000 millones"),
               (3000, "$3.000 millones"), (5000, "$5.000 millones")]
    return f"""<form class="filtros" onsubmit="return false" aria-label="Filtrar propiedades">
  {op_tipo}
  <label><span>Sector</span><select data-f="sector"><option value="">Todos</option>{"".join(f'<option>{esc(x)}</option>' for x in sectores)}</select></label>
  <label><span>Operación</span><select data-f="ops"><option value="">Venta y arriendo</option><option value="Venta">Venta</option><option value="Alquiler">Arriendo</option></select></label>
  <div class="rango-precio"><span>Precio de venta</span>
    <div class="rp-pista"><div class="rp-sel"></div>
      <input type="range" data-f="pmin" min="0" max="{len(PASOS_PRECIO) - 1}" value="0" step="1" aria-label="Precio mínimo">
      <input type="range" data-f="pmax" min="0" max="{len(PASOS_PRECIO) - 1}" value="{len(PASOS_PRECIO) - 1}" step="1" aria-label="Precio máximo">
    </div>
    <output class="rp-txt" data-pasos="{",".join(str(p) for p in PASOS_PRECIO)}">Cualquier precio</output>
  </div>
  <label><span>Alcobas</span><select data-f="alc"><option value="">Cualquiera</option><option value="1">1 o más</option><option value="2">2 o más</option><option value="3">3 o más</option><option value="4">4 o más</option></select></label>
  <label><span>Ordenar</span><select data-f="orden"><option value="nuevas">Más recientes</option><option value="precio-asc">Menor precio</option><option value="precio-desc">Mayor precio</option><option value="area-desc">Más área</option></select></label>
</form>
<p class="conteo" aria-live="polite" hidden><b>{len(tarjetas)}</b> propiedades</p>"""


def portafolio(tarjetas, tipo_fijo=""):
    orden = sorted(tarjetas, key=lambda t: t["codigo"], reverse=True)
    return f"""{filtros(tarjetas, tipo_fijo)}
<div class="grid">{"".join(tarjeta_html(t) for t in orden)}</div>
<p class="vacio" hidden>No hay propiedades con esos filtros. <a href="{esc(wa_link('Hola, busco una propiedad y no encontré lo que necesito en la web. ¿Me ayudan?'))}">Cuéntanos qué buscas</a> y te ayudamos.</p>"""


def inicio(tarjetas):
    wa = wa_link("Hola, vi la página de Dûo Real Estate y quiero más información.")
    url = CFG["url_sitio"] + "/"
    n = len(tarjetas)
    # Portada: la primera foto de las propiedades de mayor valor (casas y apartamentos en venta).
    # Las propiedades de "portada" en config.json (las que siguen en el catálogo); si no hay, las de mayor valor.
    por_codigo = {t["codigo"]: t for t in tarjetas}
    destacadas = [por_codigo[c] for c in CFG.get("portada", []) if c in por_codigo][:6]
    if not destacadas:
        destacadas = sorted((t for t in tarjetas if t["tipo"] in ("Casa", "Apartamento") and t["venta"]),
                            key=lambda t: t["venta"], reverse=True)[:6]
    fondos = "".join(f'<img src="{esc(t["foto"].replace("-800.jpg", ".jpg"))}" srcset="{esc(t["foto"].replace("-800.jpg", ".jpg"))} 1600w, '
                     f'{esc(t["foto"].replace("-800.jpg", "-2400.jpg"))} 2400w" sizes="max(100vw, 134vh)" alt="" {"fetchpriority=high" if i == 0 else "loading=lazy"} '
                     f'style="animation-delay:{i * 6 - 1.5}s">' for i, t in enumerate(destacadas))
    opciones_tipo = "".join(f'<option value="{esc(tp)}">{esc(nom)}</option>' for tp, _, nom in SECCIONES
                            if any(x["tipo"] == tp for x in tarjetas))
    opciones_sector = "".join(f'<option>{esc(s)}</option>' for s in sorted({x["sector"] for x in tarjetas if x["sector"]}))
    return cabeza("dûo real estate · Propiedades en Medellín y el Oriente",
                  f"Inmobiliaria madre e hija. Propiedades en El Poblado, Alto de las Palmas, Llanogrande y alrededores. Dos generaciones, un criterio.",
                  url, CFG["url_sitio"] + "/marca/og-duo.jpg") + f"""
<body class="pg-inicio">
{encabezado(wa, "inicio", sobre_foto=True)}
<section class="hero-inicio">
  <div class="hero-fondos" style="--n:{max(len(destacadas), 1)}">{fondos}</div>
  <div class="hero-velo"></div>
  <div class="hero-txt">
    <h1>Encuentra el hogar que encaja con tu momento de vida</h1>
    <p class="bajada">Te acompañamos a encontrar el lugar donde quieres vivir.</p>
    <form class="buscador" action="/#propiedades" method="get" aria-label="Buscar propiedades">
      <label><span>Tipo</span><select name="tipo"><option value="">Todos</option>{opciones_tipo}</select></label>
      <label><span>Sector</span><select name="sector"><option value="">Todos</option>{opciones_sector}</select></label>
      <button class="btn" type="submit">Ver propiedades</button>
    </form>
    <a class="hero-link" href="{esc(wa)}" rel="noopener">o escríbenos por WhatsApp</a>
  </div>
  <a class="hero-baja" href="#confianza" aria-label="Seguir bajando">&#8964;</a>
</section>
<section class="confianza" id="confianza">
  <div><b>Experiencia</b><span>MÁS DE 25 AÑOS<br>EN FINCA RAÍZ</span></div>
  <div><b>Asesoría</b><span>PENSADA PARA TU<br>MOMENTO DE VIDA</span></div>
  <div><b>Acompañamiento</b><span>CONTIGO HASTA EL MOMENTO<br>EN QUE ENCUENTRAS TU LUGAR</span></div>
</section>
<section class="frase">
  <p class="eyebrow">NUESTRA FORMA DE TRABAJAR</p>
  <blockquote>“Comprar o vender tu casa es una decisión grande. Por eso la tomamos contigo: con más de 25 años de experiencia y la tranquilidad de saber que siempre buscamos lo mejor para ti.”</blockquote>
</section>
<main class="listado" id="propiedades">
  <p class="eyebrow">PORTAFOLIO</p>
  <h2>Nuestras propiedades</h2>
  {portafolio(tarjetas)}
</main>
<section class="proceso" id="como-te-acompanamos">
  <p class="eyebrow">CÓMO TE ACOMPAÑAMOS</p>
  <h2>Primero te entendemos, después te mostramos</h2>
  <ol class="pasos">
    <li><span class="paso-n">01</span><h3>Te escuchamos</h3><p>Entendemos tu momento de vida: si la familia crece, si los hijos se van, si buscas más espacio o una mejor ubicación.</p></li>
    <li><span class="paso-n">02</span><h3>Te asesoramos</h3><p>Te mostramos solo lo que tiene sentido para ti, con datos claros de precio y de la zona.</p></li>
    <li><span class="paso-n">03</span><h3>Te acompañamos</h3><p>En cada visita, en la negociación, la promesa, la notaría y la entrega.</p></li>
  </ol>
</section>
<section class="nosotras" id="nosotras">
  <div class="nosotras-in">
    <img src="/marca/duo-isotipo-azul-sobre-crema.png" alt="" width="120" height="120">
    <div>
      <p class="eyebrow">QUIÉNES SOMOS · LUZ STELLA ORTIZ Y CAMILA CALLE</p>
      <h2>Dos generaciones, un criterio.</h2>
      <p>En dûo se juntan dos miradas. La de Luz Stella, con 25 años de experiencia, relaciones de confianza y clientes que vuelven. Y la de Camila, que llegó para hacer equipo y traer nuevas ideas. Lo que nos une es lo mismo: que tomes una buena decisión y te sientas acompañado en cada paso.</p>
      <a class="btn btn-azul" href="{esc(wa)}" rel="noopener">Hablemos por WhatsApp</a>
    </div>
  </div>
</section>
{pie(wa)}
<a class="flota" href="{esc(wa)}" rel="noopener" aria-label="Escríbenos por WhatsApp">WhatsApp</a>
<script src="/catalogo.js?v={VERSION_CSS}" defer></script>
</body>
</html>
"""


def seccion(tipo, slug, nombre, tarjetas):
    wa = wa_link(f"Hola, vi los {nombre.lower()} de Dûo Real Estate y quiero más información.")
    url = f"{CFG['url_sitio']}/{slug}/"
    propias = [t for t in tarjetas if t["tipo"] == tipo]
    portada = next((t["foto"] for t in sorted(propias, key=lambda t: t["codigo"], reverse=True)), "")
    og = f"{CFG['url_sitio']}/fotos/{portada.split('/')[2]}/" if portada else ""
    og_img = ""
    if portada:
        cod = portada.split("/")[2]
        ogs = sorted((SITIO / "fotos" / cod).glob("og-*.jpg"))
        og_img = f"{CFG['url_sitio']}/fotos/{cod}/{ogs[0].name}" if ogs else ""
    return cabeza(f"{nombre} · dûo real estate", f"{nombre} en venta y arriendo en El Poblado, Alto de las Palmas, Llanogrande y alrededores. Dos generaciones, un criterio.",
                  url, og_img or None) + f"""
<body>
{encabezado(wa, slug)}
<main class="listado">
  <p class="eyebrow">PORTAFOLIO DÛO</p>
  <h1>{esc(nombre)}</h1>
  {portafolio(propias, tipo)}
</main>
{pie(wa)}
<a class="flota" href="{esc(wa)}" rel="noopener" aria-label="Escríbenos por WhatsApp">WhatsApp</a>
<script src="/catalogo.js?v={VERSION_CSS}" defer></script>
</body>
</html>
"""


def no_encontrada():
    wa = wa_link("Hola, abrí un link de Dûo Real Estate que ya no funciona. ¿Me ayudan?")
    return cabeza("dûo real estate", "Esta propiedad ya no está disponible.", CFG["url_sitio"] + "/") + f"""
<body>
{encabezado(wa)}
<main class="ficha"><div class="in vacia">
  <p class="eyebrow">PÁGINA NO DISPONIBLE</p>
  <h1>Esta propiedad ya no está disponible</h1>
  <p>Puede que se haya vendido o que el link haya cambiado. Mira <a href="/#propiedades">todas nuestras propiedades</a> o escríbenos y te mostramos opciones parecidas.</p>
</div>
{contacto(wa, "Te ayudamos a encontrar otra")}
</main>
{pie(wa)}
</body>
</html>
"""


VERSION_CSS = "1"


# ---------- Principal ----------

def main():
    global VERSION_CSS
    publicar = "--publicar" in sys.argv
    solo = set()
    if "--solo" in sys.argv:
        solo = {c.upper() for c in sys.argv[sys.argv.index("--solo") + 1].split(",")}

    estilos = (RAIZ / "plantilla" / "estilos.css").read_text()
    visor_js = (RAIZ / "plantilla" / "visor.js").read_text()
    catalogo_js = (RAIZ / "plantilla" / "catalogo.js").read_text()
    VERSION_CSS = hashlib.sha1((estilos + visor_js + catalogo_js).encode()).hexdigest()[:8]

    SITIO.mkdir(exist_ok=True)
    (SITIO / "estilos.css").write_text(estilos)
    (SITIO / "visor.js").write_text(visor_js)
    (SITIO / "catalogo.js").write_text(catalogo_js)
    (SITIO / ".nojekyll").write_text("")
    if CFG.get("dominio"):  # dominio propio de GitHub Pages (duorealestate.com.co)
        (SITIO / "CNAME").write_text(CFG["dominio"] + "\n")
    shutil.copytree(MARCA, SITIO / "marca", dirs_exist_ok=True)

    previas = SITIO / "propiedades.json"
    anteriores = json.loads(previas.read_text()) if previas.exists() else {}
    catalogo = leer_interno() if os.environ.get("DUO_FUENTE", CFG.get("fuente")) == "interno" else leer_catalogo()
    print(f"Catálogo: {len(catalogo)} fichas")
    if anteriores and len(catalogo) < len(anteriores) * 0.6:
        sys.exit(f"ALTO: el catálogo trae {len(catalogo)} fichas y el sitio tiene {len(anteriores)}. "
                 "Puede ser una falla de Notion; no se borra nada. Si de verdad salieron tantas, borra sitio/propiedades.json y vuelve a correr.")
    publicadas, omitidas, neutras = {}, [], {}
    TIPOS_CON_INVENTARIO.update(p.get("Tipo propiedad") for p in catalogo if p.get("Tipo propiedad"))
    for p in sorted(catalogo, key=lambda x: x.get("Código", "")):
        codigo = (p.get("Código") or "").strip().upper()
        if not re.fullmatch(r"D\d{3}", codigo):
            omitidas.append((p.get("Título", p["_id"]), "sin código DÚO válido"))
            continue
        if solo and codigo not in solo:
            continue
        try:
            if "_cuerpo" in p and not fotos_al_dia(codigo, p["_cuerpo"]):
                refrescar_fotos(p)
            cuerpo = p["_cuerpo"] if "_cuerpo" in p else leer_cuerpo(p["_id"])
            urls = [u for k, u in cuerpo if k == "foto"]
            if not urls:
                omitidas.append((codigo, "sin fotos en la ficha"))
                continue
            claves = preparar_fotos(codigo, urls)
            pagina, problemas, tarjeta, colega = ficha(p, cuerpo, claves)
        except Exception as e:  # Notion falló con esta ficha: se deja la versión anterior y se reintenta en la próxima corrida
            if (SITIO / codigo / "index.html").exists() and codigo in anteriores:
                publicadas[codigo] = anteriores[codigo]
                omitidas.append((codigo, f"error leyendo Notion ({e}); se deja la versión anterior"))
            else:
                omitidas.append((codigo, f"error leyendo Notion ({e}); se reintenta en la próxima corrida"))
            continue
        if problemas:
            omitidas.append((codigo, "posible dato privado: " + "; ".join(problemas)))
            continue
        carpeta = SITIO / codigo
        carpeta.mkdir(exist_ok=True)
        (carpeta / "index.html").write_text(pagina)
        neutras[codigo] = colega
        publicadas[codigo] = {"url": f"{CFG['url_sitio']}/{codigo}", "notion_id": p["_id"], "fotos": len(claves),
                              "tarjeta": tarjeta}
        print(f"  {codigo} ok ({len(claves)} fotos)")

    if not solo:
        # Las que salieron del catálogo (vendidas o retiradas) se borran del sitio.
        for d in SITIO.iterdir():
            if d.is_dir() and re.fullmatch(r"D\d{3}", d.name) and d.name not in publicadas:
                shutil.rmtree(d)
                print(f"  {d.name} retirada del sitio")
        fotos = SITIO / "fotos"
        if fotos.exists():
            for d in fotos.iterdir():
                if d.is_dir() and d.name not in publicadas:
                    shutil.rmtree(d)
        (SITIO / "propiedades.json").write_text(json.dumps(publicadas, ensure_ascii=False, indent=1, sort_keys=True))

    # Portafolio: inicio con todas las propiedades y una página por tipo.
    todas = {**anteriores, **publicadas} if solo else publicadas
    tarjetas = [v["tarjeta"] for v in todas.values() if v.get("tarjeta")]
    (SITIO / "index.html").write_text(inicio(tarjetas))
    for tipo, slug, nombre in SECCIONES:
        carpeta = SITIO / slug
        if any(t["tipo"] == tipo for t in tarjetas):
            carpeta.mkdir(exist_ok=True)
            (carpeta / "index.html").write_text(seccion(tipo, slug, nombre, tarjetas))
        elif carpeta.exists():
            shutil.rmtree(carpeta)
    (SITIO / "404.html").write_text(no_encontrada())
    # Sitio neutro para colegas (solo si existe su carpeta: el clon de fichas-dre.github.io).
    if not solo and FICHAS.exists():
        try:
            publicar_fichas(publicadas, neutras)
        except Exception as e:
            omitidas.append(("fichas para colegas", f"no se generaron ({e})"))
    # Página privada para enviar propiedades por WhatsApp (nombres de edificio cifrados con PIN).
    enviar.generar(SITIO, CFG, todas, (RAIZ / "plantilla" / "enviar.html").read_text())

    print(f"Publicadas: {len(publicadas)}")
    for c, motivo in omitidas:
        print(f"  OMITIDA {c}: {motivo}")

    if publicar:
        subir()


def subir():
    if not re.sub(r"\D", "", CFG.get("whatsapp", "")):
        sys.exit("No se publica: falta el número de WhatsApp en config.json.")
    def git(*a, check=True):
        return subprocess.run(["git", "-C", str(SITIO), *a], check=check, capture_output=True, text=True)
    # Copia del código en el repo, para que GitHub Actions genere la web sin este computador.
    destino = SITIO / "_fuente"
    destino.mkdir(exist_ok=True)
    for nombre in FUENTE:
        origen = RAIZ / nombre
        if origen.is_dir():
            shutil.copytree(origen, destino / nombre, dirs_exist_ok=True)
        else:
            shutil.copy2(origen, destino / nombre)
    git("add", "-A")
    if not git("status", "--porcelain").stdout.strip():
        print("Sin cambios para subir.")
        return
    git("commit", "-m", f"Actualización automática {time.strftime('%Y-%m-%d %H:%M')}")
    git("pull", "--rebase", "-X", "theirs", "origin", "main", check=False)  # por si GitHub Actions publicó antes
    r = git("push", "origin", "HEAD:main", check=False)
    print("Subido a GitHub Pages." if r.returncode == 0 else f"ERROR al subir: {r.stderr.strip()}")
    if r.returncode != 0:
        sys.exit(1)
    subir_fichas()


def subir_fichas():
    """Sube el sitio neutro para colegas con el token de fichas-dre (llavero: duo-fichas-token)."""
    if not (FICHAS / ".git").exists():
        return
    token = enviar.secreto("FICHAS_TOKEN", "duo-fichas-token")
    if not token:
        print("Fichas para colegas: falta el token de fichas-dre; no se subieron.")
        return
    remoto = f"https://x-access-token:{token}@github.com/fichas-dre/fichas-dre.github.io.git"
    def git(*a, check=True):
        return subprocess.run(["git", "-C", str(FICHAS), "-c", "user.name=fichas",
                               "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com", *a],
                              check=check, capture_output=True, text=True)
    git("add", "-A")
    if not git("status", "--porcelain").stdout.strip():
        print("Fichas para colegas: sin cambios.")
        return
    git("commit", "-m", f"Actualización {time.strftime('%Y-%m-%d %H:%M')}")
    git("pull", "--rebase", "-X", "theirs", remoto, "main", check=False)
    r = git("push", remoto, "HEAD:main", check=False)
    print("Fichas para colegas subidas." if r.returncode == 0 else "ERROR al subir las fichas para colegas.")


if __name__ == "__main__":
    main()
