"""Conservative product identity checks; no network or model calls."""
import re


def make_context(brand="", vendor_item_number="", manufacturer_item_number="",
                 upc_code="", description="", category="jewelry", attributes=None):
    attributes = attributes or {}
    return dict(brand=brand, vendor_item_number=vendor_item_number,
                manufacturer_item_number=manufacturer_item_number, upc_code=upc_code,
                description=description, category=category, attributes=attributes)

# Only these semantic fields are useful query qualifiers; nulls and unrelated
# BC fields must not turn into search terms.
QUERY_FIELDS = ("product_type", "center_stone_type", "stone_primary_color",
                "case_material", "watch_collection", "watch_brand")
METALS = {"STSILVER": "sterling silver", "STSTEEL": "stainless steel",
          "950PL": "platinum"}

def _tokens(value):
    return re.findall(r"[a-z0-9]+", str(value or "").lower())

def has_identifier(identifier, text):
    # Allow separators in printed references, never match a numeric substring.
    parts = _tokens(identifier)
    if not parts:
        return False
    pattern = r"(?<![a-z0-9])" + r"[\s-]*".join(map(re.escape, parts)) + r"(?![a-z0-9])"
    return bool(re.search(pattern, text.lower()))

def check_candidate(context, candidate):
    """Require brand and an identifier in page content, not a search query/URL."""
    text = candidate.get("verification_text", "")
    brand = " ".join(_tokens(context.get("brand")))
    brand_ok = bool(brand) and brand in " ".join(_tokens(text))
    identifiers = {
        key: str(context.get(key) or "").strip()
        for key in ("manufacturer_item_number", "vendor_item_number", "upc_code")
    }
    page_ids = candidate.get("identifiers") or {}
    def canonical(value):
        return "".join(_tokens(value))
    matches = [key for key, value in identifiers.items()
               if value and has_identifier(value, text) and
               any(canonical(value) == canonical(page_id) for page_id in page_ids.values() if page_id)]
    attrs = context.get("attributes") or {}
    expected = " ".join([context.get("description") or ""] +
        [str(attrs.get(k) or "") for k in QUERY_FIELDS] +
        [METALS.get(str(attrs.get("metal_type") or ""), "")]).lower()
    actual = (candidate.get("description") or "").lower()
    conflicts = []
    # Positive incompatibilities only; absent details are not contradictions.
    product_types = ("bracelet", "necklace", "earring", "ring", "watch")
    def types(value):
        return {kind for kind in product_types if re.search(r"\b" + kind + r"s?\b", value)}
    want, found = types(expected), types(candidate.get("product_title", "").lower())
    if want and found and want.isdisjoint(found):
        conflicts.append("Product type contradicts the supplied description.")
    if re.search(r"\b(sterling|silver|925)\b", expected) and re.search(r"\b(14|18|22)\s*k(?:t)?\b", actual) and not re.search(r"\b(silver|sterling|925)\b", actual):
        conflicts.append("Material contradicts the supplied silver description.")
    if "blue sapphire" in expected and any(x in actual for x in ("no stones", "no gemstones", "stone-free")):
        conflicts.append("Stone-free product contradicts the supplied sapphire description.")
    expected_clasp = re.search(r"\b(pusher|lobster)\s+clasp\b", expected)
    actual_clasp = re.search(r"\b(pusher|lobster)\s+clasp\b", actual)
    if expected_clasp and actual_clasp and expected_clasp[1] != actual_clasp[1]:
        conflicts.append("Clasp contradicts the supplied description.")
    if "blue sapphire" in expected and re.search(r"\b(red ruby|green emerald|black onyx)\b", actual) and "sapphire" not in actual:
        conflicts.append("Gemstone contradicts the supplied sapphire description.")
    # A manufacturer reference, when provided, cannot be replaced by a weak vendor ID.
    required = "manufacturer_item_number" if identifiers["manufacturer_item_number"] else None
    identifier_ok = (required in matches or "upc_code" in matches) if required else bool(matches)
    verified = brand_ok and identifier_ok and not conflicts
    return {"verified": verified, "matched_identifiers": matches,
            "brand_confirmed": brand_ok, "conflicts": conflicts,
            "reason": "Brand and identifier found in page content." if verified else
                      "Identity not confirmed or supplied description conflicts with page."}

def build_queries(context):
    brand = context.get("brand", "").strip()
    ids = [context.get(k, "").strip() for k in
           ("manufacturer_item_number", "upc_code", "vendor_item_number")]
    queries = []
    for value in ids:
        if value:
            # No invented identifiers or model-generated query terms.
            query = brand + ' "' + value.replace('"', "") + '"'
            if query not in queries:
                queries.append(query)
    attrs = context.get("attributes") or {}
    qualifiers = [str(attrs[k]) for k in QUERY_FIELDS if attrs.get(k)]
    if attrs.get("metal_type") in METALS:
        qualifiers.append(METALS[attrs["metal_type"]])
    description = " ".join((context.get("description", "") + " " + " ".join(qualifiers)).split())[:180]
    if queries and description:
        queries.insert(0, queries[0] + " " + description)
    return queries
