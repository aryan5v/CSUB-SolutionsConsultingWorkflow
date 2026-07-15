import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';

import { ReviewFoundationStack } from '../lib/foundation-stack';
import { PlatformStack } from '../lib/platform-stack';
import { PlatformConfig, resolvePlatformConfig, toLogRetention } from '../lib/platform-config';

const baseConfig: PlatformConfig = {
  appEnv: 'test',
  retentionDays: 90,
  agentCoreNetworkMode: 'PUBLIC',
  embeddingDimension: 1024,
  policyDocumentsPrefix: 'policy/',
  enableGuardrail: true,
  serviceNowTableName: 'sc_req_item',
  budgetLimitUsd: 50,
  destroyOnRemoval: true,
};

function build(config: PlatformConfig): { platform: Template; foundation: Template } {
  const app = new cdk.App();
  const foundationStack = new ReviewFoundationStack(app, 'ReviewFoundationStack', {
    env: { account: '111111111111', region: 'us-west-2' },
    appEnv: config.appEnv,
    retentionDays: config.retentionDays,
  });
  const platformStack = new PlatformStack(app, 'PlatformStack', {
    env: { account: '111111111111', region: 'us-west-2' },
    foundationStack,
    config,
  });
  return {
    platform: Template.fromStack(platformStack),
    foundation: Template.fromStack(foundationStack),
  };
}

describe('PlatformStack — offline synthesis and core surface', () => {
  test('synthesizes offline without AWS credentials', () => {
    expect(() => build(baseConfig)).not.toThrow();
  });

  test('provisions the required managed services', () => {
    const { platform } = build(baseConfig);
    platform.resourceCountIs('AWS::Cognito::UserPool', 1);
    platform.resourceCountIs('AWS::CloudFront::Distribution', 1);
    platform.resourceCountIs('AWS::ApiGatewayV2::Api', 1);
    platform.resourceCountIs('AWS::ECR::Repository', 1);
    platform.resourceCountIs('AWS::Bedrock::Guardrail', 1);
    platform.resourceCountIs('AWS::Bedrock::GuardrailVersion', 1);
    platform.resourceCountIs('AWS::BedrockAgentCore::Memory', 1);
    platform.resourceCountIs('AWS::BedrockAgentCore::BrowserCustom', 1);
    platform.resourceCountIs('AWS::S3Vectors::VectorBucket', 2);
    platform.resourceCountIs('AWS::S3Vectors::Index', 2);
    platform.resourceCountIs('AWS::Budgets::Budget', 1);
    platform.resourceCountIs('AWS::CloudTrail::Trail', 1);
    platform.resourceCountIs('AWS::CloudWatch::Dashboard', 1);
  });
});

describe('CloudFront uses OAC, never OAI, and keeps the frontend private', () => {
  test('an Origin Access Control exists and no OAI is created', () => {
    const { platform } = build(baseConfig);
    platform.resourceCountIs('AWS::CloudFront::OriginAccessControl', 1);
    platform.resourceCountIs('AWS::CloudFront::CloudFrontOriginAccessIdentity', 0);
  });

  test('every bucket blocks all public access', () => {
    const { platform } = build(baseConfig);
    const buckets = platform.findResources('AWS::S3::Bucket');
    for (const bucket of Object.values(buckets)) {
      expect(bucket.Properties.PublicAccessBlockConfiguration).toEqual({
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      });
    }
  });
});

describe('Data model security invariants', () => {
  test('invite table is keyed by token_hash, never plaintext token', () => {
    const { platform } = build(baseConfig);
    platform.hasResourceProperties('AWS::DynamoDB::Table', {
      KeySchema: Match.arrayWith([{ AttributeName: 'token_hash', KeyType: 'HASH' }]),
    });
    const tables = platform.findResources('AWS::DynamoDB::Table');
    const attrNames = Object.values(tables).flatMap((t: any) =>
      t.Properties.AttributeDefinitions.map((a: any) => a.AttributeName),
    );
    expect(attrNames).not.toContain('token');
    expect(attrNames).not.toContain('token_plaintext');
  });

  test('reviewer profile uses immutable (user_id, version) keys', () => {
    const { platform } = build(baseConfig);
    platform.hasResourceProperties('AWS::DynamoDB::Table', {
      KeySchema: [
        { AttributeName: 'user_id', KeyType: 'HASH' },
        { AttributeName: 'version', KeyType: 'RANGE' },
      ],
    });
  });

  test('all platform tables enable point-in-time recovery', () => {
    const { platform } = build(baseConfig);
    const tables = platform.findResources('AWS::DynamoDB::Table');
    expect(Object.keys(tables).length).toBe(10);
    for (const t of Object.values(tables)) {
      expect(t.Properties.PointInTimeRecoverySpecification).toEqual({
        PointInTimeRecoveryEnabled: true,
      });
    }
  });
});

