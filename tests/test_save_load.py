"""
tests/test_save_load.py — unit tests for campaign save / load.
"""

import sys
import os
import json
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from campaign_save import (
    save_campaign,
    load_campaign,
    default_progressions,
    STAGE_IDS,
)


class TestDefaultProgressions(unittest.TestCase):

    def setUp(self):
        self.progs = default_progressions()

    def test_all_stages_present(self):
        for sid in STAGE_IDS:
            self.assertIn(sid, self.progs)

    def test_operator_starts_with_debt(self):
        self.assertEqual(self.progs['operator']['debt'], 10000.0)

    def test_other_stages_have_no_debt(self):
        for sid in ('deckhand', 'engineer', 'captain'):
            self.assertEqual(self.progs[sid]['debt'], 0.0)

    def test_all_stages_start_on_nights(self):
        for sid in STAGE_IDS:
            self.assertEqual(self.progs[sid]['phase'], 'nights')

    def test_clean_shifts_zero(self):
        for sid in STAGE_IDS:
            self.assertEqual(self.progs[sid]['clean_shifts'], 0)

    def test_shift_num_one(self):
        for sid in STAGE_IDS:
            self.assertEqual(self.progs[sid]['shift_num'], 1)

    def test_story_not_seen(self):
        for sid in STAGE_IDS:
            self.assertFalse(self.progs[sid]['story_seen'])

    def test_no_earnings(self):
        for sid in STAGE_IDS:
            self.assertEqual(self.progs[sid]['total_earnings'], 0.0)

    def test_returns_independent_copies(self):
        a = default_progressions()
        b = default_progressions()
        a['operator']['clean_shifts'] = 99
        self.assertEqual(b['operator']['clean_shifts'], 0)


class TestSaveCampaign(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'campaign.json')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_creates_file(self):
        save_campaign(self.path, 'operator', default_progressions())
        self.assertTrue(os.path.exists(self.path))

    def test_creates_missing_parent_directories(self):
        nested = os.path.join(self.tmp, 'a', 'b', 'saves', 'campaign.json')
        save_campaign(nested, 'operator', default_progressions())
        self.assertTrue(os.path.exists(nested))

    def test_file_is_valid_json(self):
        save_campaign(self.path, 'operator', default_progressions())
        with open(self.path) as fh:
            raw = json.load(fh)
        self.assertIsInstance(raw, dict)

    def test_json_contains_version(self):
        save_campaign(self.path, 'operator', default_progressions())
        with open(self.path) as fh:
            raw = json.load(fh)
        self.assertIn('version', raw)
        self.assertEqual(raw['version'], 1)

    def test_json_contains_active_stage_id(self):
        save_campaign(self.path, 'deckhand', default_progressions())
        with open(self.path) as fh:
            raw = json.load(fh)
        self.assertEqual(raw['active_stage_id'], 'deckhand')

    def test_json_contains_progressions(self):
        save_campaign(self.path, 'operator', default_progressions())
        with open(self.path) as fh:
            raw = json.load(fh)
        self.assertIn('progressions', raw)
        self.assertIsInstance(raw['progressions'], dict)

    def test_overwrites_existing_file(self):
        save_campaign(self.path, 'operator', default_progressions())
        progs = default_progressions()
        progs['operator']['clean_shifts'] = 5
        save_campaign(self.path, 'deckhand', progs)
        with open(self.path) as fh:
            raw = json.load(fh)
        self.assertEqual(raw['active_stage_id'], 'deckhand')
        self.assertEqual(raw['progressions']['operator']['clean_shifts'], 5)


class TestLoadCampaign(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'campaign.json')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_file_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            load_campaign(os.path.join(self.tmp, 'nonexistent.json'))

    def test_round_trip_active_stage_id(self):
        save_campaign(self.path, 'engineer', default_progressions())
        data = load_campaign(self.path)
        self.assertEqual(data['active_stage_id'], 'engineer')

    def test_round_trip_numeric_values(self):
        progs = default_progressions()
        progs['operator']['clean_shifts']   = 3
        progs['operator']['total_earnings'] = 450.75
        progs['operator']['shift_num']      = 4
        save_campaign(self.path, 'operator', progs)
        data = load_campaign(self.path)
        op = data['progressions']['operator']
        self.assertEqual(op['clean_shifts'], 3)
        self.assertAlmostEqual(op['total_earnings'], 450.75)
        self.assertEqual(op['shift_num'], 4)

    def test_round_trip_phase(self):
        progs = default_progressions()
        progs['operator']['phase'] = 'days'
        save_campaign(self.path, 'operator', progs)
        data = load_campaign(self.path)
        self.assertEqual(data['progressions']['operator']['phase'], 'days')

    def test_round_trip_story_seen(self):
        progs = default_progressions()
        progs['deckhand']['story_seen'] = True
        save_campaign(self.path, 'deckhand', progs)
        data = load_campaign(self.path)
        self.assertTrue(data['progressions']['deckhand']['story_seen'])

    def test_all_stages_present_after_load(self):
        save_campaign(self.path, 'operator', default_progressions())
        data = load_campaign(self.path)
        for sid in STAGE_IDS:
            self.assertIn(sid, data['progressions'])

    def test_missing_stage_in_file_filled_with_defaults(self):
        # Simulate a save from an older version that lacked 'captain'
        partial = default_progressions()
        del partial['captain']
        raw = {'version': 1, 'active_stage_id': 'operator', 'progressions': partial}
        with open(self.path, 'w') as fh:
            json.dump(raw, fh)
        data = load_campaign(self.path)
        self.assertIn('captain', data['progressions'])
        self.assertEqual(data['progressions']['captain']['phase'], 'nights')

    def test_missing_key_in_stage_filled_with_default(self):
        # Simulate a save where 'debt' key didn't exist yet
        progs = default_progressions()
        del progs['deckhand']['debt']
        raw = {'version': 1, 'active_stage_id': 'operator', 'progressions': progs}
        with open(self.path, 'w') as fh:
            json.dump(raw, fh)
        data = load_campaign(self.path)
        self.assertIn('debt', data['progressions']['deckhand'])
        self.assertEqual(data['progressions']['deckhand']['debt'], 0.0)

    def test_returns_dict_with_expected_keys(self):
        save_campaign(self.path, 'operator', default_progressions())
        data = load_campaign(self.path)
        self.assertIn('active_stage_id', data)
        self.assertIn('progressions', data)


if __name__ == '__main__':
    unittest.main()