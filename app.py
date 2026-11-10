#!/usr/bin/env python3
"""
Load'nt? — vigila cualquier página que casi nunca carga y avisa cuando funciona de verdad.

Cualquiera pega un enlace en la página de inicio y recibe su propia página de vigilancia
(/v/<id>) con captura en vivo, lista de pruebas, historial en lenguaje simple y avisos al celular.

Cada revisión abre el enlace en Chromium (Playwright) y prueba:
  1. El sitio contesta
  2. Hay contenido (no está en blanco ni muestra un error)
  3. Carga completa (diseño y scripts)
  4. Se ve en pantalla
  5. Hay botones que se pueden presionar
  6. Los botones responden: solo hace clic en botones seguros como «Siguiente», «Comenzar» o «Next»
     (nunca enviar, pagar, comprar, borrar...), y como máximo cada CLICK_EVERY segundos.

Sin Playwright funciona en "modo básico" (solo pasos 1 y 2).

Variables de entorno (opcionales):
  SITE_NAME ("Load'nt?"), PORT (8000), CHECK_EVERY (30), TIMEOUT (45), CLICK_EVERY (600)
  MAX_WATCHES (12)      cuántos enlaces se vigilan a la vez
  WATCH_HOURS (24)      se deja de vigilar un enlace si nadie abre su página en este tiempo
  WORKERS (1)           navegadores trabajando en paralelo (cada uno usa ~200 MB)
  PRESET_URLS           enlaces destacados en el inicio, separados por espacios
  NTFY_SERVER (https://ntfy.sh), NTFY_PREFIX (loadnt)
  DATA_DIR (./data)     donde se guarda la lista de enlaces
  ALLOW_PRIVATE (0)     1 = permite vigilar direcciones locales (solo para pruebas)
"""

import hashlib
import html
import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
    HAVE_BROWSER = True
except ImportError:
    HAVE_BROWSER = False

SITE_NAME = os.environ.get("SITE_NAME", "Load'nt?")
PORT = int(os.environ.get("PORT", "8000"))
CHECK_EVERY = int(os.environ.get("CHECK_EVERY", "30"))
TIMEOUT = int(os.environ.get("TIMEOUT", "45"))
CLICK_EVERY = int(os.environ.get("CLICK_EVERY", "600"))
MAX_WATCHES = int(os.environ.get("MAX_WATCHES", "12"))
WATCH_HOURS = float(os.environ.get("WATCH_HOURS", "24"))
WORKERS = max(1, int(os.environ.get("WORKERS", "1")))
PRESET_URLS = os.environ.get("PRESET_URLS", "").split()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_PREFIX = os.environ.get("NTFY_PREFIX", "loadnt")
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "data"))
ALLOW_PRIVATE = os.environ.get("ALLOW_PRIVATE", "0") == "1"
CHECK_PROXY = os.environ.get("CHECK_PROXY", "")          # e.g. http://user:pass@proxy-en-ecuador:8080
CHECKER_REGION = os.environ.get("CHECKER_REGION", "Ecuador" if CHECK_PROXY else "Estados Unidos")
NOTIFY_COOLDOWN = 600
HISTORY_SECONDS = 24 * 3600
LOG_SIZE = 50
MIN_TEXT = 150
ROOT = Path(__file__).parent

MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
ERROR_PHRASES = ["service unavailable", "bad gateway", "gateway timeout", "internal server error",
                 "too many connections", "database error", "error establishing", "fatal error",
                 "servicio no disponible", "error interno", "error de base de datos"]

CAPTCHA_PHRASES = ["captcha", "verify you are human", "verifica que eres humano", "no soy un robot", "not a robot",
                   "attention required", "just a moment", "checking your browser", "comprobando tu navegador", "cf-chl"]
DENIED_PHRASES = ["access denied", "acceso denegado", "forbidden", "prohibido", "you don't have permission",
                  "no tiene permiso", "no tienes permiso", "request blocked", "solicitud bloqueada"]
GEO_PHRASES = ["not available in your country", "no disponible en su país", "no disponible en tu país",
               "not available in your region", "no disponible en su región", "solo disponible en ecuador",
               "only available in ecuador", "fuera del país", "outside the country"]
MAINT_PHRASES = ["mantenimiento", "maintenance", "en construcción", "volvemos pronto", "be right back"]
SESSION_PHRASES = ["sesión ha caducado", "sesion ha caducado", "session has expired", "session expired",
                   "sesión expirada", "sesion expirada", "su sesión ha expirado"]


COUNTRY_BY_TLD = {
    "ec": "Ecuador", "co": "Colombia", "pe": "Perú", "mx": "México", "ar": "Argentina", "cl": "Chile",
    "ve": "Venezuela", "bo": "Bolivia", "py": "Paraguay", "uy": "Uruguay", "br": "Brasil", "gt": "Guatemala",
    "hn": "Honduras", "sv": "El Salvador", "ni": "Nicaragua", "cr": "Costa Rica", "pa": "Panamá",
    "do": "República Dominicana", "cu": "Cuba", "pr": "Puerto Rico", "es": "España", "us": "Estados Unidos",
    "ca": "Canadá", "uk": "Reino Unido", "gb": "Reino Unido", "fr": "Francia", "de": "Alemania", "it": "Italia",
    "pt": "Portugal", "nl": "Países Bajos", "in": "India", "ph": "Filipinas", "cn": "China", "ru": "Rusia",
}


def site_country(host):
    """Country a site most likely belongs to, from its domain ending (.ec, .gob.mx, .gov.co…). None if unknown."""
    return COUNTRY_BY_TLD.get((host or "").rsplit(".", 1)[-1].lower())