describe('API authorization boundaries', () => {
  test('a Cognito JWT authorizer exists', () => {
    const { platform } = build(baseConfig);
    platform.hasResourceProperties('AWS::ApiGatewayV2::Authorizer', {
      AuthorizerType: 'JWT',
    });
  });

  test('protected routes require the JWT authorizer; intake/slack are gateway-public', () => {
    const { platform } = build(baseConfig);
    const routes = Object.values(platform.findResources('AWS::ApiGatewayV2::Route')).map(
      (r: any) => r.Properties,
    );
    const byKey = new Map<string, any>(routes.map((r) => [r.RouteKey, r]));

    // Reviewer/admin routes are JWT-authorized.
    for (const key of ['POST /cases', 'GET /review-queue', 'POST /cases/{id}/review']) {
      expect(byKey.get(key).AuthorizationType).toBe('JWT');
      expect(byKey.get(key).AuthorizerId).toBeDefined();
    }
    // Public-at-gateway routes carry no Cognito authorizer.
    for (const key of ['GET /intake/{token}', 'POST /intake/{token}', 'POST /slack/events']) {
      expect(byKey.get(key).AuthorizationType ?? 'NONE').toBe('NONE');
      expect(byKey.get(key).AuthorizerId).toBeUndefined();
    }
  });
});

describe('Lambda proxy configuration', () => {
  test('runs Node 22 on ARM64 with a <= 1 MiB JSON metadata cap and presign TTL', () => {
    const { platform } = build(baseConfig);
    platform.hasResourceProperties('AWS::Lambda::Function', {
      Runtime: 'nodejs22.x',
      Architectures: ['arm64'],
      Handler: 'index.handler',
      Environment: {
        Variables: Match.objectLike({
          MAX_JSON_BYTES: '1048576',
          PRESIGN_TTL_SECONDS: '300',
        }),
      },
    });
    const maxBytes = 1048576;
    expect(maxBytes).toBeLessThanOrEqual(1024 * 1024);
  });

  test('ServiceNow mock targets sc_req_item by default', () => {
    const { platform } = build(baseConfig);
    platform.hasResourceProperties('AWS::Lambda::Function', {
      Environment: {
        Variables: Match.objectLike({ SERVICE_NOW_TABLE: 'sc_req_item' }),
      },
    });
  });
});

describe('IAM least privilege', () => {
  test('no policy grants Action:* or a broad service:* wildcard', () => {
    const { platform } = build(baseConfig);
    const collect = (doc: any): string[] =>
      doc.Statement.flatMap((s: any) =>
        typeof s.Action === 'string' ? [s.Action] : (s.Action ?? []),
      );
    const actions: string[] = [];
    for (const p of Object.values(platform.findResources('AWS::IAM::Policy'))) {
      actions.push(...collect((p as any).Properties.PolicyDocument));
    }
    for (const r of Object.values(platform.findResources('AWS::IAM::Role'))) {
      for (const p of (r as any).Properties.Policies ?? []) {
        actions.push(...collect(p.PolicyDocument));
      }
    }
    expect(actions.length).toBeGreaterThan(0);
    for (const a of actions) {
      expect(a).not.toBe('*');
      // No blanket "service:*" (prefix-scoped grants like s3:GetObject* are allowed).
      expect(/^[a-z0-9-]+:\*$/.test(a)).toBe(false);
    }
  });

  test('agent runtime trust policy pins SourceAccount (confused-deputy guard)', () => {
    const { platform } = build(baseConfig);
    platform.hasResourceProperties('AWS::IAM::Role', {
      AssumeRolePolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Principal: { Service: 'bedrock-agentcore.amazonaws.com' },
            Condition: Match.objectLike({
              StringEquals: Match.objectLike({ 'aws:SourceAccount': '111111111111' }),
            }),
          }),
        ]),
      },
    });
  });
});

