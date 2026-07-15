import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';

import { ReviewFoundationStack } from '../lib/foundation-stack';
import { PlatformStack } from '../lib/platform-stack';
import { PlatformConfig, resolvePlatformConfig, toLogRetention } from '../lib/platform-config';

const baseConfig: PlatformConfig = {
  appEnv: 'test',
  retentionDays: 90,
  enableAgentCoreServices: false,
  enableVectorStores: false,
  agentCoreNetworkMode: 'PUBLIC',
  embeddingDimension: 1024,
  policyDocumentsPrefix: 'policy/',
  enableGuardrail: false,
  serviceNowTableName: 'sc_req_item',
  budgetLimitUsd: 50,
  destroyOnRemoval: true,
};

const enabledConfig: PlatformConfig = {
  ...baseConfig,
  enableAgentCoreServices: true,
  enableVectorStores: true,
  enableGuardrail: true,
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

  test('provisions the supported core while advanced services default off', () => {
    const { platform } = build(baseConfig);
    platform.resourceCountIs('AWS::Cognito::UserPool', 1);
    platform.resourceCountIs('AWS::CloudFront::Distribution', 1);
    platform.resourceCountIs('AWS::ApiGatewayV2::Api', 1);
    platform.resourceCountIs('AWS::Lambda::Function', 2);
    platform.resourceCountIs('AWS::DynamoDB::Table', 10);
    platform.resourceCountIs('AWS::S3::Bucket', 4);
    platform.resourceCountIs('AWS::SQS::Queue', 2);
    platform.resourceCountIs('AWS::ECR::Repository', 1);
    platform.resourceCountIs('AWS::Budgets::Budget', 1);
    platform.resourceCountIs('AWS::CloudTrail::Trail', 1);
    platform.resourceCountIs('AWS::CloudWatch::Dashboard', 1);
    platform.resourceCountIs('AWS::Bedrock::Guardrail', 0);
    platform.resourceCountIs('AWS::Bedrock::GuardrailVersion', 0);
    platform.resourceCountIs('AWS::BedrockAgentCore::Memory', 0);
    platform.resourceCountIs('AWS::BedrockAgentCore::BrowserCustom', 0);
    platform.resourceCountIs('AWS::BedrockAgentCore::Runtime', 0);
    platform.resourceCountIs('AWS::BedrockAgentCore::RuntimeEndpoint', 0);
    platform.resourceCountIs('AWS::S3Vectors::VectorBucket', 0);
    platform.resourceCountIs('AWS::S3Vectors::Index', 0);
    platform.resourceCountIs('AWS::Bedrock::KnowledgeBase', 0);
  });
});

