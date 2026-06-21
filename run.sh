#!/usr/bin/env bash
# MemEd Linux launcher
# Run as root OR set: sudo sysctl kernel.yama.ptrace_scope=0
cd "$(dirname "$0")"
python3 main.py "$@"
