import unittest
from unittest.mock import Mock, patch
from service import upc_lookup as upc
from service.product_identity import make_context, build_queries

CODE = "825429254069"

class UpcTests(unittest.TestCase):
    def setUp(self):
        upc._CACHE.clear()
        self.item = {"upc": CODE, "ean": "0" + CODE, "brand": "John Hardy",
            "title": "Icon Bracelet with Blue Sapphire", "description": "Sterling silver bracelet",
            "model": "BUS9909044BSPXU2XL", "images": ["https://example.com/a.jpg"],
            "offers": [{"link": "https://example.com/product", "price": 100}]}
        self.context = make_context(brand="John Hardy", vendor_item_number="254069", upc_code=CODE,
            attributes={"metal_type": "STSILVER", "product_type": "Bracelets",
                        "center_stone_type": "Blue Sapphire"})
    def record(self):
        return upc.parse_record({"items": [self.item]}, CODE)
    def test_checksum_and_upc_ean_equivalence(self):
        self.assertTrue(upc.gtin(CODE))
        self.assertEqual(upc.gtin(CODE), upc.gtin("0" + CODE))
        self.assertFalse(upc.gtin("825429254068"))
        self.assertFalse(upc.gtin("254069"))
        self.assertNotEqual(upc.gtin(CODE), upc.gtin("20008236914225"))
    def test_full_structured_record(self):
        record = self.record()
        self.assertTrue(record["found"])
        self.assertEqual(record["model"], self.item["model"])
        self.assertEqual(len(record["offers"]), 1)
        self.assertEqual(record["images"], self.item["images"])
    def test_mismatched_or_duplicate_records_rejected(self):
        self.item["upc"] = "008236914221"
        self.item["ean"] = ""
        self.assertFalse(self.record()["found"])
        self.assertFalse(upc.parse_record({"items": [self.item, self.item]}, "008236914221")["found"])
    def test_conflicting_brand_or_material_rejected(self):
        record = self.record()
        record["brand"] = "Other"
        self.assertIsNone(upc.candidate_from_record(record, self.context))
        record["brand"] = "John Hardy"
        record["description"] = "18K gold bracelet"
        self.assertIsNone(upc.candidate_from_record(record, self.context))
    def test_ean_only_can_confirm_same_upc(self):
        self.item.pop("upc")
        record = self.record()
        self.assertIsNotNone(upc.candidate_from_record(record, self.context))
    def test_confirmed_title_and_model_enrich_queries(self):
        record = self.record()
        self.assertIsNotNone(upc.candidate_from_record(record, self.context))
        self.context["upc_record"] = record
        queries = build_queries(self.context)
        self.assertTrue(any(self.item["model"] in q for q in queries))
        self.assertTrue(any(self.item["title"] in q for q in queries))
    @patch.dict("os.environ", {}, clear=True)
    @patch("service.upc_lookup.requests.get")
    def test_trial_request_and_cache(self, get):
        response = Mock()
        response.json.return_value = {"code": "OK", "items": [self.item]}
        get.return_value = response
        self.assertTrue(upc.lookup(CODE)["found"])
        upc.lookup(CODE)
        get.assert_called_once()
        self.assertIn("/trial/lookup", get.call_args.args[0])
        self.assertNotIn("user_key", get.call_args.kwargs["headers"])
    @patch("service.upc_lookup.requests.get")
    def test_failure_does_not_crash(self, get):
        import requests
        get.side_effect = requests.HTTPError("429")
        self.assertFalse(upc.lookup(CODE)["found"])
        self.assertEqual(get.call_count, 1)

if __name__ == "__main__":
    unittest.main()
