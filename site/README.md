# omnigauge.dev

One self-contained file. No build step, no framework, no external requests at
render time — a tool whose claim is that it makes no network calls should not
have a homepage that phones out.

## What it is

A working DOS/Turbo Vision terminal. Pull-down menus, F1–F10, a command line
with history and tab completion, a modal dialog, a CRT power-on, meters that
fill, a sparkline, and a screensaver that counts its own bounces.

## The one rule

The grid is **78 columns at every screen size**. `fit()` measures the real glyph
advance in the real font and solves for the font size, because the advance of a
monospace glyph is not a constant across platforms — assuming `.6em` puts the
right-hand border off the edge of a phone. A phone renders identically to a 5K
display; only the type size changes.

Anything that draws a panel goes through `head()` / `row()` / `foot()`, which
share one width table. Every framed line must measure the same. This has been
got wrong three times: twice as arithmetic, once as font fallback where the
character counts were identical and only the rendered glyphs differed. **Assert
rendered widths; do not eyeball them.**

Avoid rare glyphs. Eighth-block partials and em dashes substitute from a
fallback face with a different advance and silently ragged the layout.

## Deploy

    scp site/index.html origin:/var/www/omnigauge/index.html

Served by nginx on the origin box behind Cloudflare (proxied A records).
**One home** — the site briefly had two live copies (Pages and the origin)
with no way to tell which was served, and the split cost a build nobody
could locate. The Pages project is deleted so it cannot silently re-take
the hostname. Whatever changes in `site/` gets scp'd to the origin and then
verified **through the domain**: `/` byte-identical to the repo file,
`/robots.txt` 200 `text/plain` with GET and HEAD agreeing, an unknown path
404, direct-IP TLS refused.

The nginx vhost carries the security headers and the www → apex 301, and
`try_files … =404` keeps crawler paths honest — under Pages, every unknown
path (robots.txt included) answered 200 with the page. The vhost also
enforces a Cloudflare-only origin gate, and its certificate is deliberately
separate from every other domain on the box.

`robots.txt`, `sitemap.xml` and `llms.txt` deploy alongside `index.html`.
The mail records on the zone (MX, SPF, DMARC, the Apple TXT and the DKIM
CNAME) predate the site and stay untouched by any site work.
