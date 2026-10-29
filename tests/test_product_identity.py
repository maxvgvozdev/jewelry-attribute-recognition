import unittest
from service.product_identity import make_context, build_queries, check_candidate, has_identifier

class ProductIdentityTests(unittest.TestCase):
    def setUp(self):
        self.context = make_context(
            brand="John Hardy", vendor_item_number="254069",
            attributes={"metal_type": "STSILVER", "product_type": "Bracelets",
                        "center_stone_type": "Blue Sapphire"})
    def candidate(self, **changes):
        result = dict(verification_text="John Hardy SKU 254069", identifiers={"sku": "254069"},
                      product_title="Icon Bracelet", description="Sterling silver bracelet with blue sapphire")
        result.update(changes)
        return result
    def test_bc_attributes_reach_query(self):
        query = build_queries(self.context)[0]
        self.assertIn("Blue Sapphire", query)
        self.assertIn("sterling silver", query)
        self.assertIn('"254069"', query)
    def test_reported_cross_bracelet_is_rejected(self):
        candidate = self.candidate(verification_text="John Hardy SKU BU98941",
             identifiers={"sku": "BU98941"}, product_title="Cross Bracelet",
             description="Sterling silver. Lobster clasp")
        self.assertFalse(check_candidate(self.context, candidate)["verified"])
    def test_exact_identifier_and_compatible_description(self):
        self.assertTrue(check_candidate(self.context, self.candidate())["verified"])
    def test_wrong_brand(self):
        self.assertFalse(check_candidate(self.context, self.candidate(
            verification_text="Other Brand SKU 254069"))["verified"])
    def test_no_numeric_substring_or_url_only_confirmation(self):
        self.assertFalse(has_identifier("254069", "825429254069"))
        self.assertFalse(check_candidate(self.context, self.candidate(
            verification_text="John Hardy bracelet", url="https://example.com/254069"))["verified"])
    def test_generated_identifier_needs_raw_page_corroboration(self):
        self.assertFalse(check_candidate(self.context, self.candidate(
            verification_text="John Hardy"))["verified"])
    def test_raw_mention_without_product_identifier_is_not_enough(self):
        self.assertFalse(check_candidate(self.context, self.candidate(
            identifiers={"sku": "BU98941"}))["verified"])
    def test_contradictory_type_and_material(self):
        for candidate in (self.candidate(product_title="Icon Necklace"),
                          self.candidate(description="18K yellow gold bracelet")):
            self.assertFalse(check_candidate(self.context, candidate)["verified"])
    def test_manufacturer_code_takes_priority(self):
        self.context["manufacturer_item_number"] = "BUS9909044BSPXU2XL"
        self.assertFalse(check_candidate(self.context, self.candidate())["verified"])
    def test_description_clasp_conflict(self):
        self.context["description"] = "Icon silver bracelet with pusher clasp"
        self.assertFalse(check_candidate(self.context, self.candidate(
            description="Silver bracelet with lobster clasp"))["verified"])
    def test_missing_optional_detail_is_not_a_conflict(self):
        self.assertTrue(check_candidate(self.context, self.candidate(description="Silver bracelet"))["verified"])

if __name__ == "__main__":
    unittest.main()