describe('Retention, budget, and encryption', () => {
  test('log groups apply finite retention', () => {
    const { platform } = build(baseConfig);
    const groups = platform.findResources('AWS::Logs::LogGroup');
    expect(Object.keys(groups).length).toBeGreaterThanOrEqual(2);
    for (const g of Object.values(groups)) {
      expect((g as any).Properties.RetentionInDays).toBe(90);
    }
  });

  test('a parameterized monthly cost budget is created', () => {
    const { platform } = build({ ...baseConfig, budgetLimitUsd: 75 });
    platform.hasResourceProperties('AWS::Budgets::Budget', {
      Budget: Match.objectLike({
        BudgetType: 'COST',
        TimeUnit: 'MONTHLY',
        BudgetLimit: { Amount: 75, Unit: 'USD' },
      }),
    });
  });

  test('budget notification subscriber only appears when an email is configured', () => {
    const withoutEmail = build(baseConfig).platform;
    const budgetNoEmail = Object.values(
      withoutEmail.findResources('AWS::Budgets::Budget'),
    )[0] as any;
    expect(budgetNoEmail.Properties.NotificationsWithSubscribers).toBeUndefined();

    const withEmail = build({ ...baseConfig, budgetNotificationEmail: 'owner@example.edu' })
      .platform;
    withEmail.hasResourceProperties('AWS::Budgets::Budget', {
      NotificationsWithSubscribers: Match.arrayWith([
        Match.objectLike({
          Subscribers: [{ SubscriptionType: 'EMAIL', Address: 'owner@example.edu' }],
        }),
      ]),
    });
  });

  test('seven-day AgentCore memory with a pinned guardrail version', () => {
    const { platform } = build(baseConfig);
    platform.hasResourceProperties('AWS::BedrockAgentCore::Memory', {
      EventExpiryDuration: 7,
    });
    platform.hasResourceProperties('AWS::Bedrock::GuardrailVersion', {
      GuardrailIdentifier: Match.anyValue(),
    });
  });
});

describe('Deployment gates', () => {
  test('AgentCore Runtime/Endpoint only synthesize with a configured image URI', () => {
    const gated = build(baseConfig).platform;
    gated.resourceCountIs('AWS::BedrockAgentCore::Runtime', 0);
    gated.resourceCountIs('AWS::BedrockAgentCore::RuntimeEndpoint', 0);

    const configured = build({
      ...baseConfig,
      agentCoreImageUri:
        '111111111111.dkr.ecr.us-west-2.amazonaws.com/csub-review-agent-test@sha256:' +
        'a'.repeat(64),
    }).platform;
    configured.resourceCountIs('AWS::BedrockAgentCore::Runtime', 1);
    configured.resourceCountIs('AWS::BedrockAgentCore::RuntimeEndpoint', 1);
    configured.hasResourceProperties('AWS::BedrockAgentCore::Runtime', {
      ProtocolConfiguration: 'HTTP',
      NetworkConfiguration: { NetworkMode: 'PUBLIC' },
      RequestHeaderConfiguration: {
        RequestHeaderAllowlist: Match.arrayWith(['X-Correlation-Id', 'Content-Type']),
      },
    });
  });

  test('Knowledge Bases only synthesize when an embedding model ARN is configured', () => {
    build(baseConfig).platform.resourceCountIs('AWS::Bedrock::KnowledgeBase', 0);
    const configured = build({
      ...baseConfig,
      embeddingModelArn: 'arn:aws:bedrock:us-west-2::foundation-model/placeholder-embed',
    }).platform;
    configured.resourceCountIs('AWS::Bedrock::KnowledgeBase', 2);
  });

  test('no Slack secret is referenced or generated unless imported by ARN', () => {
    const { platform } = build(baseConfig);
    platform.resourceCountIs('AWS::SecretsManager::Secret', 0);
    const lambdas = platform.findResources('AWS::Lambda::Function');
    const proxyEnvs = Object.values(lambdas)
      .map((l: any) => l.Properties.Environment?.Variables ?? {})
      .filter((v: any) => v.EVIDENCE_BUCKET);
    for (const env of proxyEnvs) {
      expect(env.SLACK_SECRET_ARN).toBeUndefined();
    }
  });
});

describe('Foundation coordination', () => {
  test('foundation stable logical IDs are preserved (cases table, KMS key)', () => {
    const { foundation } = build(baseConfig);
    const tableIds = Object.keys(foundation.findResources('AWS::DynamoDB::Table'));
    expect(tableIds.some((id) => id.startsWith('CasesTable'))).toBe(true);
    foundation.resourceCountIs('AWS::KMS::Key', 1);
  });
});

describe('platform-config resolver', () => {
  test('rejects invalid retention and enum values', () => {
    const app = new cdk.App({ context: { retentionDays: '-5' } });
    expect(() => resolvePlatformConfig(app)).toThrow(/retentionDays/);
    const app2 = new cdk.App({ context: { agentCoreNetworkMode: 'PRIVATE' } });
    expect(() => resolvePlatformConfig(app2)).toThrow(/agentCoreNetworkMode/);
  });

  test('maps day counts to supported CloudWatch retention', () => {
    expect(toLogRetention(90)).toBe(90);
    expect(toLogRetention(45)).toBe(60);
  });
});
