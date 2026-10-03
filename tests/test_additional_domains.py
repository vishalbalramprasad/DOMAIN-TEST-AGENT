import unittest

import engine
from domains import DOMAINS


class AdditionalDomainTests(unittest.TestCase):
    def test_food_delivery_domain(self):
        self.assert_domain_is_testable("food_delivery")

    def test_travel_domain(self):
        self.assert_domain_is_testable("travel")

    def test_telecom_domain(self):
        self.assert_domain_is_testable("telecom")

    def test_hotel_domain(self):
        self.assert_domain_is_testable("hotel")

    def assert_domain_is_testable(self, name):
        domain = DOMAINS[name]
        cases = engine.generate(domain)
        results = engine.execute(domain, cases, [])

        self.assertTrue(all(result["ok"] for result in results))
        self.assertEqual({case[0] for case in cases}, set(domain["rules"]))
        self.assertTrue(all(mutant["killed"] for mutant in engine.mutation(domain, cases)))

        comparison = engine.compare(name)
        self.assertEqual(len(domain["bugs"]), comparison["total"])
        self.assertEqual(100, comparison["rows"][0]["rate"])


if __name__ == "__main__":
    unittest.main()