def err_kind(e):
    s = str(e)
    reason = getattr(e, "reason", None)
    if "ERR_NAME_NOT_RESOLVED" in s or isinstance(reason, socket.gaierror):
        return "dns"
    if "ERR_CONNECTION_RESET" in s or "ERR_EMPTY_RESPONSE" in s or "ERR_CONNECTION_CLOSED" in s \
            or isinstance(reason, ConnectionResetError) or isinstance(e, ConnectionResetError):
        return "reset"
    if "ERR_CONNECTION_REFUSED" in s or isinstance(reason, ConnectionRefusedError):
        return "refused"
    if "Timeout" in s or "TIMED_OUT" in s or isinstance(e, (socket.timeout, TimeoutError)) \
            or isinstance(reason, (socket.timeout, TimeoutError)):
        return "timeout"
    return "other"


def cert_problem(url):
    """Check the site's HTTPS certificate the way a normal browser would. Returns None, 'expired', 'invalid' or 'error'."""
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or CHECK_PROXY:
        return None
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((p.hostname, p.port or 443), timeout=15) as sock:
            with ctx.wrap_socket(sock, server_hostname=p.hostname):
                return None
    except ssl.SSLCertVerificationError as e:
        msg = str(e).lower()
        return "expired" if ("expired" in msg or "not yet valid" in msg) else "invalid"
    except Exception:
        return "error"   # couldn't connect at all; says nothing about the certificate


def proxy_settings():
    if not CHECK_PROXY:
        return None
    p = urllib.parse.urlsplit(CHECK_PROXY)
    d = {"server": f"{p.scheme or 'http'}://{p.hostname}:{p.port or 8080}"}
    if p.username:
        d["username"] = urllib.parse.unquote(p.username)
        d["password"] = urllib.parse.unquote(p.password or "")
    return d


STEP_LABELS = [
    ("server", "El sitio contesta"),
    ("content", "Hay contenido"),
    ("assets", "Carga completa"),
    ("render", "Se ve en pantalla"),
    ("buttons", "Hay botones para presionar"),
    ("click", "Los botones responden"),
    ("mobile", "Se ve en celular"),
]


def step(key, st, detail):
    return {"key": key, "label": dict(STEP_LABELS)[key], "state": st, "detail": detail}


def secs_txt(ms):
    s = ms / 1000
    return "menos de 1 segundo" if s < 1 else f"{round(s)} segundo{'s' if round(s) != 1 else ''}"


# ------------------------------------------------------------------ link safety

_host_cache = {}


def host_is_public(host):
    """True if every address for this host is a normal internet address (not local/private)."""
    if ALLOW_PRIVATE:
        return True
    hit = _host_cache.get(host)
    if hit and time.time() - hit[1] < 600:
        return hit[0]
    try:
        infos = socket.getaddrinfo(host, None)
        ok = bool(infos) and all(ipaddress.ip_address(i[4][0].split("%")[0]).is_global for i in infos)
    except Exception:
        ok = None  # can't resolve right now
    _host_cache[host] = (ok, time.time())
    return ok


def clean_url(raw):
    """Validate a link typed by a person. Returns the normalized URL or raises ValueError (Spanish message)."""
    u = (raw or "").strip()
    if not u:
        raise ValueError("Pega un enlace primero.")
    if len(u) > 2000:
        raise ValueError("Ese enlace es demasiado largo.")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", u, re.I):
        u = "https://" + u
    p = urllib.parse.urlsplit(u)
    if p.scheme.lower() not in ("http", "https") or not p.hostname or "." not in p.hostname and not ALLOW_PRIVATE:
        raise ValueError("Eso no parece un enlace de una página web. Debe verse como https://sitio.com/…")
    if p.username or p.password:
        raise ValueError("Quita el usuario y contraseña del enlace.")
    try:
        ipaddress.ip_address(p.hostname)
        is_ip = True
    except ValueError:
        is_ip = False
    ok = host_is_public(p.hostname)
    if ok is None:
        raise ValueError("No encontramos ese sitio. Revisa que el enlace esté bien escrito.")
    if not ok:
        raise ValueError("Ese enlace apunta a una red privada o local, y no se puede vigilar desde aquí.")
    netloc = p.hostname.lower() + (f":{p.port}" if p.port else "")
    if is_ip and ":" in p.hostname:
        netloc = f"[{p.hostname}]" + (f":{p.port}" if p.port else "")
    return urllib.parse.urlunsplit((p.scheme.lower(), netloc, p.path or "/", p.query, ""))


# ------------------------------------------------------------------ watches

lock = threading.Lock()
watches = {}      # id -> watch dict
by_url = {}       # url -> id


def new_watch(url, wid=None, created=None, last_view=None, preset=False):
    wid = wid or secrets.token_urlsafe(6).replace("-", "a").replace("_", "b")
    now = time.time()
    w = {
        "id": wid, "url": url, "host": urllib.parse.urlsplit(url).hostname, "preset": preset,
        "created": created or now, "last_view": last_view or now, "active": True, "busy": False,
        "status": "comprobando", "status_since": now,
        "summary": "Haciendo la primera revisión…",
        "steps": [step(k, "pending", "Todavía no se revisa") for k, _ in STEP_LABELS],
        "click": None, "mobile": None, "notes": [], "last_ms": None, "attempts": 0,
        "last_up_at": None, "up_window": None,      # {start, end} of the last time it worked
        "capture": None, "capture_t": None, "capture_live": False,
        "notified_at": None, "next_check_at": now,
        "history": [],   # [t, status, ms] for 24 h
        "topic": f"{NTFY_PREFIX}-{wid}",
    }
    watches[wid] = w
    by_url[url] = wid
    return w


def save():
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with lock:
            data = [{k: w[k] for k in ("id", "url", "created", "last_view", "preset")} for w in watches.values()]
        tmp = DATA_DIR / "watches.json.tmp"
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(DATA_DIR / "watches.json")
    except Exception as e:
        print(f"No se pudo guardar la lista: {e}", flush=True)


def load():
    try:
        data = json.loads((DATA_DIR / "watches.json").read_text(encoding="utf-8"))
    except Exception:
        data = []
    with lock:
        for d in data:
            if d["url"] not in by_url:
                new_watch(d["url"], d["id"], d["created"], d["last_view"], d.get("preset", False))
        for raw in PRESET_URLS:
            try:
                url = clean_url(raw)
            except ValueError as e:
                print(f"Enlace destacado no válido ({raw}): {e}", flush=True)
                continue
            if url in by_url:
                watches[by_url[url]]["preset"] = True
            else:
                new_watch(url, preset=True)


