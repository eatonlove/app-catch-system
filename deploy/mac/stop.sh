#!/bin/bash
set -euo pipefail
launchctl bootout "gui/$(id -u)/com.appcatch.worker"
