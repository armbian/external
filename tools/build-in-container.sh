#!/bin/sh
# Run one extpkg build in a container of the release.
# The job has no "container:": the runner's node (JavaScript actions) needs
# glibc 2.38 on riscv64, but jammy and bookworm have older glibc.
# Usage: build-in-container.sh <image> <extpkg build arguments>
set -eu
image=$1; shift
summary=${GITHUB_STEP_SUMMARY:-/dev/null}
exec docker run --rm -v "$PWD:/work" -w /work \
	-v "$summary:/summary.md" -e GITHUB_STEP_SUMMARY=/summary.md -e GITHUB_ACTIONS \
	-e HOST_IDS="$(id -u):$(id -g)" -e DEBIAN_FRONTEND=noninteractive \
	"$image" sh -euc '
	# Give the files back to the runner user: the next checkout cleans the workspace.
	trap "chown -R \"\$HOST_IDS\" /work" EXIT
	apt-get update -qq
	apt-get install -y -qq --no-install-recommends python3 python3-yaml git ca-certificates \
		dpkg-dev build-essential fakeroot patch xz-utils
	git config --global --add safe.directory "*"
	python3 -m extpkg build "$@"' sh "$@"