def active_count():
    return sum(1 for w in watches.values() if w["active"])


def touch(w):
    w["last_view"] = time.time()
    if not w["active"]:
        if active_count() < MAX_WATCHES:
            w["active"] = True
            w["next_check_at"] = time.time()


# ------------------------------------------------------------------ friendly error wording

def describe_error(e):
    s = str(e)
    reason = getattr(e, "reason", None)
    if "ERR_NAME_NOT_RESOLVED" in s or isinstance(reason, socket.gaierror):
        return "No se encontró el sitio en internet"
    if "ERR_CONNECTION_RESET" in s or isinstance(reason, ConnectionResetError) or isinstance(e, ConnectionResetError):
        return "El sitio cortó la conexión"
    if "ERR_CONNECTION_REFUSED" in s or isinstance(reason, ConnectionRefusedError):
        return "El sitio no aceptó la visita"
    if "ERR_EMPTY_RESPONSE" in s:
        return "El sitio contestó, pero vacío"
    if "ERR_BLOCKED" in s or "blocked" in s.lower():
        return "La página intentó llevarnos a una dirección privada"
    if "Timeout" in s or "TIMED_OUT" in s or isinstance(e, (socket.timeout, TimeoutError)) \
            or isinstance(reason, (socket.timeout, TimeoutError)):
        return f"No contestó (esperamos {TIMEOUT} segundos)"
    if isinstance(e, urllib.error.HTTPError):
        return http_error(e.code)
    if "SSL" in s or "CERT" in s:
        return "El sitio tiene un problema de seguridad (certificado)"
    return "No se pudo abrir el sitio"


def http_error(code):
    if code == 404:
        return "La página no existe (error 404)"
    if code in (401, 403):
        return f"El sitio no deja entrar (error {code})"
    if code == 429:
        return "El sitio está recibiendo demasiadas visitas (error 429)"
    if code >= 500:
        return f"El sitio está caído o saturado (error {code})"
    return f"El sitio dio un error (código {code})"


# ------------------------------------------------------------------ browser check

INSPECT_JS = r"""() => {
  const vis = (el, inView) => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    if (r.width < 4 || r.height < 4 || s.visibility === "hidden" || s.display === "none" || parseFloat(s.opacity) < 0.05) return false;
    return !inView || (r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth);
  };
  const text = document.body ? (document.body.innerText || "").replace(/\s+/g, " ").trim() : "";
  let visible = 0, chars = 0, imgs = 0, n = 0;
  for (const el of document.body ? document.body.querySelectorAll("*") : []) {
    if (++n > 4000) break;
    if (["SCRIPT","STYLE","NOSCRIPT","TEMPLATE"].includes(el.tagName)) continue;
    const own = [...el.childNodes].filter(x => x.nodeType === 3).map(x => x.textContent.trim()).join("");
    const media = ["IMG","INPUT","BUTTON","SELECT","TEXTAREA","SVG","CANVAS","VIDEO"].includes(el.tagName.toUpperCase());
    if (!own && !media) continue;
    if (!vis(el, true)) continue;
    visible++; chars += own.length; if (el.tagName === "IMG") imgs++;
  }
  const controls = [...document.querySelectorAll('button,input[type=submit],input[type=button],a.btn,a.button,a[role=button],[role=button]')]
    .filter(el => vis(el, false));
  const buttons = controls.map(b => ({
    text: (b.innerText || b.value || b.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim().slice(0, 30),
    disabled: !!b.disabled || b.getAttribute("aria-disabled") === "true"
  }));
  return { textLen: text.length, text: text.slice(0, 500), hasForm: !!document.querySelector("form"),
           visible, chars, imgs, buttons, sheets: document.styleSheets.length, title: document.title.slice(0, 120),
           href: location.href, low: (document.title + " " + text).slice(0, 4000).toLowerCase() };
}"""

# Only "move forward" buttons are ever clicked, never anything that could send, buy or delete.
PICK_BUTTON_JS = r"""() => {
  const good = /^(siguiente|comenzar|iniciar|empezar|continuar|avanzar|next|start|begin|continue|get started|comenzar encuesta|iniciar encuesta)\b/i;
  const bad = /enviar|submit|send|pagar|pay|comprar|buy|checkout|order|pedido|borrar|eliminar|delete|remove|salir|exit|logout|cerrar sesi|suscrib|subscribe|registr|sign|aceptar|accept|confirm|guardar|save|cancel|limpiar|clear|donar|donate|reservar|book/i;
  const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 4 && r.height > 4 && s.visibility !== "hidden" && s.display !== "none"; };
  const label = el => (el.innerText || el.value || el.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim();
  const pick = [...document.querySelectorAll('button,input[type=submit],input[type=button],a.btn,a.button,a[role=button],[role=button]')]
    .find(el => vis(el) && !el.disabled && good.test(label(el)) && !bad.test(label(el)));
  if (!pick) return null;
  pick.setAttribute("data-loadnt", "1");
  return label(pick).slice(0, 30);
}"""

SNAP_JS = "() => [location.href, (document.body && document.body.innerText || '').length, document.getElementsByTagName('*').length]"


