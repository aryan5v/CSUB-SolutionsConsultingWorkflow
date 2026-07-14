#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';

import { ReviewFoundationStack } from '../lib/foundation-stack';

const app = new cdk.App();

// Account and region come from the ambient environment / CDK context; nothing
// is hard-coded (AGENTS.md, PRD sec 7). Deploy targets the recorded sandbox.
const account = process.env.CDK_DEFAULT_ACCOUNT;
const region = process.env.CDK_DEFAULT_REGION ?? process.env.AWS_REGION ?? 'us-east-1';
const appEnv =
  (app.node.tryGetContext('appEnv') as string | undefined) ?? process.env.APP_ENV ?? 'development';
const owner =
  (app.node.tryGetContext('owner') as string | undefined) ?? process.env.PROJECT_OWNER ?? 'unspecified';

new ReviewFoundationStack(app, 'ReviewFoundationStack', {
  env: { account, region },
  // The Innovation Sandbox SCP denies actions performed by CDK's bootstrap
  // cfn-exec-role, but NOT by the deploying SSO identity (verified: that identity
  // can create/tag IAM roles directly). Deploy with the CLI's own credentials so
  // CloudFormation acts as that permitted identity instead of the blocked role.
  synthesizer: new cdk.CliCredentialsStackSynthesizer(),
  appEnv,
  description: 'CSUB Technology Review Agent storage foundation (prototype).',
  tags: {
    project: 'CSUB-SolutionsConsultingWorkflow',
    owner,
    environment: appEnv,
    'data-classification': 'sanitized-prototype',
  },
});

app.synth();
