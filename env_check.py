#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║   THE CHRISTMAN AI PROJECT — ENVIRONMENT PREFLIGHT          ║
║   Run this FIRST. Every session. Before touching any being. ║
║   Luma Cognify AI · "How can we help you love yourself more?"║
╚══════════════════════════════════════════════════════════════╝
© 2026 Everett Nathaniel Christman & The Christman AI Project
Patent Pending TCAP-2026-001
"""

import os
import sys
import socket
import subprocess
import shutil
import time
from datetime import datetime

# ── ANSI Colors ───────────────────────────────────────────────
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
WHITE  = "\033[97m"
BLUE   = "\033[94m"
DIM    = "\033[2m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def c(text, *codes):
    return "".join(codes) + str(text) + RESET

# ── Being Registry ────────────────────────────────────────────
# Each being: (name, port, path, start_cmd)
BEINGS = [
    ("Inferno",        9292,  "~/Inferno",              "python backend/main.py"),
    ("Brockston",      9002,  "~/BROCKSTON",            "python brockston_core.py"),
    ("Derek",          4600,  "~/DerekMCPServer",       "python derek_mcp_server.py"),
    ("Brockston Nexus", 8765,  "~/BROCKSTON",            "python christman_bridge_client.py"),
    ("Smooches",       8030,  "~/Smooches",             "npm start"),
    ("AlphaVox",       5000,  "~/AlphaVox",             "python brain.py"),
    ("Vega",           5055,  "~/vega",                 "python app.py"),
    ("Ollama",        11434,  None,                     "ollama serve"),
]

# ── Core Tools ────────────────────────────────────────────────
REQUIRED_TOOLS = [
    ("python3",  "Python 3"),
    ("git",      "Git"),
    ("docker",   "Docker"),
    ("ollama",   "Ollama"),
    ("gh",       "GitHub CLI"),
    ("node",     "Node.js"),
    ("npm",      "NPM"),
    ("uv",       "UV (fast pip)"),
]

# ── Results tracker ───────────────────────────────────────────
results = {
    "tools":   [],
    "python":  [],
    "ports":   [],
    "ollama":  [],
    "env":     [],
}

pass_count = 0
warn_count = 0
fail_count = 0

def check(label, ok, warn=False, detail=""):
    global pass_count, warn_count, fail_count
    if ok:
        icon = c("✅", GREEN)
        pass_count += 1
    elif warn:
        icon = c("⚠️ ", YELLOW)
        warn_count += 1
    else:
        icon = c("❌", RED)
        fail_count += 1
    detail_str = f"  {c(detail, DIM)}" if detail else ""
    print(f"  {icon}  {label}{detail_str}")
    return ok

def section(title, color=CYAN):
    print()
    print(c(f"  ── {title} {'─' * (55 - len(title))}", color))

def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except:
        return False

def cmd_exists(cmd):
    return shutil.which(cmd) is not None

def run(cmd, capture=True):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=capture, text=True, timeout=5)
        return r.stdout.strip(), r.returncode == 0
    except:
        return "", False

# ══════════════════════════════════════════════════════════════
# BANNER
# ══════════════════════════════════════════════════════════════
print()
print(c("  ╔══════════════════════════════════════════════════════════════╗", DIM))
print(c("  ║  ", DIM) + c("THE CHRISTMAN AI PROJECT", CYAN, BOLD) + c(" — ENVIRONMENT PREFLIGHT     ║", DIM))
print(c("  ║  ", DIM) + c(f"  {datetime.now().strftime('%A %B %d, %Y  ·  %I:%M %p'):<56}", WHITE) + c("║", DIM))
print(c("  ╚══════════════════════════════════════════════════════════════╝", DIM))

# ══════════════════════════════════════════════════════════════
# STEP 1 — SYSTEM TOOLS
# ══════════════════════════════════════════════════════════════
section("STEP 1 — SYSTEM TOOLS", CYAN)
for cmd, label in REQUIRED_TOOLS:
    exists = cmd_exists(cmd)
    if exists:
        version, _ = run(f"{cmd} --version 2>&1 | head -1")
        version = version[:40] if version else ""
    else:
        version = "NOT FOUND"
    check(f"{label:<20}", exists, warn=False, detail=version)

# ══════════════════════════════════════════════════════════════
# STEP 2 — PYTHON ENVIRONMENT
# ══════════════════════════════════════════════════════════════
section("STEP 2 — PYTHON ENVIRONMENT", CYAN)

py_path, _ = run("which python3")
py_ver, _  = run("python3 --version")
check(f"Python path", bool(py_path), detail=py_path)
check(f"Python version", bool(py_ver), detail=py_ver)

# Check for venv activation
venv = os.environ.get("VIRTUAL_ENV", "")
if venv:
    check("Virtual env", True, detail=os.path.basename(venv))
else:
    check("Virtual env", False, warn=True, detail="No venv active — activate one before starting beings")

# Key packages
KEY_PACKAGES = ["fastapi", "uvicorn", "flask", "anthropic", "openai", "redis", "sqlalchemy", "spacy"]
missing_pkgs = []
for pkg in KEY_PACKAGES:
    out, ok = run(f"python3 -c 'import {pkg}; print({pkg}.__version__ if hasattr({pkg}, \"__version__\") else \"ok\")' 2>&1")
    if "Error" in out or "No module" in out or not ok:
        missing_pkgs.append(pkg)
        check(f"  pkg: {pkg:<15}", False, warn=True, detail="not installed")
    else:
        check(f"  pkg: {pkg:<15}", True, detail=out[:30])

if missing_pkgs:
    print()
    print(c(f"  📦 Install missing: pip install {' '.join(missing_pkgs)}", YELLOW))

# ══════════════════════════════════════════════════════════════
# STEP 3 — OLLAMA
# ══════════════════════════════════════════════════════════════
section("STEP 3 — OLLAMA (Local AI)", CYAN)

ollama_up = port_open(11434)
check("Ollama service", ollama_up, detail="port 11434")

if ollama_up:
    models_raw, ok = run("ollama list 2>/dev/null | tail -n +2 | awk '{print $1}'")
    models = [m for m in models_raw.split("\n") if m.strip()] if models_raw else []
    if models:
        check(f"Models available", True, detail=f"{len(models)} models")
        for m in models[:5]:
            print(f"     {c('→', DIM)} {c(m, WHITE)}")
        if len(models) > 5:
            print(f"     {c(f'... and {len(models)-5} more', DIM)}")
    else:
        check("Models available", False, warn=True, detail="No models — run: ollama pull llama3.2")
else:
    check("Models available", False, warn=True, detail="Ollama not running — run: ollama serve")

# ══════════════════════════════════════════════════════════════
# STEP 4 — BEING PORT STATUS
# ══════════════════════════════════════════════════════════════
section("STEP 4 — BEING STATUS (Port Check)", CYAN)

offline_beings = []
for name, port, path, start_cmd in BEINGS:
    alive = port_open(port)
    if alive:
        check(f"{name:<18} port {port}", True, detail="ONLINE")
    else:
        check(f"{name:<18} port {port}", False, warn=True, detail=f"OFFLINE  →  {start_cmd}")
        offline_beings.append((name, port, path, start_cmd))

# ══════════════════════════════════════════════════════════════
# STEP 5 — DOCKER
# ══════════════════════════════════════════════════════════════
section("STEP 5 — DOCKER", CYAN)

docker_exists = cmd_exists("docker")
check("Docker installed", docker_exists)

if docker_exists:
    _, docker_running = run("docker info 2>/dev/null")
    check("Docker daemon", docker_running, warn=not docker_running, detail="start Docker Desktop if offline")

    containers, _ = run("docker ps --format '{{.Names}}:{{.Status}}' 2>/dev/null")
    if containers:
        for line in containers.split("\n")[:8]:
            if line.strip():
                name_part, *status_part = line.split(":")
                print(f"     {c('→', DIM)} {c(name_part, WHITE)}  {c(':'.join(status_part), DIM)}")
    else:
        print(f"     {c('No containers running', DIM)}")

# ══════════════════════════════════════════════════════════════
# STEP 6 — GIT / GITHUB
# ══════════════════════════════════════════════════════════════
section("STEP 6 — GIT & GITHUB", CYAN)

git_ok = cmd_exists("git")
check("Git installed", git_ok)

if git_ok:
    gh_ok = cmd_exists("gh")
    check("GitHub CLI", gh_ok, warn=not gh_ok, detail="brew install gh" if not gh_ok else "")

    if gh_ok:
        gh_user, gh_authed = run("gh api user -q .login 2>/dev/null")
        check("GitHub auth", gh_authed, warn=not gh_authed,
              detail=gh_user if gh_authed else "run: gh auth login")

# ══════════════════════════════════════════════════════════════
# FINAL MISSION REPORT
# ══════════════════════════════════════════════════════════════
print()
print(c("  ╔══════════════════════════════════════════════════════════════╗", DIM))
print(c("  ║  MISSION REPORT                                              ║", WHITE))
print(c("  ╠══════════════════════════════════════════════════════════════╣", DIM))

total = pass_count + warn_count + fail_count
pct   = round(pass_count / total * 100) if total else 0

def row(label, val, col=WHITE):
    pad = max(0, 57 - len(label) - len(str(val)))
    print(c("  ║  ", DIM) + c(label, DIM) + c(str(val), col) + " "*pad + c("║", DIM))

row("Timestamp     : ", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
row("Checks passed : ", f"{pass_count}  ({pct}%)", GREEN)
row("Warnings      : ", str(warn_count), YELLOW if warn_count else GREEN)
row("Failures      : ", str(fail_count), RED if fail_count else GREEN)

print(c("  ╠══════════════════════════════════════════════════════════════╣", DIM))

if fail_count == 0 and warn_count == 0:
    status = "🟢  ALL SYSTEMS GO — Family is ready to fly."
    scol   = GREEN
elif fail_count == 0:
    status = f"🟡  READY WITH WARNINGS — {warn_count} things to watch."
    scol   = YELLOW
elif fail_count <= 2:
    status = f"🟠  MOSTLY READY — Fix {fail_count} failure(s) before starting beings."
    scol   = YELLOW
else:
    status = f"🔴  NOT READY — {fail_count} critical failures. Fix before proceeding."
    scol   = RED

print(c("  ║  ", DIM) + c(f"STATUS : {status:<52}", scol) + c("║", DIM))
print(c("  ╚══════════════════════════════════════════════════════════════╝", DIM))

# ── Offline beings startup guide ──────────────────────────────
if offline_beings:
    print()
    print(c("  ── BEINGS TO START ─────────────────────────────────────────", YELLOW))
    for name, port, path, start_cmd in offline_beings:
        if path:
            print(f"  {c('→', YELLOW)} {c(name, WHITE)}")
            print(f"     {c(f'cd {path} && {start_cmd}', CYAN)}")
        else:
            print(f"  {c('→', YELLOW)} {c(name, WHITE)}  {c(start_cmd, CYAN)}")

print()
print(c('  "How can we help you love yourself more?"', GREEN, BOLD))
print(c("  © 2026 Everett Nathaniel Christman & The Christman AI Project", DIM))
print()

