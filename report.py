#!/usr/bin/env python3
"""Turns results/<label>.json into SVG bar charts (light and dark) under docs/
and Markdown tables, and refreshes the blocks between
`<!-- results:<label> start -->` and `<!-- results:<label> end -->` in README.md.

  python3 -I report.py [results/laptop.json ...] [--readme README.md] [--docs docs]

Without arguments every file in results/ is processed. No dependencies.
"""

import argparse
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Chart ink and surfaces, light / dark (one hue for the single series; the two
# floor rows without an HTTP library are context and stay gray).
THEME = {
    "light": {"surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
              "grid": "#e1e0d9", "axis": "#c3c2b7", "bar": "#2a78d6", "floor": "#b5b3ab"},
    "dark": {"surface": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781",
             "grid": "#2c2c2a", "axis": "#383835", "bar": "#3987e5", "floor": "#5c5b57"},
}
FLOORS = {"empty", "std-tcp"}
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# key, title, unit label, scale from the stored unit, decimals, IQR available
METRICS = [
    ("cold_ms", "Cold start: one 1 KiB GET over plain HTTP, process start to exit", "ms", 1, 1, True),
    ("cold_rss_kb", "Peak memory of that process (max RSS)", "MiB", 1 / 1024, 1, False),
    ("https_cpu_ms", "CPU time of one HTTPS GET per process (TLS setup, certificate roots)", "ms", 1, 0, True),
    ("binary_kb", "Stripped release binary", "MiB", 1 / 1024, 1, False),
    ("req_us", "Cost per request inside one process, keep-alive", "µs", 1, 0, False),
]


def value(row, key):
    v = row.get(key)
    if isinstance(v, dict):
        return v["median"], v["p25"], v["p75"]
    return (v, None, None) if v is not None else (None, None, None)


def nice_ticks(vmax, count=5):
    """Round tick step: 1, 2, 2.5, 5 × 10^k, so that ~count ticks cover vmax."""
    if vmax <= 0:
        return [0.0, 1.0]
    raw = vmax / count
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    n = math.ceil(vmax / step - 1e-9)
    return [i * step for i in range(n + 1)]


def fmt_num(v, decimals):
    return f"{v:,.{decimals}f}"


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def bar_chart(rows, key, title, unit, scale, decimals, iqr, mode, subtitle):
    """One horizontal bar chart as an SVG string; rows sorted ascending."""
    t = THEME[mode]
    data = []
    for r in rows:
        med, p25, p75 = value(r, key)
        if med is None:
            continue
        data.append((r["name"], med * scale, None if p25 is None else p25 * scale,
                     None if p75 is None else p75 * scale))
    data.sort(key=lambda d: d[1])
    if not data:
        return None
    name_w = max(len(d[0]) for d in data) * 6.6 + 12
    bar_h, slot = 16, 26
    left, right, top = 16 + name_w, 72, 58 + 16 * (len(subtitle) - 1)
    width = 760
    plot_w = width - left - right
    height = top + len(data) * slot + 36
    vmax = max(d[3] if d[3] is not None else d[1] for d in data)
    ticks = nice_ticks(vmax)
    vmax = ticks[-1] if ticks[-1] >= vmax else ticks[-1] + (ticks[1] - ticks[0])
    x = lambda v: left + v / vmax * plot_w

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" font-family=\'{FONT}\' font-size="12">',
           f'<rect width="{width}" height="{height}" fill="{t["surface"]}"/>',
           f'<text x="16" y="24" font-size="14" font-weight="600" fill="{t["ink"]}">{esc(title)}</text>']
    for i, line in enumerate(subtitle):
        out.append(f'<text x="16" y="{42 + 16 * i}" fill="{t["ink2"]}">{esc(line)}</text>')
    base_y = top + len(data) * slot
    for tick in ticks:
        tx = x(tick)
        label = fmt_num(tick, 2 if tick % 1 else 0) + (f" {unit}" if tick == ticks[-1] else "")
        out.append(f'<line x1="{tx:.1f}" y1="{top - 6}" x2="{tx:.1f}" y2="{base_y}" stroke="{t["grid"]}" stroke-width="1"/>')
        out.append(f'<text x="{tx:.1f}" y="{base_y + 16}" text-anchor="middle" fill="{t["muted"]}" '
                   f'font-variant-numeric="tabular-nums">{label}</text>')
    out.append(f'<line x1="{left}" y1="{top - 6}" x2="{left}" y2="{base_y}" stroke="{t["axis"]}" stroke-width="1"/>')
    for i, (name, med, p25, p75) in enumerate(data):
        y = top + i * slot + (slot - bar_h) / 2
        color = t["floor"] if name in FLOORS else t["bar"]
        w = max(x(med) - left, 1)
        r = min(4, w / 2)
        # square at the baseline, 4px rounded data end
        out.append(f'<path d="M{left},{y} h{w - r:.1f} a{r},{r} 0 0 1 {r},{r} v{bar_h - 2 * r} '
                   f'a{r},{r} 0 0 1 -{r},{r} h-{w - r:.1f} z" fill="{color}"/>')
        out.append(f'<text x="{left - 8}" y="{y + bar_h / 2 + 4}" text-anchor="end" fill="{t["ink"]}">{esc(name)}</text>')
        label_x = x(med) + 6
        if iqr and p25 is not None and p75 is not None and p75 > p25:
            out.append(f'<line x1="{x(p25):.1f}" y1="{y + bar_h / 2}" x2="{x(p75):.1f}" y2="{y + bar_h / 2}" '
                       f'stroke="{t["ink2"]}" stroke-width="1"/>')
            for px in (p25, p75):
                out.append(f'<line x1="{x(px):.1f}" y1="{y + bar_h / 2 - 3}" x2="{x(px):.1f}" y2="{y + bar_h / 2 + 3}" '
                           f'stroke="{t["ink2"]}" stroke-width="1"/>')
            label_x = max(label_x, x(p75) + 6)
        out.append(f'<text x="{label_x:.1f}" y="{y + bar_h / 2 + 4}" fill="{t["ink2"]}" '
                   f'font-variant-numeric="tabular-nums">{fmt_num(med, decimals)}</text>')
    out.append("</svg>\n")
    return "\n".join(out)