class BrowserChecker:
    def __init__(self):
        self.pw = None
        self.browser = None
        self.contexts = {}   # one long-lived browser profile per watched link, so downloaded files stay cached like a real visitor

    def ensure(self):
        if self.browser and self.browser.is_connected():
            return
        if not self.pw:
            self.pw = sync_playwright().start()
        kw = {"args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]}
        if proxy_settings():
            kw["proxy"] = proxy_settings()
        self.browser = self.pw.chromium.launch(**kw)

    def reset(self):
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        self.browser = None
        self.contexts = {}

    def context_for(self, key):
        ctx = self.contexts.get(key)
        if ctx is None:
            if len(self.contexts) >= MAX_WATCHES * 2:          # drop the oldest profile
                old = next(iter(self.contexts))
                try:
                    self.contexts.pop(old).close()
                except Exception:
                    pass
            ctx = self.browser.new_context(viewport={"width": 1280, "height": 860}, locale="es-EC",
                                           ignore_https_errors=True, user_agent=UA, accept_downloads=False)
            self.contexts[key] = ctx
        return ctx

    def run(self, url, want_click, key=None):
        self.ensure()
        ctx = self.context_for(key or url)
        page = ctx.new_page()
        bad_assets, js_errors, doc_status = set(), [], []

        def guard(route):
            host = urllib.parse.urlsplit(route.request.url).hostname
            if route.request.url.startswith(("data:", "blob:")) or (host and host_is_public(host) is not False):
                route.continue_()
            else:
                route.abort("blockedbyclient")

        page.route("**/*", guard)

        def on_response(r):
            rt = r.request.resource_type
            if rt in ("stylesheet", "script") and r.status >= 400:
                bad_assets.add(r.url)
            if rt == "document" and r.frame == page.main_frame:
                doc_status.append(r.status)

        page.on("response", on_response)
        page.on("requestfailed", lambda q: bad_assets.add(q.url)
                if q.resource_type in ("stylesheet", "script") else None)
        page.on("pageerror", lambda e: js_errors.append(str(e)[:100]))

        steps = {k: step(k, "pending", "No se revisó") for k, _ in STEP_LABELS}
        out = {"steps": steps, "jpg": None, "click": None, "ms": None, "notes": [], "err": None, "pass": False}
        t0 = time.time()
        try:
            try:
                resp = page.goto(url, timeout=TIMEOUT * 1000, wait_until="domcontentloaded")
            except Exception as e:
                out["ms"] = int((time.time() - t0) * 1000)
                out["err"] = err_kind(e)
                steps["server"] = step("server", "fail", describe_error(e))
                return out
            out["ms"] = int((time.time() - t0) * 1000)
            code = resp.status if resp else 0
            if code and not (200 <= code < 400):
                steps["server"] = step("server", "fail", http_error(code))
                if code in (401, 403, 451):
                    out["notes"].append("blocked")
                elif code == 429:
                    out["notes"].append("busy")
            else:
                steps["server"] = step("server", "ok", f"Contestó en {secs_txt(out['ms'])}")

            for st, ms in (("load", 15000), ("networkidle", 8000)):
                try:
                    page.wait_for_load_state(st, timeout=ms)
                except Exception:
                    pass
            page.wait_for_timeout(800)
            info = page.evaluate(INSPECT_JS)
            try:
                out["jpg"] = page.screenshot(type="jpeg", quality=68)
            except Exception:
                pass
            if steps["server"]["state"] == "fail":
                return out

            low = info["low"]
            final_host = urllib.parse.urlsplit(info["href"]).hostname or ""
            if final_host and final_host != urllib.parse.urlsplit(url).hostname \
                    and not final_host.endswith("." + urllib.parse.urlsplit(url).hostname) \
                    and not urllib.parse.urlsplit(url).hostname.endswith("." + final_host):
                out["notes"].append("redirect:" + final_host)
            if "cookie" in low and any(w in low for w in ("habilit", "activ", "enable", "bloque", "disabled", "deshabilit", "permit", "allow")):
                out["notes"].append("cookies")
            if any(p in low for p in SESSION_PHRASES):
                out["notes"].append("session")
            short = info["textLen"] < 1500
            if short and any(p in low for p in CAPTCHA_PHRASES):
                out["notes"].append("captcha")
                steps["content"] = step("content", "fail", "Muestra una verificación «no soy un robot»")
            elif short and any(p in low for p in GEO_PHRASES):
                out["notes"].append("geo_text")
                steps["content"] = step("content", "fail", "Dice que no está disponible desde este país")
            elif short and any(p in low for p in DENIED_PHRASES):
                out["notes"].append("blocked")
                steps["content"] = step("content", "fail", "Dice que no tenemos permiso para entrar")
            elif short and any(p in low for p in MAINT_PHRASES):
                out["notes"].append("maintenance")
                steps["content"] = step("content", "fail", "Dice que está en mantenimiento")
            elif info["textLen"] < 600 and any(p in low for p in ERROR_PHRASES):
                steps["content"] = step("content", "fail", "Muestra un mensaje de error del sitio")
            elif info["textLen"] < MIN_TEXT and not info["hasForm"] and info["imgs"] == 0:
                steps["content"] = step("content", "fail", "La página está en blanco")
            else:
                bits = ["texto"] + (["un formulario"] if info["hasForm"] else []) + (["imágenes"] if info["imgs"] else [])
                desc = bits[0] if len(bits) == 1 else ", ".join(bits[:-1]) + " y " + bits[-1]
                steps["content"] = step("content", "ok", "Se ve " + desc)

            if bad_assets:
                out["notes"].append("partial_assets")
                steps["assets"] = step("assets", "fail", f"Faltan partes de la página ({len(bad_assets)} no cargaron)")
            elif info["sheets"] == 0:
                steps["assets"] = step("assets", "warn", "Se ve sin diseño, pero se puede usar")
            elif js_errors:
                steps["assets"] = step("assets", "warn", "Tiene errores menores, pero se puede usar")
            else:
                steps["assets"] = step("assets", "ok", "Cargó completa, con su diseño")

            if info["chars"] >= 60 or info["visible"] >= 6 or info["imgs"] >= 1:
                steps["render"] = step("render", "ok", "Se ve bien en pantalla")
            else:
                steps["render"] = step("render", "fail", "No se ve nada en pantalla")

            btns = info["buttons"]
            enabled = [b for b in btns if not b["disabled"]]
            if not btns:
                steps["buttons"] = step("buttons", "warn", "No encontramos botones en esta página")
            elif not enabled:
                steps["buttons"] = step("buttons", "fail", "Los botones aparecen, pero no se pueden presionar")
            else:
                names = [n for n in dict.fromkeys(b["text"] for b in enabled) if n][:3]
                steps["buttons"] = step("buttons", "ok", "Se pueden presionar" + (": " + ", ".join(f"«{n}»" for n in names) if names else ""))

            out["pass"] = not any(steps[k]["state"] == "fail" for k in ("content", "assets", "render", "buttons"))
            if not out["pass"] or not want_click:
                return out
            target = page.evaluate(PICK_BUTTON_JS)
            if not target:
                out["click"] = {"ok": None, "t": time.time(), "detail": "No hay un botón «Siguiente» o «Comenzar» para probar sin riesgo"}
                return out
            before = page.evaluate(SNAP_JS)
            n_docs = len(doc_status)
            try:
                page.click("[data-loadnt]", timeout=10000)
            except Exception:
                out["click"] = {"ok": False, "t": time.time(), "detail": f"No se pudo presionar «{target}»"}
                return out
            for st, ms in (("load", 15000), ("networkidle", 6000)):
                try:
                    page.wait_for_load_state(st, timeout=ms)
                except Exception:
                    pass
            page.wait_for_timeout(1200)
            after = page.evaluate(SNAP_JS)
            new_docs = doc_status[n_docs:]
            if new_docs and new_docs[-1] >= 400:
                out["click"] = {"ok": False, "t": time.time(), "detail": f"Presionamos «{target}» y salió un error"}
            elif after == before:
                out["click"] = {"ok": False, "t": time.time(), "detail": f"Presionamos «{target}» y no pasó nada"}
            else:
                info2 = page.evaluate(INSPECT_JS)
                if info2["textLen"] < 50 and not info2["hasForm"]:
                    out["click"] = {"ok": False, "t": time.time(), "detail": f"Presionamos «{target}» y quedó en blanco"}
                elif info2["textLen"] < 600 and any(p in info2["text"].lower() for p in ERROR_PHRASES):
                    out["click"] = {"ok": False, "t": time.time(), "detail": f"Presionamos «{target}» y salió un error"}
                else:
                    out["click"] = {"ok": True, "t": time.time(), "detail": f"Presionamos «{target}» y avanzó"}
            return out
        finally:
            try:
                page.close()
            except Exception:
                pass


def _mobile_check(self, url):
    """Open the page as a phone would. Returns {ok, t, detail}."""
    self.ensure()
    ctx = self.browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True,
                                   has_touch=True, locale="es-EC", ignore_https_errors=True, user_agent=MOBILE_UA)
    page = ctx.new_page()
    page.route("**/*", lambda r: r.continue_() if r.request.url.startswith(("data:", "blob:")) or
               host_is_public(urllib.parse.urlsplit(r.request.url).hostname or "") is not False else r.abort("blockedbyclient"))
    try:
        try:
            resp = page.goto(url, timeout=TIMEOUT * 1000, wait_until="domcontentloaded")
        except Exception as e:
            return {"ok": False, "t": time.time(), "detail": "En celular: " + describe_error(e).lower()}
        if resp and resp.status >= 400:
            return {"ok": False, "t": time.time(), "detail": "En celular da " + http_error(resp.status).lower()}
        for st, ms in (("load", 15000), ("networkidle", 6000)):
            try:
                page.wait_for_load_state(st, timeout=ms)
            except Exception:
                pass
        info = page.evaluate(INSPECT_JS)
        if info["textLen"] < MIN_TEXT and not info["hasForm"] and info["imgs"] == 0:
            return {"ok": False, "t": time.time(), "detail": "En celular se queda en blanco"}
        if info["chars"] < 60 and info["visible"] < 6 and info["imgs"] == 0:
            return {"ok": False, "t": time.time(), "detail": "En celular no se ve nada en pantalla"}
        wide = page.evaluate("() => document.documentElement.scrollWidth > innerWidth + 40")
        return {"ok": True, "t": time.time(), "detail": "Se ve en pantalla de celular" + (" (hay que mover de lado a lado)" if wide else "")}
    finally:
        try:
            ctx.close()
        except Exception:
            pass


