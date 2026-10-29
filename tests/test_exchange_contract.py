import ast
import hashlib
import unittest
from pathlib import Path

BASELINE = {'JewelryRequest': '8fbafac50674a26f94683d07180040c07a5cc21176ddabd16edab788ec458a21', 'ImageEvidence': '90c111ec5b4372201c444ed8f3d5ed92285a66bbb3f29cf48cc22e57d245e9c5', 'LookupInfo': '792fce69ce0bf9a926d3d79341e4c5290933e1fb6d3317ed3900d88786e3cf3e', 'ConfidenceInfo': 'ea651b8e6348490daeb84c1883be65750d4726ece5428404d84f6f430763965f', 'JewelryAttributes': '26bbbf913abd0ef87389f5f8ae39bf99d918f92037e500c83e62e22c39cebde2', 'WatchAttributes': '50901004966f087fc022e89384d64948daaa77548a469651848f2f1586981fa1', 'InvoiceLineItem': '59d0a58de3978ba281a71c0c9dd9354d46832cfe7953f6feaadf2aacc15c7340', 'InvoiceResponse': '2c8c5abd665371e67d3f1e650f2da192507b0a4fbdaaa42e84fdc866b9e9dd08', 'parse_invoice': '94104c8516ebbbfb0a57c2bad069bc95a50d6032d4de36f7a379e681ac681ea1'}
PROMPTS = {'INVOICE_VISION_PROMPT': '1540e6248e99be6c9278e1aaf6965d55c860e992b88461b0a5d6427abfff0fdf', 'INVOICE_EXTRACTION_PROMPT': '4e02065c662647b9ea22025c120272e58f7a812d86a5980fb287dc9ad812f829'}

class ExchangeContractTests(unittest.TestCase):
    def test_models_invoice_handler_and_prompts_unchanged(self):
        tree = ast.parse(Path("service/api.py").read_text())
        found = {}
        for node in tree.body:
            name = getattr(node, "name", None)
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
            if name in BASELINE or name in PROMPTS:
                found[name] = hashlib.sha256(ast.dump(node).encode()).hexdigest()
        self.assertEqual(found, dict(BASELINE, **PROMPTS))
