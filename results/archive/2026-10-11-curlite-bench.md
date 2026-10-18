# Archived run: curlite-bench, 2026-10-10/11

These tables come from this benchmark's predecessor (`curlite-bench`), with
the client set and crate versions of that time (reqwest 0.12, isahc 1, minreq
2, attohttpc 0.29, curlite from a checkout) and without the floor rows. They
are kept because the ARM board run has not been repeated with the current
client set yet. Columns are as in the current README; the `curlite-*` rows
beyond `curlite` and `curlite-rustls` are the builds now in `extra/curlite-matrix`.

## x86_64 laptop

x86_64 laptop, Linux, 12 CPUs, 2026-10-11. `runs=20`, 300 in-process
requests, HTTPS against example.com (CPU time, so network latency is
excluded). minreq and attohttpc open a new connection per request, hence
their per-request cost. `curlite` is the default build on the distro libcurl
(Ubuntu's 8.5 with OpenSSL 3 and its 30-odd shared libraries); the other
`curlite-*` rows are the static builds from the curlite README, `curlite-ring-min`
the `minimal` HTTP(S)-only libcurl on ring.

| client | binary KiB | crates | cold start ms | max RSS KiB | per request µs | 8 MiB download RSS KiB | HTTPS CPU ms | HTTPS RSS KiB |
|---|---|---|---|---|---|---|---|---|
| minreq | 1318 | 11 | 3.9 | 2194 | 1674 | 10156 | 10 | 3396 |
| attohttpc | 4033 | 48 | 4 | 2800 | 1177 | 10920 | 33 | 4798 |
| ureq-rustls | 1876 | 22 | 4 | 2650 | 24 | 10904 | 10 | 4164 |
| curlite-rustls-ring | 2363 | 36 | 4.1 | 3056 | 30 | 11220 | 14 | 4444 |
| curlite-ring-min | 2247 | 36 | 4.2 | 3044 | 37 | 11100 | 14 | 4342 |
| ureq-native | 827 | 30 | 4.3 | 4214 | 42 | 12436 | 47 | 10486 |
| curlite-rustls | 4406 | 35 | 4.4 | 3710 | 19 | 11364 | 33 | 5844 |
| reqwest-rustls | 2495 | 85 | 4.7 | 3310 | 49 | 11712 | 12 | 4364 |
| curlite-static-ssl | 6657 | 20 | 5.5 | 6034 | 24 | 14212 | 20 | 8400 |
| curlite-static | 1106 | 20 | 6 | 6352 | 48 | 14312 | 21 | 8340 |
| curlite | 431 | 20 | 8.4 | 10548 | 30 | 18164 | 23 | 12926 |
| isahc | 810 | 73 | 9.3 | 11346 | 50 | 19384 | 36 | 14060 |
| reqwest-native | 1238 | 85 | 33.3 | 9112 | 30 | 17716 | 42 | 9678 |

What the numbers say: the TLS library and the linking decide, not the HTTP
client. The distro libcurl costs 8 ms and 10 MiB before the first byte, a
static libcurl on rustls with ring is at ureq's 4 ms and within 0.4 MiB of
it. Every OpenSSL-based client pays for OpenSSL 3's initialisation; among
those, curlite is the cheapest on HTTPS because it lets OpenSSL look CA
certificates up by hash instead of parsing the bundle. On x86 the `minimal`
libcurl buys nothing over the plain ring build.

### Where the per-request time goes

callgrind on the curlite client against the distro libcurl, 3000 requests on
one keep-alive connection (2026-10-11): about 94 000 instructions per
request, of which three quarters are inside libcurl itself (easy handle
reset, the twenty setopts, URL parsing, connection cache lookup and the
proxy environment check, which calls `getenv` several times per request).
malloc and free take another 13 %. curlite's own code is below 5 %. The gap
to ureq (22 against 15 µs on this laptop) is libcurl's per-request setup,
not something the wrapper can remove.

## Orange Pi Zero 2W (aarch64)

Orange Pi Zero 2W (Allwinner H618, 4x Cortex-A53 at 1.4 GHz, 4 GB), Armbian
Debian 13, `performance` governor, 2026-10-10. Same columns as above plus the
summed PSS of 10 concurrent processes (what shared pages really cost). Rows
without a crate count are extra builds of the curlite client:
`curlite-lean-musl-ring` is `build-lean.sh` (static musl, no PIE, rustls on
ring), `curlite-lean-musl-awslc` the same with `build-lean.sh fetch-curlite-rustls`
(aws-lc without jitter entropy), `curlite-nopie-ring` ring on glibc without
PIE, `curlite-awslc-nojit` the `rustls` feature on glibc built with
`AWS_LC_SYS_NO_JITTER_ENTROPY=1`.

| client | binary KiB | crates | cold start ms | max RSS KiB | per request µs | 8 MiB download RSS KiB | PSS of 10 procs KiB | PSS per proc KiB | HTTPS CPU ms | HTTPS RSS KiB |
|---|---|---|---|---|---|---|---|---|---|---|
| curlite-lean-musl-ring | 2054 | - | **9.4** | **1096** | 185 | 9288 | **1972** | **197** | 28 | **1996** |
| curlite-lean-musl-awslc | 3334 | - | 9.6 | 1400 | 180 | 9592 | 2261 | 226 | **18** | 2808 |
| minreq | 1156 | 11 | 10.1 | 2200 | 6726 | 10260 | 2964 | 296 | 20 | 2788 |
| ureq-rustls | 1604 | 22 | 10.5 | 2404 | 106 | 10724 | 5675 | 567 | 21 | 3748 |
| attohttpc | 3012 | 48 | 10.9 | 2468 | 6810 | 10652 | 3748 | 374 | 480 | 4260 |
| curlite-nopie-ring | 1926 | - | 11.1 | 2600 | 170 | 10792 | 3290 | 329 | 28 | 3664 |
| curlite-rustls-ring | 2118 | 36 | 11.4 | 2724 | 172 | 10916 | 3915 | 391 | 31 | 3796 |
| curlite-awslc-nojit | 3334 | - | 11.8 | 3024 | 173 | 11036 | 4419 | 441 | 21 | 4820 |
| reqwest-rustls | 2180 | 85 | 11.9 | 3108 | 205 | 11644 | 5385 | 538 | 22 | 3734 |
| curlite-rustls | 3334 | 35 | 11.9 | 2980 | 172 | 11044 | 4583 | 458 | 488 | 4986 |
| curlite-static-ssl | 6172 | 20 | 16.8 | 5456 | 172 | 13604 | 12341 | 1234 | 48 | 7508 |
| ureq-native | 836 | 30 | 18.1 | 4452 | 104 | 12772 | 12294 | 1229 | 223 | 12128 |
| curlite-static | 1094 | 20 | 23.4 | 6928 | 180 | 15076 | 13701 | 1370 | 55 | 9808 |
| isahc | 773 | 73 | 44.8 | 12208 | 270 | 19720 | 25638 | 2563 | 140 | 15872 |
| curlite (distro libcurl) | 452 | 20 | 45.6 | 11984 | 222 | 19028 | 24036 | 2403 | 75 | 14680 |
| reqwest-native | 1156 | 85 | 183.2 | 10704 | 202 | 19152 | 37732 | 3773 | 192 | 11344 |

What the board says:

- **Cold start and memory are decided by the TLS library and the linking**,
  not by the HTTP client. The distro libcurl (34 shared objects) and anything
  on OpenSSL 3 start at 17 to 46 ms and 5 to 12 MiB. A static musl binary on
  rustls starts in 9.4 ms with 1.1 MiB, an empty C program in 7 ms and 0.7 MiB.
- **aws-lc's CPU jitter entropy costs 480 ms per HTTPS process** on this
  core. It hits attohttpc and the plain `curlite-rustls` build alike; the
  `AWS_LC_SYS_NO_JITTER_ENTROPY=1` row shows the same build without it.
- **OpenSSL via native-tls parses the whole CA bundle per process**: 223 ms
  for ureq-native, 192 ms for reqwest-native. curlite on OpenSSL lets OpenSSL
  look certificates up by hash instead (48 to 75 ms).
- **Shared pages matter with many processes**: 10 curlite musl processes
  cost 2 MiB together, 10 ureq processes 5.5 MiB.
- **Per request, libcurl is slower than ureq on this core** (170 vs 106 µs
  over a keep-alive connection); minreq and attohttpc open a connection per
  request. The HTTPS handshake is the floor for everyone at about 20 ms,
  ring's ARM handshake is a third slower than aws-lc's.
