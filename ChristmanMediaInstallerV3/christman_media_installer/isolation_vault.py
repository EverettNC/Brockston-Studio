"""
Christman Media Installer — isolation_vault.py
The Christman AI Project / Luma Cognify AI
Owner: Everett Nathaniel Christman

The Isolation Vault keeps the pathway correct.

Anything the installer DISENGAGES (displaces, retires, or purges) is either
moved into CHRISTMAN_ISOLATION/<session>/ with its relative path preserved
and its SHA-256 recorded before the move — or, for regenerable caches only,
deleted with the purge logged. Anything the installer UNLOCKS (packages,
env keys, shims, MCP tools) is recorded in the same ledger.

One ledger tells the complete truth about what the pathway looked like
before and after. Everything vaulted is restorable.

Why this design (Rule 11):
- Rule 2:  The vault lives at the target root. Visible. Never hidden.
- Rule 6:  Every failure raises or logs with context. Nothing is swallowed.
- Rule 9:  restore() walks the ledger backward. Change is cheap.
- Rule 13: Hashes are computed from bytes on disk, never assumed.
Caches (__pycache__, .pyc, stale audio_cache) are DELETED, not vaulted —
vaulting regenerable garbage is noise — but every purge is logged.
Real code is ALWAYS vaulted, never deleted. That decision is Everett's,
recorded 2026-07-03.
"""

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .constants import INSTALLER_VERSION

logger = logging.getLogger("christman.isolation_vault")

VAULT_DIRNAME = "CHRISTMAN_ISOLATION"
LEDGER_FILENAME = "LEDGER.json"

