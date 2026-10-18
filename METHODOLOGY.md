# Methodology

What is measured, how, and what the numbers can and cannot tell you.

## The question

A CLI tool, a cron job or a hook does one or a few HTTP requests and exits.
For such a process the cost of an HTTP client is not throughput; it is what
the client adds to **process start, memory and binary size**, and on HTTPS
what the TLS library does before the first byte (initialisation, loading
root certificates, the handshake). That is what this benchmark measures.
It says nothing about a long-running service doing thousands of requests per
second; use a throughput benchmark for that.

## What every client runs

Each client is a separate crate under `clients/` with the same 15-line
program: `GET <url> [-n count]` does `count` sequential requests on one client
object (one connection pool) and prints the status and the total body bytes.
Nothing is configured: each crate is used the way its README shows it, with
its **default features** plus the one feature needed for the variant (e.g.
`blocking`, or `native-tls` instead of the default `rustls`). The idea is to
measure what a CLI author gets by adding the dependency, not what an expert
could tune it down to.

Two rows have no HTTP library and set the floor:

- `empty` prints `0 0` and exits: the cost of a Rust process itself (exec,
  dynamic loader, libc and std initialisation).
- `std-tcp` writes the request line to a `std::net::TcpStream` and reads the
  `Content-Length` body: the cost of doing HTTP with no library at all. It
  cannot do HTTPS and exits with code 3 for an `https://` URL; the table
  shows `-` there.

All clients share one `[profile.release]`: `opt-level = 3`, fat LTO, one
codegen unit, `panic = "abort"`, stripped. That is what a CLI author ships.
Each client is built with its **own `cargo build -p`** invocation: building
the whole workspace at once would unify dependency features across clients,
and one client's TLS backend would end up in another's binary.

## The server

`bench-server` is a dependency-free HTTP/1.1 keep-alive server on
`127.0.0.1`: `/small` is 1 KiB, `/big` is 8 MiB. Requests never leave the
machine, so the numbers measure the client, not the network. The HTTPS
column is the one exception, see below.

## Columns

| column | how it is measured |
|---|---|
| binary KiB | size of the stripped release binary |
| crates | distinct crates in `cargo tree -e normal` for that client, minus the client itself |
| TLS | the TLS stack found by name in the dependency tree: `openssl-sys`, `rustls` with `ring` or `aws-lc-rs`, `rustls-ffi` for a libcurl built on rustls |
| clean build s | opt-in (`--build-time`): wall time of `cargo build --release -p` with an empty target directory, dependencies already downloaded; measured in a separate pass after all timings, so that the compile heat does not reach the next client |
| cold start ms | wall time from `fork` to `wait4` for one `GET /small`, median of `--runs` (default 20) runs; the chart shows the interquartile range as a whisker |
| max RSS KiB | `ru_maxrss` of that process from `wait4`, median |
| per request µs | (median wall time of a process doing `--inproc` (200) requests minus the cold start) divided by 199: the marginal cost of one more request on the same client, keep-alive if the client does it |
| 8 MiB download RSS KiB | `ru_maxrss` of one `GET /big`: whether the body is buffered, and how much the allocator keeps |
| PSS of N procs KiB | opt-in (`--parallel N`): N processes do 4000 requests each at the same time; the sum of their PSS (`/proc/<pid>/smaps_rollup`, shared pages divided among sharers) sampled every 50 ms, maximum over time. What N instances really cost together, which matters for shared libraries |
| HTTPS CPU ms | opt-in (`--https URL`): one GET of a real HTTPS URL per process, **CPU time** (user + sys) from `wait4`, median of `--runs / 2` runs. CPU time instead of wall time, so that network latency and the server are excluded; what remains is TLS initialisation, certificate loading, the handshake crypto and the request |
| HTTPS RSS KiB | `ru_maxrss` of that process |

Every raw sample is stored in the JSON under `results/`; the tables and
charts show medians.

## Why `measure` exists

The processes are launched through `measure`, a 40-line Rust binary that
does `fork`, `execvp`, `wait4` and prints wall time, CPU time and
`ru_maxrss`. Launching from Python directly would fork the interpreter,
and `ru_maxrss` of the child then includes the pre-exec copy of a Python
process (tens of MiB), hiding the 1 to 3 MiB the small clients actually use.
`measure` itself is a few hundred KiB.

## Noise

- Cold start is sensitive to CPU frequency scaling and to whatever else the
  machine does. The scripts do not pin CPUs or change governors; the
  interquartile range in the charts shows how stable a number was. For a
  clean run: idle machine, `performance` governor, AC power.
- The first run of each binary is a warm-up (page cache) and is discarded.
- The HTTPS column depends on the server (`example.com` by default) only
  through the handshake's cipher and certificate chain; its CPU time does
  not include waiting for the network.
- **GitHub Actions runners are shared hardware.** The CI run is useful for
  binary size, crate count, build time and the *order* of the timing
  columns; treat the millisecond values there as rough. The results are
  labelled with where they come from.

## Fairness notes

- Clients that open a new connection per request (no connection pool) show
  it in the per-request column, not by a different test.
- The `rustls` crypto provider matters more than the HTTP crate: `ring` and
  `aws-lc-rs` differ in binary size and, on some CPUs, in startup (aws-lc's
  CPU jitter entropy). Which one a client pulls in is in the TLS column.
- OpenSSL via `native-tls` loads the whole system CA bundle per process;
  libcurl on OpenSSL looks certificates up by hash. Both are "OpenSSL" in the
  TLS column but differ in the HTTPS column for that reason.
- A client built on the distro's shared `libcurl` carries that library's
  30-odd shared objects at start; the same libcurl built from source and
  linked statically (`curlite-rustls`, `isahc`) does not. Both are measured as
  the crate ships them.
- `extra/curlite-matrix` holds curlite builds that need a patched `curl`
  crate (rustls on ring, HTTP-only libcurl). They live in a separate
  workspace so that the `[patch]` cannot touch the main table, and are
  reported separately.

## Reproducing

```sh
# Ubuntu/Debian build dependencies for the clients that compile libcurl or
# link OpenSSL
sudo apt install build-essential cmake pkg-config libssl-dev libcurl4-openssl-dev
python3 -I bench.py --https https://example.com/ --label mymachine
python3 -I report.py results/mymachine.json
```

`report.py` writes the SVG charts to `docs/` and refreshes the result block
of the README whose label matches. Add a client by copying a directory under
`clients/`.
