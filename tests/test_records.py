import json
import unittest
from pathlib import Path
from src.records import load_records

class RecordsTest(unittest.TestCase):
    def test_public_fixture(self):
        value = load_records(Path("fixtures/context.json"))
        self.assertEqual(value["domain"], "navigation-standard-gap")
        self.assertGreaterEqual(len(value["gaps"]), 2)

    def test_fixture_matches_json_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("未安装 jsonschema，跳过契约校验")
        schema = json.loads(Path("contracts/domain.schema.json").read_text(encoding="utf-8"))
        data = json.loads(Path("fixtures/context.json").read_text(encoding="utf-8"))
        jsonschema.validate(data, schema)

if __name__ == "__main__":
    unittest.main()