# Record types
DISENGAGED = "DISENGAGED"   # real file moved into the vault
PURGED = "PURGED"           # regenerable cache deleted (logged, not vaulted)
UNLOCKED = "UNLOCKED"       # capability enabled (package/env/shim/mcp)
RESTORED = "RESTORED"       # vaulted file returned to its original path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_of(path: Path) -> str:
    """Hash real bytes on disk. No assumptions."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class LedgerRecord:
    record_type: str            # DISENGAGED | PURGED | UNLOCKED | RESTORED
    session_id: str
    timestamp: str
    reason: str
    original_path: str = ""     # relative to target root
    vault_path: str = ""        # relative to target root (empty for PURGED/UNLOCKED)
    sha256: str = ""            # hash before the move (files only)
    detail: str = ""            # e.g. package name, env key, shim target
    installer_version: str = INSTALLER_VERSION


class IsolationVault:
    """Session-scoped vault + append-only ledger for one target project.

    Usage:
        vault = IsolationVault("/path/to/being")
        vault.disengage(some_file, reason="displaced by shim: logger.py")
        vault.record_unlocked("env_key", "CHRISTMAN_TTS_ENGINE", reason="env defaults")
        vault.purge_cache(pycache_dir, reason="pre-flight hygiene")
    """

    def __init__(self, target_path: str, session_id: Optional[str] = None,
                 dry_run: bool = False):
        self.target = Path(target_path).resolve()
        if not self.target.is_dir():
            raise NotADirectoryError(
                f"Vault target must be an existing directory: {self.target}"
            )
        self.dry_run = dry_run
        self.session_id = session_id or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H-%M-%SZ"
        )
        self.vault_root = self.target / VAULT_DIRNAME
        self.session_dir = self.vault_root / self.session_id
        self.ledger_path = self.vault_root / LEDGER_FILENAME
        self.records: List[LedgerRecord] = []

    # ──────────────────────────────────────────
    # DISENGAGE — move a real file into the vault
    # ──────────────────────────────────────────
    def disengage(self, file_path: Path, reason: str) -> LedgerRecord:
        """Move one real file into the vault, preserving its relative path.
        Hash is computed BEFORE the move. Raises loudly on any failure."""
        src = Path(file_path).resolve()
        if not src.is_file():
            raise FileNotFoundError(
                f"Cannot disengage a file that isn't there: {src}"
            )
        try:
            rel = src.relative_to(self.target)
        except ValueError:
            raise ValueError(
                f"Refusing to disengage a file outside the target root: {src}"
            )
        if VAULT_DIRNAME in rel.parts:
            raise ValueError(
                f"Refusing to disengage a file already inside the vault: {rel}"
            )

        digest = _sha256_of(src)
        dest = self.session_dir / rel
        record = LedgerRecord(
            record_type=DISENGAGED,
            session_id=self.session_id,
            timestamp=_utc_now(),
            reason=reason,
            original_path=str(rel),
            vault_path=str(dest.relative_to(self.target)),
            sha256=digest,
        )

        if self.dry_run:
            logger.info(f"  [dry-run] Would disengage: {rel} → {record.vault_path}")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            logger.info(f"  📦 Disengaged: {rel} → {record.vault_path}")

        self._append(record)
        return record

    # ──────────────────────────────────────────
    # PURGE — delete regenerable cache, log it
    # ──────────────────────────────────────────
    def purge_cache(self, cache_path: Path, reason: str) -> LedgerRecord:
        """Delete a regenerable cache file or directory. Logged, never vaulted.
        Only paths matching known cache patterns are accepted."""
        src = Path(cache_path).resolve()
        try:
            rel = src.relative_to(self.target)
        except ValueError:
            raise ValueError(
                f"Refusing to purge a path outside the target root: {src}"
            )

        name = src.name
        is_cache = (
            name == "__pycache__"
            or name.endswith(".pyc")
            or name == "audio_cache"
        )
        if not is_cache:
            raise ValueError(
                f"Refusing to purge non-cache path (vault it instead): {rel}"
            )

        record = LedgerRecord(
            record_type=PURGED,
            session_id=self.session_id,
            timestamp=_utc_now(),
            reason=reason,
            original_path=str(rel),
        )

        if self.dry_run:
            logger.info(f"  [dry-run] Would purge cache: {rel}")
        else:
            if src.is_dir():
                shutil.rmtree(src)
            elif src.exists():
                src.unlink()
            logger.info(f"  🧹 Purged cache: {rel}")

        self._append(record)
        return record

    # ──────────────────────────────────────────
    # UNLOCKED — record an enabled capability
    # ──────────────────────────────────────────
    def record_unlocked(self, kind: str, detail: str, reason: str) -> LedgerRecord:
        """Record something the installer enabled: package, env_key, shim,
        mcp_tool, init_file. No file moves — ledger entry only."""
        record = LedgerRecord(
            record_type=UNLOCKED,
            session_id=self.session_id,
            timestamp=_utc_now(),
            reason=reason,
            detail=f"{kind}: {detail}",
        )
        self._append(record)
        return record

    # ──────────────────────────────────────────
    # RESTORE — walk a session's ledger backward
    # ──────────────────────────────────────────
    def restore_session(self, session_id: str) -> List[LedgerRecord]:
        """Return every DISENGAGED file from the named session to its original
        path. Verifies each hash after the move. Refuses to overwrite a file
        that now exists at the original path — that conflict is reported, not
        resolved silently."""
        all_records = self.read_ledger()
        to_restore = [
            r for r in all_records
            if r["record_type"] == DISENGAGED and r["session_id"] == session_id
        ]
        if not to_restore:
            raise ValueError(
                f"No DISENGAGED records found for session: {session_id}"
            )

        restored: List[LedgerRecord] = []
        for r in reversed(to_restore):
            vault_file = self.target / r["vault_path"]
            original = self.target / r["original_path"]

            if not vault_file.is_file():
                raise FileNotFoundError(
                    f"Ledger says vaulted, disk disagrees: {r['vault_path']} "
                    f"is missing. Restore halted — vault integrity is in question."
                )
            if original.exists():
                raise FileExistsError(
                    f"Refusing to overwrite existing file during restore: "
                    f"{r['original_path']}. Move it aside yourself, then re-run."
                )

            if not self.dry_run:
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(vault_file), str(original))
                after = _sha256_of(original)
                if after != r["sha256"]:
                    raise RuntimeError(
                        f"HASH MISMATCH after restore of {r['original_path']}: "
                        f"expected {r['sha256']}, got {after}. "
                        f"The file changed while vaulted. Investigate before trusting it."
                    )
                logger.info(f"  ↩️  Restored: {r['original_path']} (hash verified)")

            rec = LedgerRecord(
                record_type=RESTORED,
                session_id=self.session_id,
                timestamp=_utc_now(),
                reason=f"restore of session {session_id}",
                original_path=r["original_path"],
                vault_path=r["vault_path"],
                sha256=r["sha256"],
            )
            self._append(rec)
            restored.append(rec)

        return restored

    # ──────────────────────────────────────────
    # LEDGER I/O — append-only, honest on corruption
    # ──────────────────────────────────────────
    def read_ledger(self) -> List[dict]:
        if not self.ledger_path.is_file():
            return []
        try:
            data = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Ledger is corrupt and cannot be trusted: {self.ledger_path} "
                f"({e}). Do not proceed until this is resolved."
            )
        if not isinstance(data, list):
            raise RuntimeError(
                f"Ledger has unexpected shape (expected list): {self.ledger_path}"
            )
        return data

    def _append(self, record: LedgerRecord) -> None:
        self.records.append(record)
        if self.dry_run:
            return
        existing = self.read_ledger()
        existing.append(asdict(record))
        self.vault_root.mkdir(parents=True, exist_ok=True)
        tmp = self.ledger_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        tmp.replace(self.ledger_path)

    # ──────────────────────────────────────────
    # SUMMARY — for the truth report
    # ──────────────────────────────────────────
    def session_summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "vault_root": str(self.vault_root),
            "disengaged": [asdict(r) for r in self.records
                           if r.record_type == DISENGAGED],
            "purged": [asdict(r) for r in self.records
                       if r.record_type == PURGED],
            "unlocked": [asdict(r) for r in self.records
                         if r.record_type == UNLOCKED],
            "restored": [asdict(r) for r in self.records
                         if r.record_type == RESTORED],
        }
