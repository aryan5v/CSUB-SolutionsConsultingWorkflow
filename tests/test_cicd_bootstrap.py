from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CicdBootstrapTests(unittest.TestCase):
    def test_bootstrap_requires_repository_identity_and_validates_outputs(self) -> None:
        script = (ROOT / "scripts/deploy/bootstrap_github_oidc.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("${GITHUB_ORGANIZATION:?", script)
        self.assertIn("${GITHUB_REPOSITORY:?", script)
        self.assertNotIn("${GITHUB_ORGANIZATION:-aryan5v}", script)
        self.assertIn("Could not resolve the CloudFront distribution", script)
        self.assertIn("Could not resolve the CDKToolkit staging bucket", script)

    def test_delivery_iam_reads_are_scoped_to_application_stacks(self) -> None:
        template = (ROOT / "infra/cicd/github-oidc-role.yml").read_text(
            encoding="utf-8"
        )
        role_statement = template.split(
            "- Sid: ReadExistingRolesForTemplateEvaluation", maxsplit=1
        )[1].split("- Sid: ReadExistingPoliciesForTemplateEvaluation", maxsplit=1)[0]
        policy_statement = template.split(
            "- Sid: ReadExistingPoliciesForTemplateEvaluation", maxsplit=1
        )[1].split("\n\nOutputs:", maxsplit=1)[0]
        self.assertNotIn("Resource: '*'", role_statement)
        self.assertNotIn("Resource: '*'", policy_statement)
        self.assertIn("role/${FoundationStackName}-*", role_statement)
        self.assertIn("policy/${PlatformStackName}-*", policy_statement)
        self.assertNotIn("cloudformation:UpdateTerminationProtection", template)

    def test_run_blocks_do_not_interpolate_release_values_directly(self) -> None:
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('git checkout --detach "${{', workflow)
        self.assertNotIn('build_frontend.sh "${{', workflow)
        self.assertNotIn('git show -s --format=%ct "${{', workflow)
        self.assertNotIn("_deployment-state/${{", workflow)


if __name__ == "__main__":
    unittest.main()
