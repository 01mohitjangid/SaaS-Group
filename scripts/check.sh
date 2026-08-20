#!/usr/bin/env bash
# Everything CI will run, in parallel. Wall-clock is the slowest check, not the sum.
#
#   ./scripts/check.sh          or   make check
#
# Backend:  ruff format --check · ruff check · mypy · pytest
# Frontend: added in step 3, alongside the two React apps.
#
# A check whose tool is missing prints SKIP rather than failing, so read the SKIP
# lines: a green run with skips means "nothing available failed", not "all covered".
# The database tests skip when PostgreSQL is unreachable — run `make db` first.
#
# Exits 0 only if nothing FAILed.

set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root" || exit 1

BE=backend
VENV="$root/$BE/.venv/bin"

logdir="$(mktemp -d)"
trap 'rm -rf "$logdir"' EXIT
names=()

run() { # name, cmd...
  local name="$1"
  shift
  names+=("$name")
  (
    cd "$root/$BE" || exit 1
    "$@" >"$logdir/$name.out" 2>&1
    echo $? >"$logdir/$name.code"
  ) &
}

skip() {
  names+=("$1")
  echo "$2" >"$logdir/$1.out"
  echo skip >"$logdir/$1.code"
}

echo "▸ check (parallel) · backend=$BE"

if [ -x "$VENV/ruff" ]; then
  run be:format "$VENV/ruff" format --check .
  run be:lint "$VENV/ruff" check .
else
  skip be:format "ruff not installed — run: cd $BE && uv pip install -e '.[dev]'"
  skip be:lint "ruff not installed"
fi

if [ -x "$VENV/mypy" ]; then
  run be:types "$VENV/mypy" .
else
  skip be:types "mypy not installed — types are UNCHECKED"
fi

if [ -x "$VENV/python" ]; then
  run be:tests "$VENV/python" -m pytest -rs
  # `-rs` prints the skip reasons; the summary line is parsed below so a run where the
  # database tests silently skipped cannot read as a clean pass.
else
  skip be:tests "no virtualenv — tests did NOT run"
fi

if [ -f "$root/frontend/package.json" ]; then
  skip fe:all "frontend checks are wired in step 3"
else
  skip fe:all "no frontend yet — that is step 3, not a passing check"
fi

wait

failed=0
passed=0
skipped=0
skipped_tests=0
for name in "${names[@]}"; do
  code="$(cat "$logdir/$name.code" 2>/dev/null || echo 1)"
  if [ "$code" = "skip" ]; then
    skipped=$((skipped + 1))
    printf '  SKIP  %-10s %s\n' "$name" "$(cat "$logdir/$name.out")"
  elif [ "$code" = "0" ]; then
    passed=$((passed + 1))
    summary="$(grep -Eo '[0-9]+ (passed|skipped|deselected)(, [0-9]+ (passed|skipped|deselected))*' "$logdir/$name.out" | tail -1)"
    printf '  PASS  %-10s %s\n' "$name" "$summary"
    if printf '%s' "$summary" | grep -q skipped; then
      skipped_tests=1
      printf '        %s\n' "$(grep -E '^SKIPPED' "$logdir/$name.out" | head -3)"
    fi
  else
    failed=$((failed + 1))
    printf '  FAIL  %-10s\n' "$name"
    sed 's/^/        /' "$logdir/$name.out"
  fi
done

if [ "$failed" != "0" ]; then
  echo "▸ check: RED ($passed passed, $failed failed, $skipped skipped)"
  exit 1
fi

# "Nothing failed" is not "everything was checked". Say which one this is.
if [ "$passed" = "0" ]; then
  echo "▸ check: NOTHING RAN — every check was skipped. This is not a pass."
  exit 1
fi

echo "▸ check: GREEN ($passed passed, $skipped skipped)"
if [ "$skipped" != "0" ]; then
  echo "  Read the SKIP lines above: a skipped check is a coverage hole, not a pass."
fi
if [ "$skipped_tests" != "0" ]; then
  echo "  ! Some TESTS skipped inside a passing check. The database tests need"
  echo "    PostgreSQL and the peblo_tv_test database: run 'make db' and check again."
  # Locally a skip is a warning — not everyone has Docker running. In CI it is a
  # failure, because a pipeline that skips its integration tests is lying.
  if [ "${STRICT_TESTS:-0}" = "1" ]; then
    echo "▸ check: RED — STRICT_TESTS=1 and some tests did not run."
    exit 1
  fi
fi
exit 0
