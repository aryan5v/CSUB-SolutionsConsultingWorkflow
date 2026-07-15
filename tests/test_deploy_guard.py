from __future__ import annotations

import unittest

from scripts.deploy.guard_change_set import (
    change_findings,
    envelope_findings,
    is_known_empty_change_set,
)


def change(
    *,
    action: str = "Modify",
    replacement: str = "False",
    resource_type: str = "AWS::Lambda::Function",
) -> dict:
    return {
        "ResourceChange": {
            "Action": action,
            "LogicalResourceId": "Example",
            "Replacement": replacement,
            "ResourceType": resource_type,
        }
    }


class DeploymentChangeGuardTests(unittest.TestCase):
    def test_allows_non_replacing_application_update(self) -> None:
        self.assertEqual(change_findings({"Changes": [change()]}), [])

    def test_blocks_removal_and_conditional_replacement(self) -> None:
        findings = change_findings(
            {
                "Changes": [
                    change(action="Remove"),
                    change(replacement="Conditional"),
                ]
            }
        )
        self.assertEqual(len(findings), 2)
        self.assertIn("blocked action=Remove", findings[0])
        self.assertIn("replacement=Conditional", findings[1])

    def test_security_change_requires_human_sso_path(self) -> None:
        payload = {
            "Changes": [change(resource_type="AWS::IAM::Policy")],
        }
        self.assertEqual(len(change_findings(payload)), 1)
        self.assertIn("human SSO deployment path", change_findings(payload)[0])

    def test_blocks_api_lambda_url_bucket_and_cloudfront_security_surfaces(self) -> None:
        for resource_type in (
            "AWS::ApiGatewayV2::Route",
            "AWS::Lambda::Url",
            "AWS::S3::Bucket",
            "AWS::CloudFront::Distribution",
        ):
            with self.subTest(resource_type=resource_type):
                self.assertTrue(
                    change_findings({"Changes": [change(resource_type=resource_type)]})
                )

    def test_recognizes_cloudformation_no_change_result(self) -> None:
        self.assertTrue(
            is_known_empty_change_set(
                {
                    "Status": "FAILED",
                    "StatusReason": "The submitted information didn't contain changes.",
                    "Changes": [],
                }
            )
        )

    def test_failed_or_incomplete_change_sets_fail_closed(self) -> None:
        self.assertTrue(envelope_findings({"Status": "FAILED", "Changes": []}))
        self.assertTrue(
            envelope_findings(
                {
                    "Status": "CREATE_COMPLETE",
                    "ExecutionStatus": "AVAILABLE",
                    "Changes": [change()],
                    "NextToken": "more",
                }
            )
        )

    def test_blocks_unknown_dynamic_and_missing_replacement(self) -> None:
        payload = {
            "Changes": [
                change(action="Dynamic"),
                change(action="Unknown"),
                {
                    "ResourceChange": {
                        "Action": "Modify",
                        "LogicalResourceId": "MissingReplacement",
                        "ResourceType": "AWS::Lambda::Function",
                    }
                },
            ]
        }
        findings = change_findings(payload)
        self.assertEqual(len(findings), 3)

    def test_blocks_destructive_policy_action(self) -> None:
        payload = {"Changes": [change()]}
        payload["Changes"][0]["ResourceChange"]["PolicyAction"] = "ReplaceAndDelete"
        self.assertIn("policy_action=ReplaceAndDelete", change_findings(payload)[0])

    def test_accepts_only_complete_available_change_set(self) -> None:
        payload = {
            "Status": "CREATE_COMPLETE",
            "ExecutionStatus": "AVAILABLE",
            "Changes": [change()],
        }
        self.assertEqual(envelope_findings(payload), [])


if __name__ == "__main__":
    unittest.main()
