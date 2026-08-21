#!/usr/bin/env bash
# The Vercel build, as a script rather than a one-line `buildCommand`.
#
# Why it needs to exist at all:
#
# The pnpm workspace lives in frontend/, not at the repository root. Vercel detects a
# package manager by looking for a lockfile beside the *root* package.json, finds none,
# and so the `pnpm` on PATH is the one the build image bundles — pnpm 6.35.1. That is
# older than this lockfile's format (`lockfileVersion: 9.0`) and refuses to read it:
#
#     WARN   Ignoring not compatible lockfile at /vercel/path0/frontend/pnpm-lock.yaml
#     ERROR  Headless installation requires a pnpm-lock.yaml file
#
# Production builds only worked by accident: ENABLE_EXPERIMENTAL_COREPACK=1 was set on
# that environment alone, so corepack supplied pnpm 10.25.0. Preview builds had no such
# variable and failed every time, in six seconds, at install. Pinning the version here
# makes every environment build the same way, from the repository rather than from
# dashboard state that nobody can see in a diff.

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

# One source of truth for the version: the `packageManager` field the repo already pins.
wanted="$(node -p "require('./package.json').packageManager.split('@')[1]")"

if [ "$(pnpm --version 2>/dev/null || true)" != "$wanted" ]; then
  # `corepack enable` on its own is NOT enough, and this is the trap that cost a build:
  # it writes its shim into Node's bin directory, which sits *after* the image's own
  # pnpm 6.35.1 on PATH. The shim is shadowed, the old binary still runs, and the only
  # symptom is the misleading "not compatible lockfile" above. Installing the shim into
  # a directory we control and putting that first is what actually takes effect — for
  # this script and for the nested `pnpm --filter` calls that `build:vercel` makes.
  shim="$(mktemp -d)"
  corepack enable --install-directory "$shim" pnpm
  export PATH="$shim:$PATH"
  corepack prepare "pnpm@${wanted}" --activate
fi

# Assert rather than hope. A silent version mismatch here surfaces later as an error
# about the lockfile, which sends you looking in entirely the wrong place.
got="$(pnpm --version)"
if [ "$got" != "$wanted" ]; then
  echo "✗ expected pnpm $wanted on PATH, got $got — the corepack shim is being shadowed" >&2
  exit 1
fi
echo "▸ pnpm $got"

cd frontend
pnpm install --frozen-lockfile
pnpm run build:vercel
