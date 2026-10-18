#!/usr/bin/env python3
"""Measures every fetch-* client against bench-server, writes one JSON file
and prints a Markdown table. Run from the repository root.

  python3 -I bench.py [--runs 20] [--inproc 200] [--build-time] [--only a,b]
                      [--https https://example.com/] [--no-build]
                      [--parallel 20] [--workspace extra/curlite-matrix]
                      [--label laptop] [--out results]

Builds each client separately first (so that dependency features are not
unified across clients), unless --no-build.

Columns: stripped binary size, crates in the dependency tree, TLS stack found
in that tree, clean build time (opt-in, slow), cold start (process start to
exit for one 1 KiB GET: median wall time with the interquartile range, and
max RSS), per-request cost inside one process (200 keep-alive GETs), and max
RSS for one 8 MiB download. With --https, one GET of that URL per process:
CPU time (user+sys, network latency excluded) and max RSS, which is where TLS
setup and root certificate loading show up. With --parallel N, N processes
run 1 KiB GETs at the same time and the sum of their PSS (proportional set
size, shared pages divided among sharers) is sampled from /proc: what N
instances really cost together.

A client that cannot do a request exits with code 3 ("unsupported"); its
cell is empty. The JSON keeps every raw sample, the table shows medians.
"""

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVER_ADDR = "127.0.0.1:18080"
UNSUPPORTED = 3


class Workspace:
    """A cargo workspace with a `clients/` directory of fetch-* packages."""

    def __init__(self, path):
        self.path = (ROOT / path).resolve()
        self.target = self.path / "target" / "release"

    def clients(self, only):
        names = sorted(p.name for p in (self.path / "clients").iterdir() if p.is_dir())
        return [n for n in names if not only or n in only]

    def cargo(self, *args, **kw):
        return subprocess.run(["cargo", *args], cwd=self.path, capture_output=True, text=True, **kw)

    def build(self, packages):
        """One cargo invocation per package: building the whole workspace at
        once unifies dependency features across clients (one client's rustls
        backend would end up in another's binary)."""
        for pkg in packages:
            print(f"  building {pkg}", file=sys.stderr)
            r = self.cargo("build", "--release", "-p", pkg)
            if r.returncode != 0:
                sys.exit(f"build of {pkg} failed:\n{r.stderr[-3000:]}")

    def tree(self, name, *args):
        r = self.cargo("tree", "-p", f"fetch-{name}", "--edges", "normal", "--prefix", "none", *args)
        return [l.split() for l in r.stdout.splitlines() if l.strip()] if r.returncode == 0 else None

    def crate_count(self, name):
        tree = self.tree(name)
        return None if tree is None else len({l[0] for l in tree}) - 1

    def direct_deps(self, name):
        """`ureq 3.4.2`-style names of the client's direct dependencies."""
        tree = self.tree(name, "--depth", "1")
        if tree is None:
            return ""
        return ", ".join(f"{l[0]} {l[1].lstrip('v')}" for l in tree[1:] if len(l) > 1)

    def tls(self, name):
        """The TLS stack in the dependency tree, from crate names."""
        crates = {l[0] for l in self.tree(name) or []}
        if "openssl-sys" in crates:
            via = " (native-tls)" if "native-tls" in crates else ""
            return "OpenSSL" + via
        if "rustls" in crates or "rustls-ffi" in crates:
            if "aws-lc-rs" in crates:
                return "rustls / aws-lc"
            if "ring" in crates:
                return "rustls / ring"
            return "rustls"
        if "curl-sys" in crates:
            return "libcurl's"
        return "none"

    def clean_build_seconds(self, name):
        target = self.path / "target" / f"clean-{name}"
        shutil.rmtree(target, ignore_errors=True)
        env = dict(os.environ, CARGO_TARGET_DIR=str(target))
        start = time.perf_counter()
        r = self.cargo("build", "--release", "-p", f"fetch-{name}", env=env)
        seconds = time.perf_counter() - start
        shutil.rmtree(target, ignore_errors=True)
        return seconds if r.returncode == 0 else None


MAIN = Workspace(".")


