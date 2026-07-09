# Christman Media Installer — Hardening Update (2026-07-03)

Drop-in replacement for the repo contents. Nothing removed, one module added.

## Apply (from anywhere)
```bash
cd /path/to/ChristmanMediaInstaller       # your local clone
cp -r /path/to/unzipped/CMI_hardened/* .  # overwrite with these files
python3 -m py_compile christman_media_installer/*.py
pip install -e .                          # works now — pyproject backend was broken before this update
git add -A && git commit -m "Hardening: isolation vault, ledger, restore, verifier crash guard, real MCP tools"
git push
```

## What changed
- NEW  isolation_vault.py — CHRISTMAN_ISOLATION/<session>/ + append-only LEDGER.json.
  Disengaged files vaulted with SHA-256 (never deleted). Caches purged + logged.
  Unlocked capabilities (packages/env/shims/MCP) ledgered.
- NEW  command: christman-media restore --target <path> --session <id>
  Hash-verified, refuses to overwrite conflicts.
- NEW  flag: --displace on install/repair — explicit approval to vault real-logic
  files when a shim must take their place. Default stays non-destructive.
- FIX  pyproject.toml — invalid build backend; pip install -e . was impossible.
- FIX  verifier.py — missing 'say' binary crashed the whole verify suite; now a
  recorded failure with reason. Swallowed sounddevice exception now surfaced.
- FIX  shim_engine.py — unreadable file no longer treated as safe to overwrite;
  stale shims vaulted before replacement.
- FIX  installer.py — MCP tool template was a stub pretending to work; now runs
  the real explore pipeline or honestly reports UNAVAILABLE. Pre-flight hygiene
  (pycache/pyc/audio_cache purge) added per infrastructure manifest v1.4.0.
- FIX  constants.py — explorer now recognizes the live christman_sound stack
  (EAR/SPEAK/TONE/PHONEMES/VOICE_PROFILE).
- ADD  truth report ISOLATION section + explore now displays ear canal / voice SDK refs.

All proven by live runs 2026-07-03: displace → vault → restore round-trip with
byte-identical hash verification; purges ledgered; verify completes on a box
with no speech binaries.