def fmt(v, digits=0):
    if v is None:
        return "-"
    if isinstance(v, dict):
        v = v["median"]
    return f"{v:,.{digits}f}"


def md_table(result):
    rows = result["clients"]
    meta = result["meta"]
    has_https = any(r.get("https_cpu_ms") for r in rows)
    has_build = any(r.get("build_s") is not None for r in rows)
    has_pss = any(r.get("pss_total_kb") is not None for r in rows)
    cols = ["client", "TLS", "crates", "binary KiB"]
    if has_build:
        cols.append("clean build s")
    cols += ["cold start ms", "max RSS KiB", "per request µs", "8 MiB download RSS KiB"]
    if has_pss:
        cols += [f"PSS of {meta['parallel']} procs KiB"]
    if has_https:
        cols += ["HTTPS CPU ms", "HTTPS RSS KiB"]
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in sorted(rows, key=lambda r: (r.get("cold_ms") or {}).get("median", float("inf"))):
        cells = [f"`{r['name']}`", r["tls"], fmt(r["crates"]), fmt(r["binary_kb"])]
        if has_build:
            cells.append(fmt(r["build_s"]))
        cells += [fmt(r["cold_ms"], 1), fmt(r["cold_rss_kb"]), fmt(r["req_us"]), fmt(r["big_rss_kb"])]
        if has_pss:
            cells.append(fmt(r["pss_total_kb"]))
        if has_https:
            if r["https_cpu_ms"] is None and any("https" in e for e in r.get("errors", [])):
                cells += ["fails", "fails"]
            else:
                cells += [fmt(r["https_cpu_ms"]), fmt(r["https_rss_kb"])]
        out.append("| " + " | ".join(cells) + " |")
    failed = [r["name"] for r in rows if r.get("errors")]
    if failed:
        out.append("\n`fails`: the request errored in every run (" + ", ".join(f"`{n}`" for n in failed)
                   + "); the message is in the JSON under `errors`.")
    return "\n".join(out)


def picture(label, key, alt):
    return (f'<picture>\n  <source media="(prefers-color-scheme: dark)" srcset="docs/{label}-{key}-dark.svg">\n'
            f'  <img alt="{esc(alt)}" src="docs/{label}-{key}-light.svg">\n</picture>')


def render(result, docs):
    meta = result["meta"]
    label = meta["label"]
    h = meta["host"]
    cpu = re.sub(r"\((R|TM)\)|\d+th Gen |CPU @.*", "", h.get("cpu_model") or h["arch"]).strip()
    where = f"{cpu}, {h.get('distro') or h['os']} {h['kernel']}"
    if meta.get("ci"):
        where += " (GitHub Actions runner: shared hardware, treat timings as rough)"
    method = f"{meta['date']}, median of {meta['runs']} runs"
    charts = {}
    for key, title, unit, scale, decimals, iqr in METRICS:
        sub = [where, method + (", bar = median, whisker = interquartile range" if iqr else "")]
        for mode in ("light", "dark"):
            svg = bar_chart(result["clients"], key, title, unit, scale, decimals, iqr, mode, sub)
            if svg:
                (docs / f"{label}-{key}-{mode}.svg").write_text(svg)
                charts[key] = title
    versions = "; ".join(f"{r['name']}: {r['deps']}" for r in result["clients"] if r.get("deps"))
    block = [md_table(result), "",
             f"{where}; {meta['date']}; {meta['rustc']}; runs={meta['runs']}, "
             f"in-process requests={meta['inproc']}" + (f"; HTTPS against `{meta['https_url']}`" if meta.get("https_url") else "")
             + (f"; libcurl {h['libcurl']}" if h.get("libcurl") else "") + ".", "",
             "<details><summary>Crate versions</summary>", "", versions, "", "</details>"]
    return charts, "\n".join(block)


def refresh_readme(readme, label, body):
    start, end = f"<!-- results:{label} start -->", f"<!-- results:{label} end -->"
    text = readme.read_text()
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        return False
    readme.write_text(pattern.sub(lambda _: f"{start}\n{body}\n{end}", text))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="*", type=Path)
    ap.add_argument("--readme", type=Path, default=ROOT / "README.md")
    ap.add_argument("--docs", type=Path, default=ROOT / "docs")
    args = ap.parse_args()
    files = args.results or sorted((ROOT / "results").glob("*.json"))
    args.docs.mkdir(exist_ok=True)
    for f in files:
        result = json.loads(f.read_text())
        label = result["meta"]["label"]
        charts, body = render(result, args.docs)
        updated = args.readme.exists() and refresh_readme(args.readme, label, body)
        print(f"{f.name}: {len(charts)} charts" + (", README refreshed" if updated else ""))
        for key in charts:
            print("  " + picture(label, key, charts[key]).replace("\n", " "))


if __name__ == "__main__":
    main()