describe('Cognito hosted UI supports the reviewer PKCE client', () => {
  const configuredDomainPrefix = 'csub-reviewer-test-unique';
  const localDevelopmentAppUrl = 'http://127.0.0.1:5173/app';

  test('uses a secretless authorization-code-only client with exact scopes and URLs', () => {
    const { platform } = build({ ...baseConfig, cognitoDomainPrefix: configuredDomainPrefix });
    const distributions = platform.findResources('AWS::CloudFront::Distribution');
    const distributionLogicalId = Object.keys(distributions)[0];
    const cloudFrontAppUrl = {
      'Fn::Join': [
        '',
        [
          'https://',
          { 'Fn::GetAtt': [distributionLogicalId, 'DomainName'] },
          '/app',
        ],
      ],
    };

    const domains = platform.findResources('AWS::Cognito::UserPoolDomain');
    const domainLogicalId = Object.keys(domains)[0];
    platform.resourceCountIs('AWS::Cognito::UserPoolDomain', 1);
    platform.hasResourceProperties('AWS::Cognito::UserPoolDomain', {
      Domain: configuredDomainPrefix,
      UserPoolId: Match.anyValue(),
    });

    const clients = Object.values(platform.findResources('AWS::Cognito::UserPoolClient'));
    expect(clients).toHaveLength(1);
    const properties = (clients[0] as any).Properties;
    expect(properties.GenerateSecret).toBe(false);
    expect(properties.AllowedOAuthFlowsUserPoolClient).toBe(true);
    expect(properties.AllowedOAuthFlows).toEqual(['code']);
    expect(properties.AllowedOAuthFlows).not.toContain('implicit');
    expect(properties.AllowedOAuthFlows).not.toContain('client_credentials');
    expect(properties.AllowedOAuthScopes).toEqual(['openid', 'email', 'profile']);
    expect(properties.SupportedIdentityProviders).toEqual(['COGNITO']);
    expect(properties.CallbackURLs).toEqual([cloudFrontAppUrl, localDevelopmentAppUrl]);
    expect(properties.LogoutURLs).toEqual([cloudFrontAppUrl, localDevelopmentAppUrl]);

    platform.hasOutput('CognitoDomainUrl', {
      Value: {
        'Fn::Join': [
          '',
          [
            'https://',
            { Ref: domainLogicalId },
            '.auth.us-west-2.amazoncognito.com',
          ],
        ],
      },
    });
  });

  test('derives a unique account-and-environment prefix when no override is supplied', () => {
    const { platform } = build(baseConfig);
    platform.hasResourceProperties('AWS::Cognito::UserPoolDomain', {
      Domain: 'csub-reviewer-test-111111111111',
    });
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

describe('CloudTrail audit bucket sandbox compatibility', () => {
  test('uses SSE-S3 for audit logs while evidence/generated remain KMS encrypted', () => {
    const { platform } = build(baseConfig);

    platform.hasResourceProperties('AWS::S3::Bucket', {
      BucketEncryption: {
        ServerSideEncryptionConfiguration: [
          { ServerSideEncryptionByDefault: { SSEAlgorithm: 'AES256' } },
        ],
      },
      LifecycleConfiguration: {
        Rules: Match.arrayWith([Match.objectLike({ Id: 'ExpireAudit', Status: 'Enabled' })]),
      },
      PublicAccessBlockConfiguration: {
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      },
      VersioningConfiguration: { Status: 'Enabled' },
    });

    for (const lifecycleId of ['ExpireEvidence', 'ExpireGeneratedVersions']) {
      platform.hasResourceProperties('AWS::S3::Bucket', {
        BucketEncryption: {
          ServerSideEncryptionConfiguration: [
            {
              ServerSideEncryptionByDefault: Match.objectLike({
                SSEAlgorithm: 'aws:kms',
                KMSMasterKeyID: Match.anyValue(),
              }),
            },
          ],
        },
        LifecycleConfiguration: {
          Rules: Match.arrayWith([Match.objectLike({ Id: lifecycleId, Status: 'Enabled' })]),
        },
      });
    }

    platform.resourceCountIs('AWS::CloudTrail::Trail', 1);
    const trails = Object.values(platform.findResources('AWS::CloudTrail::Trail'));
    expect(trails[0].Properties.S3BucketName).toBeDefined();
    expect(trails[0].Properties.KMSKeyId).toBeUndefined();
    platform.hasResourceProperties('AWS::S3::BucketPolicy', {
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: 's3:PutObject',
            Effect: 'Allow',
            Principal: { Service: 'cloudtrail.amazonaws.com' },
          }),
        ]),
      }),
    });
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
    for (const key of [
      'GET /health',
      'GET /vendor/invites/current',
      'POST /vendor/invites/current/open',
      'GET /vendor/invites/current/questions',
      'POST /vendor/invites/current/evidence',
      'POST /vendor/invites/current/trust-center',
      'POST /vendor/invites/current/answers',
      'POST /vendor/invites/current/coverage',
      'POST /vendor/invites/current/finalize',
      'GET /intake',
      'POST /intake',
      'POST /slack/events',
    ]) {
      expect(byKey.get(key).AuthorizationType ?? 'NONE').toBe('NONE');
      expect(byKey.get(key).AuthorizerId).toBeUndefined();
    }
    // No route embeds the invite token in the URL path or query.
    expect(routes.some((r) => String(r.RouteKey).includes('{token}'))).toBe(false);
    expect(routes.some((r) => /[?&](token|invite_token)=/.test(String(r.RouteKey)))).toBe(false);
    expect(byKey.has('GET /intake/{token}')).toBe(false);
  });

  test('uses one API-scoped Lambda invoke permission for all routes', () => {
    const { platform } = build(baseConfig);
    const permissions = Object.values(
      platform.findResources('AWS::Lambda::Permission'),
    ) as any[];
    const apiLogicalIds = Object.keys(platform.findResources('AWS::ApiGatewayV2::Api'));

    expect(permissions).toHaveLength(1);
    expect(apiLogicalIds).toHaveLength(1);
    expect(permissions[0].Properties.Action).toBe('lambda:InvokeFunction');
    expect(permissions[0].Properties.Principal).toBe('apigateway.amazonaws.com');
    const sourceArn = JSON.stringify(permissions[0].Properties.SourceArn);
    expect(sourceArn).toContain(JSON.stringify({ Ref: apiLogicalIds[0] }));
    expect(sourceArn).toContain('/*/*/*');
  });

  test('CORS permits bearer intake from only the UI and local development origins', () => {
    const { platform } = build(baseConfig);
    platform.hasResourceProperties('AWS::ApiGatewayV2::Api', {
      CorsConfiguration: Match.objectLike({
        AllowHeaders: ['Content-Type', 'Authorization', 'X-Correlation-Id'],
        AllowMethods: ['GET', 'POST', 'PATCH', 'DELETE', 'OPTIONS'],
        AllowOrigins: Match.arrayWith([
          'http://127.0.0.1:5173',
          'http://localhost:5173',
        ]),
      }),
    });
    const api = Object.values(platform.findResources('AWS::ApiGatewayV2::Api'))[0] as any;
    expect(api.Properties.CorsConfiguration.AllowOrigins).not.toContain('*');
  });
});

