"""Persisted history through the real HTTP API, including restart and late checks."""
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from apps.backend.elbow_room.server import Observations, database_connection, make_handler, read_config


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        path = root / 'config.json'
        path.write_text(json.dumps({'train_name': 'History test', 'platform_name': 'Test', 'direction': 'right', 'coaches': [
            {'coach_id': name, 'coach_name': name, 'capacity': 100, 'interval_seconds': 60, 'counts': [0]}
            for name in ('one', 'two')]}))
        self.config = read_config(path)
        self.database = root / 'history.sqlite3'
        self.store = Observations(self.database, self.config)
        self.base = self.start_api(self.store)

    def start_api(self, store):
        handler = make_handler(store)
        handler.log_message = lambda *_: None
        api = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=api.serve_forever, daemon=True)
        thread.start()
        def close():
            api.shutdown()
            api.server_close()
            thread.join(timeout=2)
        self.addCleanup(close)
        return f'http://127.0.0.1:{api.server_port}'

    def get(self, query='', base=None):
        with urlopen((base or self.base) + '/api/history' + query, timeout=3) as response:
            return json.load(response)

    def test_filtered_cursor_pages_cover_old_records_despite_new_insertions(self):
        ids = []
        for index in range(125):
            ids.append(self.store.publish(self.config['coaches'][0], index)['id'])
            self.store.publish(self.config['coaches'][1], 5)
        page = self.get('?coach_id=one&limit=20')
        seen = [row['id'] for row in page['items']]
        newest = self.store.publish(self.config['coaches'][0], 999)
        while page['next_before'] is not None:
            page = self.get(f"?coach_id=one&limit=20&before={page['next_before']}")
            self.assertTrue(all(row['coach_id'] == 'one' for row in page['items']))
            seen.extend(row['id'] for row in page['items'])
        self.assertEqual(seen, list(reversed(ids)))
        self.assertEqual(self.get('?coach_id=one')['items'][0]['id'], newest['id'])

    def test_verification_timestamps_counts_and_failures_survive_restart(self):
        coach = self.config['coaches'][0]
        observed = datetime.now(timezone.utc) - timedelta(hours=1)
        original = self.store.publish(coach, 10, observed_at=observed)
        failed = self.store.publish(coach, 20)
        pending = self.store.publish(coach, 30)
        self.store.mark_verification_pending(original['id'], 'test-model')
        self.store.finish_verification(original['id'], count=90, sample_counts=[90, 90, 90], model='test-model')
        self.store.finish_verification(failed['id'], error='Unable to assess', model='test-model')
        self.store.mark_verification_pending(pending['id'], 'test-model')
        restart = Observations(self.database, self.config)
        records = self.get('?coach_id=one', base=self.start_api(restart))['items']
        checked = records[-1]
        self.assertEqual(checked['observed_at'], observed.isoformat())
        self.assertGreater(checked['verification']['completed_at'], checked['observed_at'])
        self.assertEqual((checked['regular_passenger_count'], checked['passenger_count'], checked['occupancy_percent'], checked['status']), (10, 90, 90, 'red'))
        self.assertTrue(checked['verification']['disagreement'])
        self.assertEqual(records[1]['passenger_count'], 20)
        self.assertEqual(records[1]['verification']['status'], 'unavailable')
        self.assertEqual(records[0]['verification']['reason'], 'Verification interrupted by restart')
        self.assertEqual(self.store.snapshot()['coaches'][0]['passenger_count'], 30)
        self.assertIsNone(restart.snapshot()['coaches'][0]['passenger_count'])

    def test_empty_legacy_and_invalid_queries(self):
        self.assertEqual(self.get(), {'items': [], 'next_before': None})
        row = self.store.publish(self.config['coaches'][0], 0)
        row.pop('regular_passenger_count')
        row.pop('verification')
        with database_connection(self.database) as connection:
            connection.execute('UPDATE observations SET payload=? WHERE id=?', (json.dumps(row), row['id']))
        legacy = self.get()['items'][0]
        self.assertEqual(legacy['regular_passenger_count'], 0)
        self.assertEqual(legacy['verification']['status'], 'not_recorded')
        self.assertEqual(self.get('?coach_id=missing')['items'], [])
        self.assertEqual(self.get('?coach_id=%27%20OR%201%3D1--')['items'], [])
        for query in ('?limit=0', '?limit=101', '?limit=no', '?before=-1', '?before=9999999999999999999999999', '?before=', '?limit=2&limit=3', '?unexpected=true'):
            with self.subTest(query=query), self.assertRaises(HTTPError) as error:
                self.get(query)
            self.assertEqual(error.exception.code, 400)
            error.exception.close()
