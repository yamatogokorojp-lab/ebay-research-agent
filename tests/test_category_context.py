"""Regression tests for stale Streamlit session-state category assignments."""
import unittest

from category_fees import (category_product_fingerprint,
                           reconcile_category_context, category_choice_is_current)


class CategoryContextTests(unittest.TestCase):
    def setUp(self):
        self.watch = {'sku': 'SKU-1', 'title': 'Seiko SND379P1', 'brand': 'SEIKO', 'model': 'SND379P1'}
        self.identity = category_product_fingerprint(self.watch)
        self.choice = {'category_id': '31387', '_category_query': self.watch['title'], '_identity': self.identity}

    def test_retains_selection_for_same_product(self):
        identities = {'SKU-1': self.identity}
        suggestions = {'SKU-1': {'query': 'Seiko SND379P1'}}
        choices = {'SKU-1': dict(self.choice)}
        changed = reconcile_category_context([dict(self.watch)], identities, suggestions, choices)
        self.assertEqual(changed, set())
        self.assertIn('SKU-1', choices)

    def test_changed_title_invalidates_same_sku(self):
        identities = {'SKU-1': self.identity}
        suggestions = {'SKU-1': {'query': 'Seiko SND379P1'}}
        choices = {'SKU-1': dict(self.choice)}
        changed = reconcile_category_context([dict(self.watch, title='Sony RM-DR1J')], identities, suggestions, choices)
        self.assertEqual(changed, {'SKU-1'})
        self.assertNotIn('SKU-1', choices)
        self.assertNotIn('SKU-1', suggestions)

    def test_changed_brand_and_model_invalidate(self):
        for key, value in [('brand', 'CASIO'), ('model', 'SND409')]:
            with self.subTest(key=key):
                identities = {'SKU-1': self.identity}
                choices = {'SKU-1': dict(self.choice)}
                reconcile_category_context([dict(self.watch, **{key: value})], identities, {}, choices)
                self.assertEqual(choices, {})

    def test_removed_sku_invalidates_and_cleans_seen(self):
        identities = {'SKU-1': self.identity}
        choices = {'SKU-1': dict(self.choice)}
        changed = reconcile_category_context([{'sku':'SKU-2', 'title':'camera'}], identities, {}, choices)
        self.assertIn('SKU-1', changed)
        self.assertEqual(choices, {})
        self.assertNotIn('SKU-1', identities)

    def test_preexisting_choice_without_identity_is_untrusted(self):
        identities = {}
        choices = {'SKU-1': dict(self.choice)}
        reconcile_category_context([self.watch], identities, {}, choices)
        self.assertEqual(choices, {})

    def test_changed_query_or_product_disallows_old_selection(self):
        self.assertTrue(category_choice_is_current(self.choice, 'Seiko SND379P1', self.identity))
        self.assertFalse(category_choice_is_current(self.choice, 'Seiko SND409', self.identity))
        self.assertFalse(category_choice_is_current(self.choice, 'Seiko SND379P1', ('changed','seiko','snd379p1')))
        self.assertFalse(category_choice_is_current({'category_id':'31387'}, 'Seiko SND379P1', self.identity))
        self.assertFalse(category_choice_is_current(None, 'Seiko SND379P1', self.identity))

    def test_trivial_whitespace_and_case_do_not_invalidate(self):
        self.assertEqual(category_product_fingerprint(self.watch), category_product_fingerprint(
            dict(self.watch, title=' seiko   snd379p1 ', brand=' seiko ')))


if __name__ == '__main__':
    unittest.main()
