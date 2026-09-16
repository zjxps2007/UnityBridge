from __future__ import annotations

import unittest

from unity_bridge.host.context import PreparedContext
from unity_bridge.host.registry import normalized_project


class PreparedContextTests(unittest.TestCase):
    def context(self, references):
        return {"domainId": "domain-one", "referenceGeneration": 1, "languageVersion": "9.0",
                "projectPath": ".", "references": references}

    def test_reference_identity_is_order_independent_but_detects_path_and_mvid_changes(self):
        references = [{"path": "A.dll", "mvid": "a-one"}, {"path": "B.dll", "mvid": "b-one"}]
        original = PreparedContext.from_connector(self.context(references))
        reordered = PreparedContext.from_connector(self.context(list(reversed(references))))
        self.assertEqual(original.compiler_reference_generation, reordered.compiler_reference_generation)
        for changed in ({"path": "A.dll", "mvid": "a-two"}, {"path": "Other.dll", "mvid": "a-one"}):
            with self.subTest(changed=changed):
                refreshed = PreparedContext.from_connector(self.context([changed, references[1]]))
                self.assertNotEqual(original.compiler_reference_generation, refreshed.compiler_reference_generation)

    def test_prepared_context_owns_negotiated_reference_snapshot(self):
        references = [{"path": "A.dll", "mvid": "a-one", "name": "A"}]
        context = self.context(references)
        prepared = PreparedContext.from_connector(context)
        references[0]["mvid"] = "a-two"
        references.append({"path": "B.dll", "mvid": "b-one"})
        context["domainId"] = "domain-two"
        self.assertEqual(prepared.references, [{"path": "A.dll", "mvid": "a-one", "name": "A"}])
        self.assertEqual(prepared.domain_id, "domain-one")
        self.assertEqual(prepared.project_id, normalized_project("."))


if __name__ == "__main__":
    unittest.main()
