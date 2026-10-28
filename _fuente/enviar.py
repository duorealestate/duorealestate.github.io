"""Página privada "Enviar" (duorealestate.github.io/enviar/) para Camila y Luz Stella.

Lista las propiedades del catálogo con dos botones: "A cliente" (link de la web) y "A colega"
(ficha pública de Notion). Los nombres de edificio y número de unidad salen de la base interna y
van CIFRADOS en la página: solo se leen con la llave del link de instalación más el PIN.
Nunca se escriben en claro en el sitio ni en los mensajes.

Secretos (en GitHub Actions como variables de entorno; en el Mac, en el llavero):
  NOTION_TOKEN  · llave de Notion de solo lectura con acceso a PROPIEDADES - interno  (llavero: duo-notion-token)
  DUO_ENVIAR    · "llave:PIN" (llave = 64 caracteres hexadecimales)                     (llavero: duo-enviar)
Sin ellos la página se publica igual, pero sin búsqueda por nombre.
Con "url_editor" en config.json, cada tarjeta muestra un lápiz ✏️ (solo con el PIN) que guarda en Notion
por medio del Worker de Cloudflare "editor-duo" (automatizacion/editor-cloudflare.js).
"""
import base64
import hashlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path

DB_INTERNA = "3ce22d40016d80cd829dd22743da3ad1"  # PROPIEDADES - interno


def secreto(variable, servicio):
    valor = os.environ.get(variable, "").strip()
    if valor:
        return valor
    try:
        return subprocess.run(["security", "find-generic-password", "-s", servicio, "-w"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return ""


def leer_nombres():
    """{código DÚO: [nombre, número, m² de lote]} desde la base interna, o None si no hay llave."""
    prueba = os.environ.get("DUO_NOMBRES_PRUEBA")  # solo para probar en el computador
    if prueba:
        return json.loads(Path(prueba).read_text())
    token = secreto("NOTION_TOKEN", "duo-notion-token")
    if not token:
        return None
    nombres, cursor = {}, None
    while True:
        cuerpo = {"page_size": 100}
        if cursor:
            cuerpo["start_cursor"] = cursor
        req = urllib.request.Request(
            f"https://api.notion.com/v1/databases/{DB_INTERNA}/query", data=json.dumps(cuerpo).encode(),
            headers={"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
        for pg in d["results"]:
            pr = pg["properties"]
            nombre = "".join(t["plain_text"] for t in pr.get("Título", {}).get("title", [])).strip()
            numero = "".join(t["plain_text"] for t in pr.get("Número", {}).get("rich_text", [])).strip()
            lote = pr.get("Área lote m²", {}).get("number") or 0
            codigo = ((pr.get("Código DÚO", {}).get("formula") or {}).get("string") or "").strip().upper()
            if codigo:
                nombres[codigo] = [nombre, numero, lote]
        if not d.get("has_more"):
            return nombres
        cursor = d["next_cursor"]


def cifrar(texto, llave_hex, pin):
    """Cifrado de flujo con SHA-256 (sin librerías). Mismo algoritmo que descifrar() en plantilla/enviar.html.
    El nonce sale del contenido: si los nombres no cambian, la página tampoco y no hay commits de más."""
    llave = hashlib.sha256(bytes.fromhex(llave_hex) + pin.encode()).digest()
    datos = texto.encode()
    nonce = hashlib.sha256(b"nonce" + llave + datos).digest()[:16]
    flujo, i = bytearray(), 0
    while len(flujo) < len(datos):
        flujo += hashlib.sha256(llave + nonce + i.to_bytes(4, "big")).digest()
        i += 1
    cif = bytes(a ^ b for a, b in zip(datos, flujo))
    tag = hashlib.sha256(b"tag" + llave + nonce + cif).digest()[:16]
    return base64.b64encode(nonce + tag + cif).decode()


def generar(sitio, cfg, publicadas, plantilla):
    destino = sitio / "enviar" / "index.html"
    props = []
    for codigo, v in sorted(publicadas.items(), reverse=True):
        t = v.get("tarjeta")
        if not t:
            continue
        props.append({"cod": codigo, "tipo": t["tipo"], "sector": t["sector"], "titulo": t["titulo"], "ops": t["ops"],
                      "venta": t["venta"], "canon": t["canon"], "area": t["area"], "alc": t["alc"], "foto": t["foto"],
                      "ban": t.get("ban", 0), "parq": t.get("parq", 0), "ext": t.get("ext", 0), "det": t.get("det", {}),
                      "web": v["url"], "ficha": f"{cfg['url_fichas']}/{codigo}",
                      "id": v["notion_id"].replace("-", "")})

    cifrado = ""
    clave = secreto("DUO_ENVIAR", "duo-enviar")
    if clave:
        try:
            nombres = leer_nombres()
        except Exception as e:  # Notion falló: se deja la página anterior y se reintenta en la próxima corrida
            print(f"  Enviar: no se pudieron leer los nombres ({e}); se deja la versión anterior")
            if destino.exists():
                return
            nombres = None
        if nombres is not None:
            llave_hex, pin = clave.split(":", 1)
            por_codigo = {p["cod"]: nombres[p["cod"]][:2] for p in props if p["cod"] in nombres}
            for p in props:  # el área de lote no es privada: va en claro (solo casas)
                if p["tipo"] == "Casa" and nombres.get(p["cod"], [0, 0, 0])[2]:
                    p["lote"] = nombres[p["cod"]][2]
            cifrado = cifrar(json.dumps(por_codigo, ensure_ascii=False, sort_keys=True), llave_hex, pin)
            print(f"  Enviar: {len(por_codigo)} de {len(props)} propiedades con nombre")
    for p in props:
        del p["id"]

    html = plantilla.replace("/*DATOS*/[]", json.dumps(props, ensure_ascii=False)).replace("/*NOMBRES*/\"\"", json.dumps(cifrado)) \
        .replace("/*EDITOR*/\"\"", json.dumps(cfg.get("url_editor", "")))
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(html)
