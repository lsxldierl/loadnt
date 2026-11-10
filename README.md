# Load'nt?

Keeps checking a website that barely loads and tells you when it actually works.

Built for slow, overloaded sites like government surveys and appointment pages, which time out, reset the connection or load half-broken most of the time. Paste a link, and Load'nt? opens it in a real browser every 30 seconds. It sends a notification to your phone when the page loads completely and its buttons respond.

The site's interface is in Spanish.

## How it works

Each link gets its own page at `/v/<id>` showing:

- current status in plain words
- a live screenshot from the last check
- how long it has been down, when it last worked and for how long, and how often it worked in the last hour
- a timeline of when it was up and down
- a minute-by-minute strip of the last hour

A check only counts as "working" if all of these pass:

1. the server answers
2. the page has real content (not blank, not an error page)
3. its CSS and JS load
4. something is actually visible on screen
5. there are buttons that can be pressed
6. clicking a safe button ("Siguiente", "Comenzar", "Next") does something

It never clicks anything that could submit, pay, buy or delete. The click test runs at most once every 10 minutes per link.

The checker keeps its browser cache between checks, like a real visitor does. On sites that drop half their files, each check gets further than the last.

## Diagnosis

When a page fails, the watch page tries to explain why. It only shows a note when there's something useful to say:

- **Visitor's own connection.** The visitor's browser also checks whether the site answers. Compared with the server's result, this tells apart "down for everyone", "blocks foreign or datacenter traffic" and "only failing on your network".
- **Country blocks.** The site's country comes from its domain (`.ec`, `.gov.co`, `.gob.mx`…) and the visitor's from their time zone.
- **Other causes:** expired or invalid certificates, captchas and bot checks, "access denied" pages, maintenance pages, cookie requirements, expired sessions, redirects to another domain, very slow responses, and pages that break on phones.

## Notifications

- **ntfy** (free, no account): every link gets its own topic. Install the ntfy app, subscribe to the topic shown on the page, and you get a push notification even with your phone locked.
- **In the page:** a sound, vibration (Android) and browser notification while the tab is open.
- **Share link:** anyone with the link sees the same live status, and there's a WhatsApp share button.

## Running it

### On Render (free)

1. Fork or push this repo to GitHub.
2. On render.com: **New → Blueprint**, then pick the repo. `render.yaml` sets everything up.
3. Free instances sleep after 15 minutes without traffic, and nothing gets checked while asleep. Point a free uptime monitor (e.g. UptimeRobot) at `/healthz` every 5 minutes.

The free plan has 512 MB of RAM and runs a full Chromium. Keep `MAX_WATCHES` low or use a paid instance. The list of watched links resets on restart; links in `PRESET_URLS` always come back.

### On Windows

Install Python (tick "Add Python to PATH"), then run `start-windows.bat`. The first run downloads Chromium. The dashboard is at `http://localhost:8000`, and the console prints an address for phones on the same Wi-Fi.

### Anywhere else

```
pip install -r requirements.txt
python -m playwright install chromium
python app.py
```

Without Playwright it falls back to plain HTTP checks (server and content only).

### Checking from another country

Checks come from wherever the app runs. Render has no South America region. If a site only accepts visitors from its own country, run the app on a machine there, or route checks through a proxy with `CHECK_PROXY`.

## Configuration

| Variable | Default | |
|---|---|---|
| `SITE_NAME` | `Load'nt?` | Name shown on the site |
| `PRESET_URLS` | | Links that are always watched and listed on the home page (space-separated) |
| `MAX_WATCHES` | `12` | Links watched at once |
| `WATCH_HOURS` | `24` | Pause a link when nobody has opened its page for this long |
| `CHECK_EVERY` | `30` | Seconds between checks of each link |
| `TIMEOUT` | `45` | Seconds to wait for a response |
| `CLICK_EVERY` | `600` | How often the button test repeats while a page is up |
| `WORKERS` | `1` | Parallel browsers (about 200 MB each) |
| `NTFY_SERVER` | `https://ntfy.sh` | ntfy server |
| `NTFY_PREFIX` | `loadnt` | Prefix for topic names; empty disables ntfy |
| `CHECKER_REGION` | `Estados Unidos` | Where checks run from, used in the explanations |
| `CHECK_PROXY` | | Proxy for checks, e.g. `http://user:pass@host:port` |
| `DATA_DIR` | `./data` | Where the list of links is saved |
| `PORT` | `8000` | |

Keep proxy credentials in your host's environment settings, not in the repo.

## Project layout

```
app.py        server, checker, diagnosis, API
home.html     paste-a-link page
watch.html    live status page for one link
style.css     shared styles
fx.js         animations (all optional; respects reduced motion)
Dockerfile    image with Python + Chromium (used by Render)
render.yaml   Render blueprint
```

## Contributing

Issues and pull requests are welcome. Things that would help most:

- **Checker nodes in other countries.** Volunteers could run a small agent that pulls jobs and reports results, so a site can be checked from inside its own country.
- **Translations of the interface.**
- **More block and error-page patterns** for sites that fail in unusual ways.

## License

MIT
