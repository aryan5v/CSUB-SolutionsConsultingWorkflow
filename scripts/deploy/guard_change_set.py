#!/usr/bin/env python3
"""Fail closed on incomplete, destructive, or security-sensitive changes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SECURITY_SENSITIVE_TYPES = {
    "AWS::ApiGatewayV2::Authorizer",
    "AWS::ApiGatewayV2::Api",
    "AWS::ApiGatewayV2::Integration",
    "AWS::ApiGatewayV2::Route",
    "AWS::ApiGatewayV2::Stage",
    "AWS::CloudFront::Distribution",
    "AWS::CloudFront::Function",
    "AWS::CloudFront::OriginAccessControl",
    "AWS::Cognito::UserPool",
    "AWS::Cognito::UserPoolClient",
    "AWS::Cognito::UserPoolDomain",
    "AWS::DynamoDB::Table",
    "AWS::IAM::ManagedPolicy",
    "AWS::IAM::Policy",
    "AWS::IAM::Role",
    "AWS::KMS::Key",
    "AWS::Lambda::Permission",
    "AWS::Lambda::Url",
    "AWS::S3::Bucket",
    "AWS::S3::BucketPolicy",
    "AWS::SecretsManager::Secret",
    "AWS::SQS::Queue",
    "AWS::WAFv2::WebACL",
}


KNOWN_ACTIONS = {"Add", "Modify", "Remove", "Import", "Dynamic"}
SAFE_REPLACEMENTS = {"False"}
DESTRUCTIVE_POLICY_ACTIONS = {"Delete", "ReplaceAndDelete"}

# CDK injects a metadata-only resource (the analytics/version string) that
# CloudFormation reports with replacement=Conditional on essentially every
# synth. It provisions no infrastructure and is never destructive, so it is
# exempt from the action/replacement checks; otherwise it blocks every deploy.
CDK_METADATA_TYPE = "AWS::CDK::Metadata"


def change_findings(change_set: dict[str, Any]) -> list[str]:
    """Return reasons a prepared CloudFormation change set must not execute."""

    findings: list[str] = []
    for wrapper in change_set.get("Changes", []):
        resource = wrapper.get("ResourceChange", {})
        action = str(resource.get("Action", "Unknown"))
        logical_id = str(resource.get("LogicalResourceId", "Unknown"))
        resource_type = str(resource.get("ResourceType", "Unknown"))
        if resource_type == CDK_METADATA_TYPE:
            continue
        replacement_value = resource.get("Replacement")
        replacement = str(replacement_value) if replacement_value is not None else "Missing"
        policy_action = str(resource.get("PolicyAction", ""))

        if action not in KNOWN_ACTIONS or action in {"Remove", "Dynamic"}:
            findings.append(
                f"{logical_id} ({resource_type}) has blocked action={action}"
            )
        if action == "Modify" and replacement not in SAFE_REPLACEMENTS:
            findings.append(
                f"{logical_id} ({resource_type}) has replacement={replacement}"
            )
        if policy_action in DESTRUCTIVE_POLICY_ACTIONS:
            findings.append(
                f"{logical_id} ({resource_type}) has policy_action={policy_action}"
            )
        if resource_type in SECURITY_SENSITIVE_TYPES:
            findings.append(
                f"{logical_id} changes security-sensitive {resource_type}; use the "
                "documented human SSO deployment path"
            )
    return findings


def is_known_empty_change_set(change_set: dict[str, Any]) -> bool:
    status = str(change_set.get("Status", ""))
    reason = str(change_set.get("StatusReason", "")).lower()
    return (
        not change_set.get("Changes")
        and status == "FAILED"
        and "didn't contain changes" in reason
    )


def envelope_findings(change_set: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    status = str(change_set.get("Status", "Missing"))
    execution = str(change_set.get("ExecutionStatus", "Missing"))
    if status != "CREATE_COMPLETE":
        findings.append(f"change set status is {status}, not CREATE_COMPLETE")
    if execution != "AVAILABLE":
        findings.append(f"change set execution status is {execution}, not AVAILABLE")
    if change_set.get("NextToken"):
        findings.append("change-set response is paginated; inspect every page before deploy")
    if not isinstance(change_set.get("Changes"), list) or not change_set.get("Changes"):
        findings.append("completed change set contains no resource changes")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("change_set", type=Path)
    args = parser.parse_args(argv)

    change_set = json.loads(args.change_set.read_text(encoding="utf-8"))
    if is_known_empty_change_set(change_set):
        print("NO_CHANGES")
        return 10

    findings = envelope_findings(change_set) + change_findings(change_set)
    if findings:
        print("BLOCKED_CHANGE_SET", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 2

    print("SAFE_CHANGE_SET")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