BrowserChecker.mobile = _mobile_check


def basic_run(url, want_click=False):
    steps = {k: step(k, "skip", "Solo con el modo navegador") for k, _ in STEP_LABELS}
    out = {"steps": steps, "jpg": None, "click": None, "ms": None, "notes": [], "err": None, "pass": False}
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-EC,es;q=0.9"})
    t0 = time.time()
    try:
        try:
            r = urllib.request.urlopen(req, timeout=TIMEOUT)
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), ssl.SSLError):
                r = urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl._create_unverified_context())
            else:
                raise
        with r:
            body = r.read(3_000_000).decode("utf-8", errors="replace")
    except Exception as e:
        out["ms"] = int((time.time() - t0) * 1000)
        out["err"] = err_kind(e)
        steps["server"] = step("server", "fail", describe_error(e))
        return out
    out["ms"] = int((time.time() - t0) * 1000)
    out["pass"] = True
    steps["server"] = step("server", "ok", f"Contestó en {secs_txt(out['ms'])}")
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", body)
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"(?s)<[^>]+>", " ", t))).strip()
    if len(t) < MIN_TEXT and "<form" not in body.lower():
        steps["content"] = step("content", "fail", "La página está en blanco")
    else:
        steps["content"] = step("content", "ok", "Se ve texto")
    return out


# ------------------------------------------------------------------ verdict, stats, notifications

FAIL_SUMMARY = {
    "content": {"Muestra un mensaje de error del sitio": "Se abrió, pero muestra un mensaje de error",
                "La página está en blanco": "Se abrió, pero en blanco"},
    "assets": "Se abrió a medias: faltan partes de la página",
    "render": "Se abrió, pero no se ve nada en pantalla",
    "buttons": "Se abrió, pero los botones no se pueden presionar",
}


