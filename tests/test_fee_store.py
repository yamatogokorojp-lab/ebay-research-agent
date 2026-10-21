import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from fee_updates import FeeUpdateError
from fee_store import store_verified_snapshot, load_current_snapshot, snapshot_is_current

NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)


def sample():
    return {'rates': {'SpeedPAK Economy': {'fuel_pct': 15, 'peak_jpy': 350,
       'customs_jpy': 120, 'other_jpy': 0, 'effective_from': '2026-10-01',
       'effective_to': '2026-10-31', 'source_url': 'https://www.orangeconnex.jp/charges'}}}


class FeeStoreTests(unittest.TestCase):
    def test_store_restore_and_history(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'current.json'
            stored = store_verified_snapshot(sample(), path, NOW)
            self.assertEqual(load_current_snapshot(path, NOW)['SpeedPAK Economy']['peak_jpy'], 350)
            self.assertEqual(stored['SpeedPAK Economy']['customs_jpy'], 120)
            self.assertEqual(len(list((Path(d) / 'history').glob('*.json'))), 1)
    def test_rejected_update_cannot_destroy_previous(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'current.json'
            store_verified_snapshot(sample(), path, NOW)
            original = path.read_bytes()
            bad = sample(); bad['rates']['SpeedPAK Economy']['fuel_pct'] = -99
            with self.assertRaises(FeeUpdateError):
                store_verified_snapshot(bad, path, NOW)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(len(list((Path(d) / 'history').glob('*.json'))), 1)
    def test_expired_snapshot_is_not_current(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'current.json'
            store_verified_snapshot(sample(), path, NOW)
            later = datetime(2026, 11, 1, tzinfo=timezone.utc)
            with self.assertRaises(FeeUpdateError):
                load_current_snapshot(path, later)
            self.assertFalse(snapshot_is_current(json.loads(path.read_text())['rates'], later))
    def test_fake_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'current.json'
            bad = sample(); bad['rates']['SpeedPAK Economy']['source_url'] = 'https://orangeconnex.jp.phishing.test/'
            with self.assertRaises(FeeUpdateError):
                store_verified_snapshot(bad, path, NOW)
            self.assertFalse(path.exists())

if __name__=='__main__': unittest.main()
