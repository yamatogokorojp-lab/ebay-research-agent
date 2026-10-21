"""Durable, auditable handling of authoritative shipping-fee snapshots.

The rate provider is responsible for validating the official data format and
license. We never treat missing or expired values as zero, nor serve an older
snapshot as a current rate. A history of accepted updates is kept on disk.
"""
from __future__ import annotations

from datetime import datetime, timezone, date
from pathlib import Path
from tempfile import NamedTemporaryFile
import json
import os

from fee_updates import FeeUpdateError, validate_fee_feed


def snapshot_is_current(snapshot: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    try:
        return bool(snapshot) and all(
            date.fromisoformat(rec['effective_from']) <= now.date() <= date.fromisoformat(rec['effective_to'])
            for rec in snapshot.values()
        )
    except (TypeError, KeyError, ValueError, AttributeError):
        return False


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never leave a half-written current snapshot in case of a power failure.
    temp = None
    try:
        with NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, prefix='.fee-', suffix='.tmp', delete=False) as f:
            temp = Path(f.name)
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def store_verified_snapshot(doc: dict, destination: Path, now: datetime | None = None) -> dict:
    """Validate entire feed before writing; on error, retain previous snapshot."""
    now = now or datetime.now(timezone.utc)
    verified = validate_fee_feed(doc, now)
    _atomic_json(destination, {'rates': verified, 'accepted_at': now.isoformat()})
    # Keep a tamper-evident-by-comparison copy by date/time; no claimed
    # cryptographic authenticity, and do not embed credentials.
    history = destination.parent / 'history' / f"{now.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    _atomic_json(history, {'rates': verified, 'accepted_at': now.isoformat()})
    return verified


def load_current_snapshot(destination: Path, now: datetime | None = None) -> dict:
    """Return only values valid today; older values remain in history only."""
    if not destination.is_file():
        raise FeeUpdateError('適用できる保存料金はありません')
    try:
        with destination.open(encoding='utf-8') as f:
            payload = json.load(f)
        rates = payload['rates']
        if not snapshot_is_current(rates, now):
            raise FeeUpdateError('保存された料金の適用期間が終了しています')
        # Previously stored data still have to satisfy the *current* rules.
        return validate_fee_feed({'rates': rates}, now)
    except (OSError, ValueError, TypeError, KeyError) as err:
        raise FeeUpdateError('保存料金の整合性を確認できません') from err