def decide(steps, click, basic):
    s = {x["key"]: x for x in steps}
    if s["server"]["state"] == "fail":
        return "caida", s["server"]["detail"]
    for k in ("content", "assets", "render", "buttons"):
        if s[k]["state"] == "fail":
            m = FAIL_SUMMARY[k]
            if isinstance(m, dict):
                d = s[k]["detail"]
                return "parcial", m.get(d, "Se abrió, pero " + d[0].lower() + d[1:])
            return "parcial", m
    if basic:
        return "funcionando", "¡Funciona! Se abrió con contenido"
    if click and click["ok"] is False:
        return "parcial", "Se ve bien, pero los botones no responden"
    if click and click["ok"]:
        return "funcionando", "¡Funciona! Se abrió completa y los botones responden"
    return "funcionando", "¡Funciona! Se abrió completa"


def stats_for(w, now):
    hist = [h for h in w["history"] if now - h[0] <= 3600]
    up = sum(1 for h in hist if h[1] == "funcionando")
    answered = [h[2] for h in hist if h[1] != "caida" and h[2] is not None]
    return {
        "hour_total": len(hist),
        "hour_up": up,
        "typical_ms": int(statistics.median(answered)) if answered else None,
        "day_total": len(w["history"]),
        "day_up": sum(1 for h in w["history"] if h[1] == "funcionando"),
    }


RANK = {"funcionando": 3, "parcial": 2, "caida": 1}