def run_measured(cmd):
    """(wall seconds, max RSS KiB, CPU seconds) of one child process, or None
    if the client reports the request as unsupported.

    Python forks itself before exec, and ru_maxrss covers that pre-exec copy
    of the interpreter, so the child is launched through the tiny `measure`
    binary, which reports what `wait4` saw.
    """
    proc = subprocess.run(
        [MAIN.target / "measure", *map(str, cmd)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    if proc.returncode == UNSUPPORTED:
        return None
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd} exited with {proc.returncode}: {proc.stderr}")
    wall_us, cpu_us, rss = proc.stderr.strip().splitlines()[-1].split()
    return int(wall_us) / 1e6, int(rss), int(cpu_us) / 1e6


def samples(cmd, runs, errors):
    """Lists of wall seconds, RSS KiB and CPU seconds over `runs`, or None if
    the client does not support the request or fails (noted in `errors`)."""
    walls, rss, cpu = [], [], []
    for _ in range(runs):
        try:
            m = run_measured(cmd)
        except RuntimeError as e:
            errors.append(str(e))
            print(f"    FAILED: {e}", file=sys.stderr)
            return None
        if m is None:
            return None
        walls.append(m[0])
        rss.append(m[1])
        cpu.append(m[2])
    return walls, rss, cpu


def quartiles(values, scale=1.0):
    """{median, p25, p75, samples} of `values` times `scale`."""
    v = sorted(x * scale for x in values)
    q = statistics.quantiles(v, n=4) if len(v) >= 2 else [v[0], v[0], v[0]]
    return {"median": statistics.median(v), "p25": q[0], "p75": q[2], "samples": v}


def parallel_pss(binary, url, count, requests=4000):
    """Max over time of the summed PSS of `count` concurrent processes, KiB."""
    procs = [subprocess.Popen([binary, url, "-n", str(requests)], stdout=subprocess.DEVNULL)
             for _ in range(count)]
    peak = 0
    while any(p.poll() is None for p in procs):
        total = 0
        for p in procs:
            try:
                with open(f"/proc/{p.pid}/smaps_rollup") as f:
                    for line in f:
                        if line.startswith("Pss:"):
                            total += int(line.split()[1])
                            break
            except OSError:
                pass
        peak = max(peak, total)
        time.sleep(0.05)
    for p in procs:
        if p.returncode not in (0, UNSUPPORTED):
            raise RuntimeError(f"{binary} exited with {p.returncode} in parallel run")
    return peak


def measure_client(ws, name, binary, base, args):
    """One result row (dict) for a client binary."""
    print(f"  measuring {name}", file=sys.stderr)
    small = f"{base}/small"
    errors = []
    # warm the page cache so the first run is not a disk read
    samples([binary, small], 1, errors)
    if args.https:
        samples([binary, args.https], 1, [])
    few = max(3, args.runs // 4)
    cold = samples([binary, small], args.runs, errors)
    many = samples([binary, small, "-n", str(args.inproc)], few, errors)
    big = samples([binary, f"{base}/big"], few, errors)
    row = {
        "name": name,
        "deps": ws.direct_deps(name),
        "crates": ws.crate_count(name),
        "tls": ws.tls(name),
        "binary_kb": binary.stat().st_size // 1024,
        "build_s": None,  # filled in by the build-time pass after all measurements
        "cold_ms": None if cold is None else quartiles(cold[0], 1e3),
        "cold_rss_kb": None if cold is None else statistics.median(cold[1]),
        "req_us": None,
        "big_rss_kb": None if big is None else statistics.median(big[1]),
        "pss_total_kb": None,
        "https_cpu_ms": None,
        "https_wall_ms": None,
        "https_rss_kb": None,
        "errors": errors,
    }
    if cold is not None and many is not None:
        per_req = (statistics.median(many[0]) - statistics.median(cold[0])) / (args.inproc - 1) * 1e6
        row["req_us"] = max(per_req, 0.0)
    if args.parallel and cold is not None:
        row["pss_total_kb"] = parallel_pss(binary, small, args.parallel)
    if args.https:
        https = samples([binary, args.https], max(5, args.runs // 2), errors)
        if https is not None:
            row["https_wall_ms"] = quartiles(https[0], 1e3)
            row["https_rss_kb"] = statistics.median(https[1])
            row["https_cpu_ms"] = quartiles(https[2], 1e3)
    if row["cold_ms"]:
        print(f"    {row['cold_ms']['median']:.1f} ms cold, {row['cold_rss_kb']:.0f} KiB", file=sys.stderr)
    return row


def host_info():
    cpu_model = ""
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    cpu_model = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    try:
        distro = platform.freedesktop_os_release().get("PRETTY_NAME", "")
    except OSError:
        distro = ""
    u = os.uname()
    curl = subprocess.run(["curl-config", "--version"], capture_output=True, text=True)
    return {
        "os": u.sysname, "kernel": u.release, "arch": u.machine, "cpus": os.cpu_count(),
        "cpu_model": cpu_model, "distro": distro,
        "libcurl": curl.stdout.strip() if curl.returncode == 0 else "",
    }


def fmt(v, digits=0):
    if v is None:
        return "-"
    if isinstance(v, dict):
        v = v["median"]
    return f"{v:.{digits}f}"


def table(rows, args):
    cols = ["client", "TLS", "binary KiB", "crates"]
    if args.build_time:
        cols.append("clean build s")
    cols += ["cold start ms", "max RSS KiB", "per request µs", "8 MiB download RSS KiB"]
    if args.parallel:
        cols += [f"PSS of {args.parallel} procs KiB", "PSS per proc KiB"]
    if args.https:
        cols += ["HTTPS CPU ms", "HTTPS RSS KiB"]
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in sorted(rows, key=lambda r: (r["cold_ms"] or {}).get("median", float("inf"))):
        cells = [r["name"], r["tls"], str(r["binary_kb"]), fmt(r["crates"])]
        if args.build_time:
            cells.append(fmt(r["build_s"]))
        cells += [fmt(r["cold_ms"], 1), fmt(r["cold_rss_kb"]), fmt(r["req_us"]), fmt(r["big_rss_kb"])]
        if args.parallel:
            pss = r["pss_total_kb"]
            cells += [fmt(pss), fmt(None if pss is None else pss / args.parallel)]
        if args.https:
            cells += [fmt(r["https_cpu_ms"]), fmt(r["https_rss_kb"])]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--inproc", type=int, default=200)
    ap.add_argument("--build-time", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--https", default="", help="URL for one HTTPS GET per process")
    ap.add_argument("--no-build", action="store_true", help="use the binaries as they are")
    ap.add_argument("--parallel", type=int, default=0, help="N concurrent processes for a PSS sum")
    ap.add_argument("--workspace", action="append", default=[],
                    help="another workspace with clients/ to include (e.g. extra/curlite-matrix)")
    ap.add_argument("--extra", action="append", default=[],
                    help="label=path of an extra binary to measure (e.g. a lean build)")
    ap.add_argument("--label", default=platform.node() or "host", help="name of the result file")
    ap.add_argument("--out", default="results", help="directory for the JSON result")
    args = ap.parse_args()
    only = {s for s in args.only.split(",") if s}

    workspaces = [MAIN, *(Workspace(w) for w in args.workspace)]
    binaries = {}  # name -> (workspace, path)
    for ws in workspaces:
        names = ws.clients(only)
        if not args.no_build:
            core = ["bench-server", "measure"] if ws is MAIN else []
            ws.build([*core, *(f"fetch-{n}" for n in names)])
        for n in names:
            if (ws.target / f"fetch-{n}").exists():
                binaries[n] = (ws, ws.target / f"fetch-{n}")
    for extra in args.extra:
        label, _, path = extra.partition("=")
        binaries[label] = (MAIN, Path(path).resolve())
    if not binaries:
        sys.exit("no built clients found")

    server = subprocess.Popen([MAIN.target / "bench-server", SERVER_ADDR], stderr=subprocess.DEVNULL)
    time.sleep(0.3)
    rows = []
    try:
        for name, (ws, binary) in binaries.items():
            rows.append(measure_client(ws, name, binary, f"http://{SERVER_ADDR}", args))
    finally:
        server.kill()
    if args.build_time:
        # after every timing: a clean release build with LTO keeps all cores
        # busy for minutes, and a client measured right after one runs on a
        # hot, throttled CPU with cold caches (seen: 93 ms instead of 33 ms)
        for row in rows:
            ws, _ = binaries[row["name"]]
            print(f"  clean build of {row['name']}", file=sys.stderr)
            row["build_s"] = ws.clean_build_seconds(row["name"])

    rustc = subprocess.run(["rustc", "--version"], capture_output=True, text=True).stdout.strip()
    git = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    result = {
        "meta": {
            "label": args.label, "date": date.today().isoformat(), "host": host_info(), "rustc": rustc,
            "commit": git, "runs": args.runs, "inproc": args.inproc, "https_url": args.https,
            "parallel": args.parallel, "ci": bool(os.environ.get("GITHUB_ACTIONS")),
        },
        "clients": rows,
    }
    out_dir = ROOT / args.out
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{args.label}.json"
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(table(rows, args))
    h = result["meta"]["host"]
    print(f"\n{h['os']} {h['kernel']} {h['arch']}, {h['cpus']} CPUs, {h['cpu_model']}, {rustc}; "
          f"runs={args.runs}, in-process requests={args.inproc}; written to {out}")


if __name__ == "__main__":
    main()