describe('Connected Lambda configuration', () => {
  test('runs Python 3.13 on ARM64 with deterministic source/layer packaging', () => {
    const { platform } = build(baseConfig);
    platform.hasResourceProperties('AWS::Lambda::Function', {
      Runtime: 'python3.13',
      Architectures: ['arm64'],
      Handler: 'review_agent.lambda_api.handler',
      MemorySize: 512,
      Environment: {
        Variables: Match.objectLike({
          CONTRACTS_SCHEMA_DIR: '/opt/schemas',
          WORKSPACE_ID: 'csub-demo',
          MAX_JSON_BYTES: '1048576',
          PRESIGN_TTL_SECONDS: '300',
          VENDOR_TABLE: Match.anyValue(),
          PRODUCT_TABLE: Match.anyValue(),
          CONTACT_TABLE: Match.anyValue(),
          INVITE_TABLE: Match.anyValue(),
          SUBMISSION_TABLE: Match.anyValue(),
          REVIEW_TABLE: Match.anyValue(),
          PROFILE_TABLE: Match.anyValue(),
          INTEGRATION_EVENT_TABLE: Match.anyValue(),
          AUDIT_TABLE: Match.anyValue(),
          IDEMPOTENCY_TABLE: Match.anyValue(),
        }),
      },
    });
    platform.resourceCountIs('AWS::Lambda::LayerVersion', 1);
    platform.hasResourceProperties('AWS::Lambda::LayerVersion', {
      CompatibleArchitectures: ['arm64'],
      CompatibleRuntimes: ['python3.13'],
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

  test('generated packet objects remain read-only to the case proxy', () => {
    const { platform } = build(baseConfig);
    const policies = Object.values(platform.findResources('AWS::IAM::Policy'));
    const putObjectStatements = policies.flatMap((policy: any) =>
      policy.Properties.PolicyDocument.Statement.filter((statement: any) => {
        const actions = Array.isArray(statement.Action) ? statement.Action : [statement.Action];
        return actions.includes('s3:PutObject');
      }),
    );
    expect(putObjectStatements.length).toBeGreaterThan(0);
    expect(JSON.stringify(putObjectStatements)).toContain('EvidenceBucket');
    expect(JSON.stringify(putObjectStatements)).not.toContain('GeneratedBucket');
  });

  test('agent runtime trust policy pins SourceAccount (confused-deputy guard)', () => {
    const { platform } = build(enabledConfig);
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

  test('seven-day AgentCore memory with a separately enabled pinned guardrail version', () => {
    const { platform } = build(enabledConfig);
    platform.hasResourceProperties('AWS::BedrockAgentCore::Memory', {
      EventExpiryDuration: 7,
    });
    platform.hasResourceProperties('AWS::Bedrock::GuardrailVersion', {
      GuardrailIdentifier: Match.anyValue(),
    });
  });
});

describe('Deployment gates', () => {
  const imageUri =
    '111111111111.dkr.ecr.us-west-2.amazonaws.com/csub-review-agent-test@sha256:' +
    'a'.repeat(64);
  const embeddingModelArn =
    'arn:aws:bedrock:us-west-2::foundation-model/placeholder-embed';

  test('default-off template contains no AgentCore resources, roles, policies, or endpoint env', () => {
    const platform = build(baseConfig).platform;
    platform.resourceCountIs('AWS::BedrockAgentCore::Memory', 0);
    platform.resourceCountIs('AWS::BedrockAgentCore::BrowserCustom', 0);
    platform.resourceCountIs('AWS::BedrockAgentCore::Runtime', 0);
    platform.resourceCountIs('AWS::BedrockAgentCore::RuntimeEndpoint', 0);
    const resources = platform.toJSON().Resources;
    expect(JSON.stringify(resources).toLowerCase()).not.toContain('bedrock-agentcore');
    expect(JSON.stringify(resources)).not.toContain('AGENT_RUNTIME_ENDPOINT_ARN');
    platform.hasOutput('AgentCoreServicesEnabled', { Value: 'false' });
    platform.hasOutput('AgentRuntimeConfigured', { Value: 'false' });
  });

  test('an image URI cannot bypass the disabled AgentCore master gate', () => {
    const platform = build({ ...baseConfig, agentCoreImageUri: imageUri }).platform;
    platform.resourceCountIs('AWS::BedrockAgentCore::Memory', 0);
    platform.resourceCountIs('AWS::BedrockAgentCore::BrowserCustom', 0);
    platform.resourceCountIs('AWS::BedrockAgentCore::Runtime', 0);
    platform.resourceCountIs('AWS::BedrockAgentCore::RuntimeEndpoint', 0);
    expect(JSON.stringify(platform.toJSON().Resources).toLowerCase()).not.toContain(
      'bedrock-agentcore',
    );
  });

  test('explicit AgentCore enablement preserves Memory/Browser and gates Runtime on image URI', () => {
    const servicesOnly = build({ ...baseConfig, enableAgentCoreServices: true }).platform;
    servicesOnly.resourceCountIs('AWS::BedrockAgentCore::Memory', 1);
    servicesOnly.resourceCountIs('AWS::BedrockAgentCore::BrowserCustom', 1);
    servicesOnly.resourceCountIs('AWS::BedrockAgentCore::Runtime', 0);
    servicesOnly.resourceCountIs('AWS::BedrockAgentCore::RuntimeEndpoint', 0);
    servicesOnly.hasOutput('AgentCoreServicesEnabled', { Value: 'true' });
    servicesOnly.hasOutput('AgentRuntimeConfigured', { Value: 'false' });

    const configured = build({
      ...baseConfig,
      enableAgentCoreServices: true,
      agentCoreImageUri: imageUri,
    }).platform;
    configured.resourceCountIs('AWS::BedrockAgentCore::Memory', 1);
    configured.resourceCountIs('AWS::BedrockAgentCore::BrowserCustom', 1);
    configured.resourceCountIs('AWS::BedrockAgentCore::Runtime', 1);
    configured.resourceCountIs('AWS::BedrockAgentCore::RuntimeEndpoint', 1);
    configured.hasResourceProperties('AWS::BedrockAgentCore::Runtime', {
      ProtocolConfiguration: 'HTTP',
      NetworkConfiguration: { NetworkMode: 'PUBLIC' },
      RequestHeaderConfiguration: {
        RequestHeaderAllowlist: Match.arrayWith(['X-Correlation-Id', 'Content-Type']),
      },
    });
    configured.hasResourceProperties('AWS::Lambda::Function', {
      Runtime: 'python3.13',
      Environment: {
        Variables: Match.objectLike({ AGENT_RUNTIME_ENDPOINT_ARN: Match.anyValue() }),
      },
    });
    const enabledPolicies = JSON.stringify(configured.findResources('AWS::IAM::Policy'));
    expect(enabledPolicies).toContain('bedrock-agentcore:InvokeAgentRuntime');
    configured.hasOutput('AgentRuntimeConfigured', { Value: 'true' });
  });

  test('default-off template contains no S3 Vectors, Knowledge Bases, KB role/policy, or KB alarm', () => {
    const platform = build({ ...baseConfig, embeddingModelArn }).platform;
    platform.resourceCountIs('AWS::S3Vectors::VectorBucket', 0);
    platform.resourceCountIs('AWS::S3Vectors::Index', 0);
    platform.resourceCountIs('AWS::Bedrock::KnowledgeBase', 0);
    const resources = JSON.stringify(platform.toJSON().Resources).toLowerCase();
    expect(resources).not.toContain('s3vectors:');
    expect(resources).not.toContain('kbingestionfailurealarm');
    platform.hasOutput('VectorStoresEnabled', { Value: 'false' });
    platform.hasOutput('KnowledgeBasesConfigured', { Value: 'false' });
  });

  test('explicit vector enablement preserves stores and gates Knowledge Bases on embedding ARN', () => {
    const storesOnly = build({ ...baseConfig, enableVectorStores: true }).platform;
    storesOnly.resourceCountIs('AWS::S3Vectors::VectorBucket', 2);
    storesOnly.resourceCountIs('AWS::S3Vectors::Index', 2);
    storesOnly.resourceCountIs('AWS::Bedrock::KnowledgeBase', 0);
    storesOnly.hasOutput('VectorStoresEnabled', { Value: 'true' });
    storesOnly.hasOutput('KnowledgeBasesConfigured', { Value: 'false' });

    const configured = build({
      ...baseConfig,
      enableVectorStores: true,
      embeddingModelArn,
    }).platform;
    configured.resourceCountIs('AWS::S3Vectors::VectorBucket', 2);
    configured.resourceCountIs('AWS::S3Vectors::Index', 2);
    configured.resourceCountIs('AWS::Bedrock::KnowledgeBase', 2);
    configured.hasOutput('KnowledgeBasesConfigured', { Value: 'true' });
  });

  test('Guardrail remains an independent default-off gate', () => {
    const off = build(baseConfig).platform;
    off.resourceCountIs('AWS::Bedrock::Guardrail', 0);
    off.resourceCountIs('AWS::Bedrock::GuardrailVersion', 0);
    off.hasOutput('GuardrailEnabled', { Value: 'false' });

    const on = build({ ...baseConfig, enableGuardrail: true }).platform;
    on.resourceCountIs('AWS::Bedrock::Guardrail', 1);
    on.resourceCountIs('AWS::Bedrock::GuardrailVersion', 1);
    on.hasResourceProperties('AWS::Lambda::Function', {
      Runtime: 'python3.13',
      Environment: {
        Variables: Match.objectLike({
          GUARDRAIL_ID: Match.anyValue(),
          GUARDRAIL_VERSION: Match.anyValue(),
        }),
      },
    });
    on.hasOutput('GuardrailEnabled', { Value: 'true' });
  });

  test('Slack secret remains absent by default and gated env/IAM are restored when imported', () => {
    const { platform } = build(baseConfig);
    platform.resourceCountIs('AWS::SecretsManager::Secret', 0);
    const lambdas = platform.findResources('AWS::Lambda::Function');
    const proxyEnvs = Object.values(lambdas)
      .map((l: any) => l.Properties.Environment?.Variables ?? {})
      .filter((v: any) => v.EVIDENCE_BUCKET);
    for (const env of proxyEnvs) {
      expect(env.SLACK_SECRET_ARN).toBeUndefined();
    }

    const secretArn =
      'arn:aws:secretsmanager:us-west-2:111111111111:secret:csub/slack-test-AbCdEf';
    const withSlack = build({ ...baseConfig, slackSecretArn: secretArn }).platform;
    withSlack.resourceCountIs('AWS::SecretsManager::Secret', 0);
    withSlack.hasResourceProperties('AWS::Lambda::Function', {
      Runtime: 'python3.13',
      Environment: {
        Variables: Match.objectLike({ SLACK_SECRET_ARN: secretArn }),
      },
    });
    expect(JSON.stringify(withSlack.findResources('AWS::IAM::Policy'))).toContain(
      'secretsmanager:GetSecretValue',
    );
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
  test('service gates default false and Cognito/domain settings accept explicit context', () => {
    const keys = [
      'ENABLE_AGENTCORE_SERVICES',
      'ENABLE_VECTOR_STORES',
      'ENABLE_GUARDRAIL',
      'COGNITO_DOMAIN_PREFIX',
    ] as const;
    const previous = Object.fromEntries(keys.map((key) => [key, process.env[key]]));
    try {
      for (const key of keys) delete process.env[key];
      const defaults = resolvePlatformConfig(new cdk.App());
      expect(defaults.enableAgentCoreServices).toBe(false);
      expect(defaults.enableVectorStores).toBe(false);
      expect(defaults.enableGuardrail).toBe(false);
      expect(defaults.cognitoDomainPrefix).toBeUndefined();

      const enabled = resolvePlatformConfig(
        new cdk.App({
          context: {
            enableAgentCoreServices: true,
            enableVectorStores: true,
            enableGuardrail: true,
            cognitoDomainPrefix: 'configured-reviewer-domain',
          },
        }),
      );
      expect(enabled.enableAgentCoreServices).toBe(true);
      expect(enabled.enableVectorStores).toBe(true);
      expect(enabled.enableGuardrail).toBe(true);
      expect(enabled.cognitoDomainPrefix).toBe('configured-reviewer-domain');
    } finally {
      for (const key of keys) {
        const value = previous[key];
        if (value === undefined) delete process.env[key];
        else process.env[key] = value;
      }
    }
  });

  test('rejects invalid retention and enum values', () => {
    const app = new cdk.App({ context: { retentionDays: '-5' } });
    expect(() => resolvePlatformConfig(app)).toThrow(/retentionDays/);
    const app2 = new cdk.App({ context: { agentCoreNetworkMode: 'PRIVATE' } });
    expect(() => resolvePlatformConfig(app2)).toThrow(/agentCoreNetworkMode/);
    const app3 = new cdk.App({ context: { enableVectorStores: 'sometimes' } });
    expect(() => resolvePlatformConfig(app3)).toThrow(/enableVectorStores must be a boolean/);
    const app4 = new cdk.App({ context: { cognitoDomainPrefix: 'Invalid_Prefix' } });
    expect(() => resolvePlatformConfig(app4)).toThrow(/cognitoDomainPrefix/);
  });

  test('maps day counts to supported CloudWatch retention', () => {
    expect(toLogRetention(90)).toBe(90);
    expect(toLogRetention(45)).toBe(60);
  });
});
