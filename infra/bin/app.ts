#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';

import { ReviewFoundationStack } from '../lib/foundation-stack';
import { PlatformStack } from '../lib/platform-stack';
import { resolvePlatformConfig } from '../lib/platform-config';

const app = new cdk.App();

// Account and region come from the ambient environment / CDK context; nothing
// is hard-coded (AGENTS.md, PRD sec 7). Deploy targets the recorded sandbox.
const account = process.env.AWS_ACCOUNT_ID ?? process.env.CDK_DEFAULT_ACCOUNT;
const region = process.env.AWS_REGION ?? process.env.CDK_DEFAULT_REGION ?? 'us-west-2';
const owner =
  (app.node.tryGetContext('owner') as string | undefined) ??
  process.env.PROJECT_OWNER ??
  'unspecified';

const config = resolvePlatformConfig(app);

const commonTags = {
  project: 'CSUB-SolutionsConsultingWorkflow',
  owner,
  environment: config.appEnv,
  'data-classification': 'sanitized-prototype',
};

// Preserve the existing deployed ReviewFoundationStack logical IDs untouched.
const foundationStack = new ReviewFoundationStack(app, 'ReviewFoundationStack', {
  env: { account, region },
  // This sandbox is subject to an Organizations SCP that blocks the default
  // bootstrap execution role. Deployments therefore use the caller's scoped
  // GitHub OIDC or SSO credentials directly.
  synthesizer: new cdk.CliCredentialsStackSynthesizer(),
  terminationProtection: true,
  appEnv: config.appEnv,
  retentionDays: config.retentionDays,
  description: 'CSUB Technology Review Agent storage foundation (prototype).',
  tags: commonTags,
});

new PlatformStack(app, 'PlatformStack', {
  env: { account, region },
  synthesizer: new cdk.CliCredentialsStackSynthesizer(),
  terminationProtection: true,
  foundationStack,
  config,
  description: 'CSUB Technology Review Agent demo platform (prototype).',
  tags: commonTags,
});

app.synth();
