"""Validated optional fee feed. Never infer rates from an unverified webpage.

A provider/authorized JSON endpoint can be configured once its schema and rights
have been verified. Missing, stale and invalid values do not overwrite stored data.
"""
from __future__ import annotations

from datetime import datetime, date, timezone
from urllib.parse import urlparse
from typing import Any
import requests

class FeeUpdateError(Exception):
    pass

METHODS = {'SpeedPAK Economy', 'SpeedPAK FedEx', 'DHL', 'EMS'}
ALLOW_HOSTS = {'orangeconnex.jp', 'www.orangeconnex.jp',
               'fedex.com', 'www.fedex.com', 'dhl.com', 'www.dhl.com',
               'post.japanpost.jp'}
FIELDS = ('fuel_pct', 'peak_jpy', 'customs_jpy', 'other_jpy')


def _trusted(url: str) -> bool:
    parts = urlparse(url)
    return parts.scheme == 'https' and parts.hostname in ALLOW_HOSTS and not parts.username and not parts.password


def validate_fee_feed(doc: Any, retrieved_at: datetime | None = None) -> dict:
    """Reject stale/incomplete data; return a clean immutable-by-convention snapshot.

    Schema (per method): fuel_pct, peak_jpy, customs_jpy, other_jpy,
    effective_from, effective_to, source_url. Providers must publish numbers
    with documented applicability; an absent fee cannot be interpreted as 0.
    """
    now = retrieved_at or datetime.now(timezone.utc)
    if not isinstance(doc, dict) or not isinstance(doc.get('rates'), dict):
        raise FeeUpdateError('料金データの形式が不正です')
    result = {}
    for method, raw in doc['rates'].items():
        if method not in METHODS or not isinstance(raw, dict):
            raise FeeUpdateError('不明な配送サービスが含まれています')
        link = str(raw.get('source_url') or '')
        if not _trusted(link):
            raise FeeUpdateError(f'{method}: 公式ドメインのHTTPS出典が必要です')
        try:
            start = date.fromisoformat(raw['effective_from'])
            end = date.fromisoformat(raw['effective_to'])
        except (ValueError, KeyError, TypeError) as err:
            raise FeeUpdateError(f'{method}: 適用期間が不明です') from err
        if not start <= now.date() <= end or end < start:
            raise FeeUpdateError(f'{method}: 本日の適用期間外なので更新しません')
        values = {}
        for field in FIELDS:
            try:
                value = float(raw[field])
            except (ValueError, TypeError, KeyError) as err:
                raise FeeUpdateError(f'{method}: {field} が未確認です。0円とみなしません') from err
            if not (0 <= value <= (150 if field == 'fuel_pct' else 500000)):
                raise FeeUpdateError(f'{method}: {field} の値が不正です')
            values[field] = value
        values.update({'source_url': link, 'effective_from': start.isoformat(),
                       'effective_to': end.isoformat(), 'checked_at': now.isoformat(timespec='seconds')})
        result[method] = values
    if not result:
        raise FeeUpdateError('料金データが空です')
    return result


def fetch_verified_fees(feed_url: str, now: datetime | None = None) -> dict:
    if not _trusted(feed_url):
        raise FeeUpdateError('自動取得先は承認済みの公式HTTPSドメインに限定しています')
    try:
        response = requests.get(feed_url, timeout=15, headers={'Accept': 'application/json'})
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as err:
        raise FeeUpdateError(f'公式料金データの通信に失敗: {err}') from err
    return validate_fee_feed(payload, now)