def minutes_for(w, now, n=60):
    """Best result in each of the last n minutes (oldest first); None = no check that minute."""
    out = [None] * n
    for h in w["history"]:
        i = n - 1 - int((now - h[0]) // 60)
        if 0 <= i < n and (out[i] is None or RANK.get(h[1], 0) > RANK.get(out[i], 0)):
            out[i] = h[1]
    return out


def timeline_for(w, limit=8):
    """Stretches of the same state, newest first: what a visitor actually wants to know."""
    segs = []
    for h in w["history"]:
        t, st, text = h[0], h[1], h[3]
        if segs and segs[-1]["status"] == st:
            seg = segs[-1]
            seg["end"], seg["count"], seg["text"] = t, seg["count"] + 1, text
            if st == "funcionando" and "botones responden" in text:
                seg["text"] = text
        else:
            segs.append({"status": st, "start": t, "end": t, "count": 1, "text": text})
    return segs[::-1][:limit]


def _post(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15).read()


def send_notification(w):
    if not NTFY_PREFIX:
        return
    try:
        _post(NTFY_SERVER, {
            "topic": w["topic"],
            "title": f"¡{w['host']} ya cargó!",
            "message": "Se abrió completa y funciona. Entra ahora, antes de que se caiga otra vez.",
            "click": w["url"], "priority": 5, "tags": ["white_check_mark"],
            "actions": [{"action": "view", "label": "Abrir página", "url": w["url"]}],
        })
        print(f"  aviso enviado a {w['topic']}", flush=True)
    except Exception as e:
        print(f"  no se pudo enviar el aviso: {e}", flush=True)


NOTE_TEXT = {
    "geo": ("Puede que no deje entrar desde fuera de {country}",
            "Este sitio parece ser de {country} y nuestro revisor está en {region}. Muchos sitios, sobre todo de gobierno, "
            "solo aceptan visitas desde su país o rechazan servidores. Mira «desde tu conexión»: si a ti sí te contesta, "
            "ábrelo tú directamente."),
    "blocked": ("El sitio rechaza nuestra visita",
                "Contestó que no tenemos permiso. Suele pasar cuando un sitio solo acepta visitas desde su país "
                "o bloquea navegadores automáticos. Desde tu conexión podría funcionar: ábrelo tú."),
    "geo_text": ("Dice que no está disponible desde este país",
                 "El propio sitio dice que solo funciona desde ciertos países. Nuestro revisor está en {region}. "
                 "Si estás en {country_or_pais}, ábrelo tú; si no, necesitarías conectarte desde ese país."),
    "captcha": ("Pide comprobar que eres humano",
                "Aparece una verificación tipo «no soy un robot». Nosotros no podemos pasarla, pero tú sí: "
                "abre la página y complétala."),
    "cookies": ("El sitio necesita cookies",
                "Si a ti no te carga, ábrelo en una ventana privada o borra las cookies de este sitio y vuelve a intentar. "
                "Revisa también que tu navegador no esté bloqueando cookies."),
    "session": ("Dice que la sesión caducó",
                "Al abrirlo, empieza de nuevo desde el inicio. Si te pasa a mitad del formulario, borra las cookies de "
                "este sitio o usa una ventana privada."),
    "maintenance": ("Está en mantenimiento",
                    "El propio sitio dice que está en mantenimiento. Normalmente vuelve solo: te avisamos cuando pase."),
    "busy": ("Hay demasiada gente entrando",
             "El sitio está saturado de visitas. Suele mejorar de noche o muy temprano en la mañana."),
    "slow": ("Es muy lento",
             "Cuando contesta, tarda unos {secs} segundos. Espera sin recargar la página: recargar vuelve a empezar la espera."),
    "redirect": ("Te manda a otra dirección",
                 "Al abrirla, termina en {host}. Revisa que sea el sitio correcto antes de escribir tus datos."),
    "cert_expired": ("Tu navegador dirá «La conexión no es privada»",
                     "El certificado de seguridad del sitio está vencido. Cuando funcione, tu navegador mostrará esa advertencia: "
                     "toca «Configuración avanzada» y luego «Continuar al sitio». Hazlo solo si la dirección es exactamente {host_self}."),
    "cert_invalid": ("Tu navegador dirá «La conexión no es privada»",
                     "El certificado de seguridad del sitio no es válido. Para entrar: «Configuración avanzada» y «Continuar al sitio», "
                     "solo si la dirección es exactamente {host_self}. No escribas contraseñas ni datos bancarios ahí."),
    "partial_assets": ("Recarga varias veces",
                       "La página llega, pero varias de sus partes (diseño, botones) se cortan en el camino. Tu navegador guarda "
                       "lo que ya bajó, así que cada recarga completa un poco más. Si se ve sin diseño o los botones no hacen nada, "
                       "recarga hasta que se vea bien."),
    "flaky": ("El sitio corta muchas conexiones",
              "A veces contesta y a veces corta la conexión. Recargar varias veces sí sirve aquí: en la última hora pasó en "
              "{flaky_ok} de {flaky_total} intentos."),
    "mobile": ("En celular no funciona igual",
               "{detail}. Si puedes, ábrelo desde una computadora."),
}


def build_notes(w, out, status, now):
    """Turn signals from the last checks into short, actionable explanations."""
    kinds, extra = [], {}
    for n in out.get("notes", []):
        if n.startswith("redirect:"):
            kinds.append("redirect")
            extra["host"] = n.split(":", 1)[1]
        elif n not in kinds:
            kinds.append(n)
    recent = w["history"][-4:]
    net_fails = [h for h in recent if h[1] == "caida" and len(h) > 4 and h[4] in ("timeout", "reset", "refused", "other")]
    country = site_country(w["host"])
    if (status == "caida" and country and country.lower() != CHECKER_REGION.lower()
            and len(net_fails) >= 2 and "geo" not in kinds):
        kinds.insert(0, "geo")
    if w.get("cert") in ("expired", "invalid"):
        kinds.insert(0, "cert_" + w["cert"])
    last_hour = [h for h in w["history"] if now - h[0] <= 3600]
    resets = [h for h in last_hour if h[1] == "caida" and len(h) > 4 and h[4] == "reset"]
    answered = [h for h in last_hour if h[1] != "caida"]
    if resets and answered and len(last_hour) >= 4 and status != "funcionando":
        kinds.append("flaky")
        extra["flaky_ok"], extra["flaky_total"] = len(answered), len(last_hour)
    hour = [h[2] for h in w["history"] if now - h[0] <= 3600 and h[1] != "caida" and h[2]]
    if hour and statistics.median(hour) > 20000:
        kinds.append("slow")
        extra["secs"] = round(statistics.median(hour) / 1000)
    if w.get("mobile") and w["mobile"]["ok"] is False:
        kinds.append("mobile")
        extra["detail"] = w["mobile"]["detail"]
    notes = []
    for k in kinds:
        if k in NOTE_TEXT:
            title, text = NOTE_TEXT[k]
            fmt = dict(region=CHECKER_REGION, host=extra.get("host", ""), secs=extra.get("secs", ""),
                       detail=extra.get("detail", ""), country=country or "su país", host_self=w["host"],
                       flaky_ok=extra.get("flaky_ok", ""), flaky_total=extra.get("flaky_total", ""),
                       country_or_pais=country or "el país del sitio")
            notes.append({"kind": k, "title": title.format(**fmt), "text": text.format(**fmt)})
    return notes[:3]


def check_watch(w, checker):
    with lock:
        url, prev_status, prev_click = w["url"], w["status"], w["click"]
    if time.time() - w.get("cert_t", 0) > 600:          # certificate check every 10 minutes
        c = cert_problem(url)
        if c != "error":
            w["cert"], w["cert_t"] = c, time.time()
    want_click = (prev_status != "funcionando" or not prev_click or time.time() - prev_click["t"] > CLICK_EVERY)
    try:
        out = checker.run(url, want_click, w["id"]) if checker else basic_run(url)
    except Exception as e:
        if checker:
            checker.reset()
        out = {"steps": {k: step(k, "pending", "No se revisó") for k, _ in STEP_LABELS},
               "jpg": None, "click": None, "ms": None, "notes": [], "err": err_kind(e), "pass": False}
        out["steps"]["server"] = step("server", "fail", describe_error(e))

    mobile = None
    if checker and out.get("pass"):
        if want_click:
            try:
                mobile = checker.mobile(url)
            except Exception:
                mobile = None
        elif w.get("mobile"):
            mobile = w["mobile"]
        if mobile:
            out["steps"]["mobile"] = step("mobile", "ok" if mobile["ok"] else "fail", mobile["detail"])
    elif checker:
        out["steps"]["mobile"] = step("mobile", "pending", "Se prueba cuando la página cargue")

    steps = [out["steps"][k] for k, _ in STEP_LABELS]
    s_ok = all(x["state"] in ("ok", "warn") for x in steps[:5])
    click = out["click"]
    if checker and s_ok:
        if click is None and prev_click and prev_status == "funcionando":
            click = prev_click
        if click is not None:
            age = time.time() - click["t"]
            when = "recién" if age < 5 else f"hace {int(age // 60)} min" if age >= 60 else f"hace {int(age)} s"
            st = "ok" if click["ok"] else ("warn" if click["ok"] is None else "fail")
            steps[5] = step("click", st, f"{click['detail']} ({when})" if click["ok"] is not None else click["detail"])
    elif checker:
        steps[5] = step("click", "pending", "Se prueba cuando la página cargue")

    status, summary = decide(steps, click if s_ok else None, checker is None)
    now = time.time()
    notify = False
    with lock:
        w["attempts"] += 1
        w["last_ms"] = out["ms"]
        w["steps"] = steps
        w["click"] = click if s_ok else None
        if status != w["status"]:
            if w["status"] == "funcionando" and w["up_window"] is not None:
                w["up_window"]["end"] = now
            if status == "funcionando":
                w["up_window"] = {"start": now, "end": None}
            w["status_since"] = now
        w["status"] = status
        w["summary"] = summary
        if out["jpg"]:
            w["capture"], w["capture_t"], w["capture_live"] = out["jpg"], now, True
        else:
            w["capture_live"] = False
        if status == "funcionando":
            w["last_up_at"] = now
            if prev_status != "funcionando" and (not w["notified_at"] or now - w["notified_at"] > NOTIFY_COOLDOWN):
                w["notified_at"] = now
                notify = True
        w["mobile"] = mobile if out.get("pass") else w.get("mobile")
        w["history"].append([now, status, out["ms"], summary, out.get("err")])
        while w["history"] and now - w["history"][0][0] > HISTORY_SECONDS:
            w["history"].pop(0)
        w["notes"] = build_notes(w, out, status, now)
        w["next_check_at"] = now + CHECK_EVERY
        w["busy"] = False
    print(f"[{w['id']}] {status:<11} {summary} ({out['ms']} ms) {w['host']}", flush=True)
    if notify:
        threading.Thread(target=send_notification, args=(w,), daemon=True).start()


def worker(n):
    checker = None
    if HAVE_BROWSER:
        try:
            checker = BrowserChecker()
            checker.ensure()
        except Exception as e:
            print(f"No se pudo abrir Chromium ({e}). Usando modo básico.", flush=True)
            checker = None
    while True:
        now = time.time()
        pick = None
        with lock:
            for w in watches.values():
                if w["active"] and now - w["last_view"] > WATCH_HOURS * 3600 and not w["preset"]:
                    w["active"] = False
                    w["summary"] = "En pausa: nadie abrió esta página por un buen tiempo. Ábrela para reanudar."
            due = [w for w in watches.values() if w["active"] and not w["busy"] and w["next_check_at"] <= now]
            if due:
                pick = min(due, key=lambda w: w["next_check_at"])
                pick["busy"] = True
        if pick:
            check_watch(pick, checker)
        else:
            time.sleep(1)


# ------------------------------------------------------------------ web

def page(name):
    return (ROOT / name).read_text(encoding="utf-8").replace("{{SITE_NAME}}", html.escape(SITE_NAME))


def public_view(w, now):
    keys = ("id", "url", "host", "status", "status_since", "summary", "steps", "last_ms", "attempts",
            "last_up_at", "up_window", "capture_t", "capture_live", "next_check_at", "topic", "active", "created")
    v = {k: w[k] for k in keys}
    v = json.loads(json.dumps(v))
    v["stats"] = stats_for(w, now)
    v["timeline"] = timeline_for(w)
    v["notes"] = w["notes"]
    v["minutes"] = minutes_for(w, now)
    v["recent"] = [[h[0], h[1], h[3]] for h in w["history"][-24:]]
    v["region"] = CHECKER_REGION
    v["site_country"] = site_country(w["host"])
    v["has_capture"] = w["capture"] is not None
    return v


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype, extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj), "application/json")

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/":
            return self._send(200, page("home.html"), "text/html; charset=utf-8")
        m = re.fullmatch(r"/v/([A-Za-z0-9]{4,16})/?", path)
        if m:
            if m.group(1) not in watches:
                return self._send(404, page("home.html"), "text/html; charset=utf-8")
            return self._send(200, page("watch.html"), "text/html; charset=utf-8")
        m = re.fullmatch(r"/api/estado/([A-Za-z0-9]{4,16})", path)
        if m:
            with lock:
                w = watches.get(m.group(1))
                if not w:
                    return self._json(404, {"error": "No encontramos esa página vigilada."})
                touch(w)
                now = time.time()
                v = public_view(w, now)
            v.update({"now": now, "check_every": CHECK_EVERY, "site_name": SITE_NAME,
                      "ntfy_url": f"{NTFY_SERVER}/{v['topic']}" if NTFY_PREFIX else "",
                      "mode": "navegador" if HAVE_BROWSER else "basico"})
            return self._json(200, v)
        m = re.fullmatch(r"/api/captura/([A-Za-z0-9]{4,16})\.jpg", path)
        if m:
            w = watches.get(m.group(1))
            if w and w["capture"]:
                return self._send(200, w["capture"], "image/jpeg")
            return self._send(404, "Sin captura", "text/plain")
        if path == "/api/ticker":
            with lock:
                ev = []
                for w in watches.values():
                    name = w["host"] if w["preset"] else "otra página"
                    for h in w["history"][-10:]:
                        ev.append([h[0], name, h[1], h[3]])
            ev.sort(key=lambda e: -e[0])
            return self._json(200, {"events": ev[:40]})
        if path == "/api/destacadas":
            with lock:
                items = [{"id": w["id"], "host": w["host"], "url": w["url"], "status": w["status"]}
                         for w in watches.values() if w["preset"]]
            return self._json(200, {"items": items, "site_name": SITE_NAME})
        if path == "/fx.js":
            return self._send(200, (ROOT / "fx.js").read_text(encoding="utf-8"), "text/javascript; charset=utf-8")
        if path == "/style.css":
            return self._send(200, (ROOT / "style.css").read_text(encoding="utf-8"), "text/css; charset=utf-8")
        if path == "/healthz":
            return self._send(200, "ok", "text/plain")
        self._send(404, "No encontrado", "text/plain")

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path != "/api/vigilar":
            return self._send(404, "No encontrado", "text/plain")
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 10000)
            body = json.loads(self.rfile.read(n) or b"{}")
            url = clean_url(str(body.get("url", "")))
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except Exception:
            return self._json(400, {"error": "No entendimos ese enlace."})
        with lock:
            if url in by_url:
                w = watches[by_url[url]]
                touch(w)
                if not w["active"]:
                    return self._json(429, {"error": "Ahora mismo estamos vigilando demasiadas páginas. Intenta en un rato."})
                return self._json(200, {"id": w["id"]})
            if active_count() >= MAX_WATCHES:
                return self._json(429, {"error": "Ahora mismo estamos vigilando demasiadas páginas. Intenta en un rato."})
            w = new_watch(url)
        save()
        print(f"Nuevo enlace vigilado: {url} -> /v/{w['id']}", flush=True)
        self._json(200, {"id": w["id"]})

    def log_message(self, *args):
        pass


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


if __name__ == "__main__":
    load()
    save()
    for i in range(WORKERS):
        threading.Thread(target=worker, args=(i,), daemon=True).start()
    def autosave():
        while True:
            time.sleep(300)
            save()
    threading.Thread(target=autosave, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SITE_NAME} listo ({'navegador real' if HAVE_BROWSER else 'modo básico: instala playwright para la prueba completa'})")
    print(f"En esta computadora:  http://localhost:{PORT}")
    ip = lan_ip()
    if ip:
        print(f"En tu celular (misma red Wi-Fi):  http://{ip}:{PORT}")
    print("Ctrl+C para detener.\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        save()
        print("\nDetenido.")
