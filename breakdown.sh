#!/bin/bash
# breakdown.sh <fetch binary> [https url]: where a cold start spends its time.
# Shared libraries, dynamic-loader relocations, then CPU/wall/RSS for one
# plain-HTTP GET against bench-server and one HTTPS GET, 5 runs each (median).
set -u
export LC_ALL=C
bin=$1; https=${2:-https://example.com/}
here=$(cd "$(dirname "$0")" && pwd); rel=$here/target/release
echo "== $bin"
echo "libs: $(ldd "$bin" | grep -c '=>') shared, binary $(( $(stat -c %s "$bin") / 1024 )) KiB"
LD_DEBUG=statistics "$bin" http://127.0.0.1:18099/small 2>&1 >/dev/null | grep -E "relocations:|startup time" | sed 's/^ *[0-9]*:\s*/  /' | head -3
"$rel/bench-server" 127.0.0.1:18099 2>/dev/null & srv=$!
sleep 0.3
median() { sort -n | awk '{a[NR]=$1} END {print a[int((NR+1)/2)]}'; }
run() { # label url
  local w=() c=() r=()
  for i in 1 2 3 4 5; do
    read -r wall cpu rss < <("$rel/measure" "$bin" "$2" 2>&1 >/dev/null | tail -1)
    w+=("$wall"); c+=("$cpu"); r+=("$rss")
  done
  printf "%-6s wall %6.1f ms  cpu %6.1f ms  rss %6d KiB\n" "$1" \
    "$(printf '%s\n' "${w[@]}" | median | awk '{print $1/1000}')" \
    "$(printf '%s\n' "${c[@]}" | median | awk '{print $1/1000}')" \
    "$(printf '%s\n' "${r[@]}" | median)"
}
run http http://127.0.0.1:18099/small
run https "$https"
kill $srv 2>/dev/null
