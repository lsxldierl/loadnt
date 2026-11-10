# loadnt

Watches a website that keeps failing to load and notifies you when it works.

I made this for the Ministerio de Desarrollo Humano survey site in Ecuador, which times out, resets connections or loads half broken most of the day. It works with any URL.

UI is in Spanish.

## What it does

- Opens the page in headless Chromium every 30 seconds
- Only marks it as up if the page actually renders: content is there, CSS/JS loaded, buttons exist and a "Siguiente"/"Next" click goes somewhere
- Never clicks submit, pay, delete or anything similar
- Keeps the browser cache between checks, so on flaky servers each check gets further
- Takes a screenshot each check
- Also tests the page at phone size
- Sends a push notification through [ntfy](https://ntfy.sh) when it comes back up

Each watched URL gets a page at `/v/<id>` with the current status, last screenshot, uptime for the last hour and a timeline. The visitor's browser also pings the site, so you can tell if it's down for everyone or only blocked from the server's location.

It also detects expired certificates, captchas, "access denied" pages, maintenance pages, cookie walls and redirects, and shows a short explanation for each.

## Run locally

```
pip install -r requirements.txt
python -m playwright install chromium
python app.py
```

Open http://localhost:8000.

On Windows you can just run `start-windows.bat`.

## Deploy on Render

There's a `render.yaml`, so New → Blueprint → pick this repo works.

The free instance sleeps after 15 min without traffic. Point an uptime monitor at `/healthz` to keep it awake. It has 512 MB of RAM, so keep `MAX_WATCHES` low.

Some sites only accept visitors from their own country. Render has no South America region, so for those you need to run it on a machine in that country or set `CHECK_PROXY`.

## Config

All optional, set as environment variables.

```
SITE_NAME       name shown on the site (default: Load'nt?)
PRESET_URLS     URLs always watched, space separated
MAX_WATCHES     max URLs watched at once (12)
WATCH_HOURS     pause a URL nobody has opened for this many hours (24)
CHECK_EVERY     seconds between checks (30)
TIMEOUT         seconds to wait for the site (45)
CLICK_EVERY     seconds between button tests while up (600)
WORKERS         parallel browsers, ~200 MB each (1)
NTFY_SERVER     ntfy server (https://ntfy.sh)
NTFY_PREFIX     ntfy topic prefix, empty to disable (loadnt)
CHECKER_REGION  where the checker runs, shown in messages (Estados Unidos)
CHECK_PROXY     proxy for checks, http://user:pass@host:port
DATA_DIR        where watched URLs are saved (./data)
PORT            (8000)
```

## Ideas

- Checker nodes in other countries that pull jobs from the main server
- English UI

PRs welcome.

## License

MIT
