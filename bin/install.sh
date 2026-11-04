#!/bin/bash
set -euo pipefail
exec "$(dirname "$0")/mif" install "$@"
