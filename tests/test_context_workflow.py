"""Exercise the real workflow function without loading Windows service dependencies."""
import ast
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

class HTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code, self.detail = status_code, detail

class Lookup:
    def __init__(self, **values):
        self.__dict__.update(cross_confirmed=False, **values)
    def dict(self):
        return self.__dict__

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(Path("service/api.py").read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_jewelry_workflow")
        self.search = Mock(return_value={"data": [{"url": "https://example.com/item",
            "description": "Silver bracelet", "images": [], "identity": {
                "verified": True, "matched_identifiers": ["vendor_item_number"]}}]})
        self.env = dict(Optional=__import__("typing").Optional,
            Dict=__import__("typing").Dict, Any=__import__("typing").Any,
            List=__import__("typing").List, JewelryRequest=object, ImageEvidence=object,
            LookupInfo=Lookup, HTTPException=HTTPException, logger=Mock(),
            _run_firecrawl_search=self.search, _run_firecrawl_scrape=self.search,
            _check_upc=Mock(return_value={"found": True}),
            _build_attributes_from_text_and_vision=Mock(return_value={"product_type": "Bracelets"}),
            _normalize_to_bc365=lambda key, value, category: value)
        exec(compile(ast.Module(body=[node], type_ignores=[]), "workflow", "exec"), self.env)
        self.payload = SimpleNamespace(category="Bracelets", brand="John Hardy",
            vendor_item_number="254069", manufacturer_item_number="", upc_code="",
            source_url="", description="Icon Silver 6.5mm with pusher clasp")

    def test_existing_bc_prefill_is_passed_to_search(self):
        attrs = {"metal_type": "STSILVER", "center_stone_type": "Blue Sapphire"}
        result = self.env["run_jewelry_workflow"](self.payload, attrs)
        context = self.search.call_args.args[1]
        self.assertEqual(context["attributes"]["center_stone_type"], "Blue Sapphire")
        self.assertEqual(context["attributes"]["product_type"], "Bracelets")
        self.assertEqual(context["description"], "")
        self.assertEqual(result["evidence"]["text"], "Silver bracelet")
        self.assertNotEqual(result["confidence"]["overall"], "high")

    def test_unverified_result_stops_before_attributes(self):
        self.search.return_value = {"data": [], "rejected": []}
        with self.assertRaises(HTTPException) as error:
            self.env["run_jewelry_workflow"](self.payload)
        self.assertEqual(error.exception.status_code, 404)
        self.env["_build_attributes_from_text_and_vision"].assert_not_called()

    def test_source_url_uses_same_context(self):
        self.payload.source_url = "https://example.com/item"
        self.env["run_jewelry_workflow"](self.payload, {"product_type": "Bracelets"})
        self.assertEqual(self.search.call_args.args[0], self.payload.source_url)
        self.assertEqual(self.search.call_args.args[1]["vendor_item_number"], "254069")

    def test_discovery_failure_is_distinct_from_no_match(self):
        self.search.side_effect = RuntimeError("service down")
        with self.assertRaises(HTTPException) as error:
            self.env["run_jewelry_workflow"](self.payload)
        self.assertEqual(error.exception.status_code, 502)

if __name__ == "__main__":
    unittest.main()
