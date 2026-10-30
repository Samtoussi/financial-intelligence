import copy
import json
import unittest

from src.evaluation.ground_truth import load_dataset, unique_object, validate, yoy


class GroundTruthTests(unittest.TestCase):
    def setUp(self):
        self.data = copy.deepcopy(load_dataset())

    def test_correct_dataset(self):
        self.assertEqual(validate(self.data), {
            'revenue': '18.8', 'operating_income': '21.0', 'net_income': '32.0',
            'diluted_eps': '32.3', 'agents_and_infra_revenue': '24.5',
            'devices_and_consumer_revenue': '-3.2'})

    def test_corrupted_metric(self):
        self.data['metrics'][2]['current']['value'] = '99999'
        with self.assertRaisesRegex(ValueError, 'income ordering'):
            validate(self.data)

    def test_invalid_values(self):
        for value in ['NaN', 'Infinity', '-1', '0', '', '1,000', '1e3', True, None, 92279]:
            with self.subTest(value=value):
                self.data['metrics'][0]['current']['value'] = value
                with self.assertRaises(ValueError):
                    validate(self.data)

    def test_missing_citation(self):
        del self.data['metrics'][0]['source']
        with self.assertRaisesRegex(ValueError, 'citation'):
            validate(self.data)

    def test_incomplete_citation(self):
        self.data['metrics'][0]['source']['row'] = ' '
        with self.assertRaisesRegex(ValueError, 'citation row'):
            validate(self.data)

    def test_incorrect_segment_total(self):
        for period in ['current', 'prior']:
            with self.subTest(period=period):
                data = copy.deepcopy(self.data)
                data['metrics'][4][period]['value'] = '60000'
                with self.assertRaisesRegex(ValueError, f'segment total: {period}'):
                    validate(data)

    def test_duplicate_metric(self):
        self.data['metrics'].append(copy.deepcopy(self.data['metrics'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate metric'):
            validate(self.data)

    def test_missing_metric(self):
        self.data['metrics'].pop()
        with self.assertRaisesRegex(ValueError, 'metric IDs'):
            validate(self.data)

    def test_inconsistent_period(self):
        self.data['metrics'][1]['prior']['period']['end'] = '2024-09-30'
        with self.assertRaisesRegex(ValueError, 'periods'):
            validate(self.data)

    def test_inconsistent_units(self):
        self.data['metrics'][3]['unit'] = 'USD millions'
        with self.assertRaisesRegex(ValueError, 'units'):
            validate(self.data)

    def test_incorrect_source_url(self):
        self.data['metrics'][0]['source']['url'] = 'https://example.com'
        with self.assertRaisesRegex(ValueError, 'citation URL'):
            validate(self.data)

    def test_invalid_precision(self):
        self.data['metrics'][0]['current']['value'] = '92279.1'
        with self.assertRaisesRegex(ValueError, 'precision'):
            validate(self.data)

    def test_premature_review_conclusion(self):
        self.data['qualitative_review_cases'][0]['status'] = 'reviewed'
        with self.assertRaisesRegex(ValueError, 'manual review'):
            validate(self.data)

    def test_duplicate_json_key(self):
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            json.loads('{"id": 1, "id": 2}', object_pairs_hook=unique_object)

    def test_decimal_display_rounding(self):
        self.assertEqual(yoy('101.25', '100'), '1.3')
        self.assertEqual(yoy('98.75', '100'), '-1.3')


if __name__ == '__main__':
    unittest.main()
