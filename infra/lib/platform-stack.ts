import * as path from 'node:path';
import * as cdk from 'aws-cdk-lib';
import * as apigwv2 from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpUserPoolAuthorizer } from 'aws-cdk-lib/aws-apigatewayv2-authorizers';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as budgets from 'aws-cdk-lib/aws-budgets';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as cloudtrail from 'aws-cdk-lib/aws-cloudtrail';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3vectors from 'aws-cdk-lib/aws-s3vectors';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import { Construct } from 'constructs';

import { ReviewFoundationStack } from './foundation-stack';
import { PlatformConfig, toLogRetention } from './platform-config';

export interface PlatformStackProps extends cdk.StackProps {
  /** Coordinated foundation stack that owns the shared KMS key and stateful buckets/table. */
  readonly foundationStack: ReviewFoundationStack;
  /** Resolved, validated platform configuration and deployment gates. */
  readonly config: PlatformConfig;
}

/**
 * AWS-native demo platform for the CSUB Technology Review Agent prototype.
 *
 * Composed with — never mutating — {@link ReviewFoundationStack}: the shared
 * customer-managed KMS key is passed by object reference (no CloudFormation
 * exports / cross-stack `Fn::ImportValue`), so the foundation stack's stable
 * logical IDs are untouched and there are no brittle export dependencies.
 *
 * Security posture (issue #20 corrections):
 * - CloudFront uses Origin Access Control (OAC), never legacy OAI; the
 *   frontend bucket stays private (no website hosting, no public access).
 * - Invite tokens persist a `token_hash` only, never plaintext.
 * - Reviewer profiles are keyed by immutable `(user_id, version)`.
 * - Evidence uploads use case-scoped presigned S3 PUTs, not bytes through API
 *   Gateway; the JSON metadata surface is capped well under 1 MiB.
 * - The Lambda proxy reaches AgentCore via the SDK v3 data-plane client
 *   (SigV4), never `fetch`, and never forwards Host/Authorization.
 * - Slack credentials are imported from a configured secret ARN; no placeholder
 *   secret is ever generated. The ServiceNow mock needs no credential.
 * - IAM/KMS are least-privilege and resource-scoped; no `Action:*` or broad
 *   `service:*`.
 *
 * Deployment gates (see infra/DEPLOYMENT.md): AgentCore Runtime/Endpoint,
 * Knowledge Bases, and the Slack secret are only synthesized when their
 * required inputs are configured, so the template synthesizes and deploys
 * cleanly at every stage without institutional data or live model IDs.
 */
export class PlatformStack extends cdk.Stack {
  public readonly userPool: cognito.UserPool;
  public readonly userPoolClient: cognito.UserPoolClient;
  public readonly frontendBucket: s3.Bucket;
  public readonly evidenceBucket: s3.Bucket;
  public readonly generatedBucket: s3.Bucket;
  public readonly distribution: cloudfront.Distribution;
  public readonly tables: Record<string, dynamodb.Table> = {};
  public readonly ecrRepository: ecr.Repository;
  public readonly logEncryptionKey: kms.Key;
  public readonly proxyFunction: lambda.Function;
  public readonly api: apigwv2.HttpApi;
  public readonly analysisQueue: sqs.Queue;
  public readonly analysisDlq: sqs.Queue;
  public readonly guardrail?: bedrock.CfnGuardrail;
  public readonly agentRuntime?: agentcore.CfnRuntime;

  constructor(scope: Construct, id: string, props: PlatformStackProps) {
    super(scope, id, props);

    const { foundationStack, config } = props;
    const { appEnv, retentionDays } = config;
    const removalPolicy = config.destroyOnRemoval
      ? cdk.RemovalPolicy.DESTROY
      : cdk.RemovalPolicy.RETAIN;
    const autoDelete = config.destroyOnRemoval;

    // Shared, customer-managed key from the foundation stack (by reference).
    const dataKey = foundationStack.dataKey;

    // ====================================================================
    // Storage: evidence, generated packets, private frontend, audit
    // ====================================================================
    const bucketDefaults: s3.BucketProps = {
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: dataKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy,
      autoDeleteObjects: autoDelete,
    };

    this.evidenceBucket = new s3.Bucket(this, 'EvidenceBucket', {
      ...bucketDefaults,
      versioned: true,
      // Presigned PUT uploads originate from the reviewer SPA; scope CORS to
      // PUT/GET only. Origins are constrained at the presign step, not here.
      cors: [
        {
          allowedMethods: [s3.HttpMethods.PUT, s3.HttpMethods.GET],
          allowedOrigins: ['*'],
          allowedHeaders: ['*'],
          maxAge: 3000,
        },
      ],
      lifecycleRules: [
        { id: 'ExpireEvidence', expiration: cdk.Duration.days(retentionDays) },
        { id: 'AbortIncompleteUploads', abortIncompleteMultipartUploadAfter: cdk.Duration.days(1) },
      ],
    });

    this.generatedBucket = new s3.Bucket(this, 'GeneratedBucket', {
      ...bucketDefaults,
      versioned: true,
      lifecycleRules: [
        {
          id: 'ExpireGeneratedVersions',
          expiration: cdk.Duration.days(retentionDays),
          noncurrentVersionExpiration: cdk.Duration.days(retentionDays),
        },
      ],
    });

    // Private frontend origin — served only through CloudFront OAC. Static web
    // assets carry no institutional data, so SSE-S3 (not the shared customer
    // KMS key) is used: this is the recommended pattern for OAC-fronted origins
    // and keeps the foundation stack's KMS key policy untouched.
    this.frontendBucket = new s3.Bucket(this, 'FrontendBucket', {
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: true,
      removalPolicy,
      autoDeleteObjects: autoDelete,
    });

    const auditBucket = new s3.Bucket(this, 'AuditBucket', {
      ...bucketDefaults,
      versioned: true,
      lifecycleRules: [{ id: 'ExpireAudit', expiration: cdk.Duration.days(retentionDays) }],
    });

    // ====================================================================
    // DynamoDB records (PITR on every table; least-privilege access later)
    // ====================================================================
    const makeTable = (
      logicalId: string,
      partitionKey: dynamodb.Attribute,
      sortKey?: dynamodb.Attribute,
      ttlAttribute?: string,
    ): dynamodb.Table => {
      const table = new dynamodb.Table(this, logicalId, {
        partitionKey,
        sortKey,
        billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
        encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
        encryptionKey: dataKey,
        pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
        timeToLiveAttribute: ttlAttribute,
        removalPolicy,
      });
      this.tables[logicalId] = table;
      return table;
    };

    const str = (name: string): dynamodb.Attribute => ({
      name,
      type: dynamodb.AttributeType.STRING,
    });
    const num = (name: string): dynamodb.Attribute => ({
      name,
      type: dynamodb.AttributeType.NUMBER,
    });

    makeTable('VendorTable', str('vendor_id'));
    makeTable('ProductTable', str('product_id'), num('version'));
    makeTable('ContactTable', str('contact_id'));
    // Invites are keyed by an opaque token HASH — never the plaintext token.
    makeTable('InviteTable', str('token_hash'), undefined, 'expires_at');
    makeTable('SubmissionTable', str('submission_id'), str('case_id'));
    makeTable('ReviewTable', str('case_id'), num('decision_version'));
    // Reviewer profiles use immutable (user_id, version) keys.
    makeTable('ProfileTable', str('user_id'), num('version'));
    makeTable('IntegrationEventTable', str('event_id'), num('occurred_at'), 'ttl');
    makeTable('AuditTable', str('case_id'), num('sequence'));
    makeTable('IdempotencyTable', str('idempotency_key'), undefined, 'ttl');

    // ====================================================================
    // Cognito reviewer pool (no self-service signup)
    // ====================================================================
    this.userPool = new cognito.UserPool(this, 'ReviewerPool', {
      userPoolName: `csub-reviewer-${appEnv}`,
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      standardAttributes: {
        email: { required: true, mutable: false },
        fullname: { required: true, mutable: true },
      },
      passwordPolicy: {
        minLength: 12,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true,
      },
      mfa: cognito.Mfa.OPTIONAL,
      mfaSecondFactor: { sms: false, otp: true },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy,
    });

    this.userPoolClient = new cognito.UserPoolClient(this, 'ReviewerPoolClient', {
      userPool: this.userPool,
      authFlows: { userSrp: true },
      generateSecret: false,
      preventUserExistenceErrors: true,
      accessTokenValidity: cdk.Duration.hours(1),
      idTokenValidity: cdk.Duration.hours(1),
      refreshTokenValidity: cdk.Duration.days(1),
    });

    // ====================================================================
    // CloudFront distribution with Origin Access Control (OAC, not OAI)
    // ====================================================================
    this.distribution = new cloudfront.Distribution(this, 'FrontendDistribution', {
      comment: `CSUB reviewer frontend ${appEnv}`,
      defaultRootObject: 'index.html',
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
      minimumProtocolVersion: cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
      defaultBehavior: {
        // withOriginAccessControl provisions the OAC and the private bucket
        // policy automatically — the bucket is never made public.
        origin: origins.S3BucketOrigin.withOriginAccessControl(this.frontendBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        responseHeadersPolicy: cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
      },
      errorResponses: [
        // SPA fallback.
        { httpStatus: 403, responseHttpStatus: 200, responsePagePath: '/index.html' },
        { httpStatus: 404, responseHttpStatus: 200, responsePagePath: '/index.html' },
      ],
    });

    // ====================================================================
    // ECR repository for the ARM64 HTTP AgentCore runtime image
    // ====================================================================
    this.ecrRepository = new ecr.Repository(this, 'AgentRuntimeRepository', {
      repositoryName: `csub-review-agent-${appEnv}`,
      imageScanOnPush: true,
      imageTagMutability: ecr.TagMutability.IMMUTABLE,
      encryption: ecr.RepositoryEncryption.KMS,
      encryptionKey: dataKey,
      removalPolicy,
      emptyOnDelete: autoDelete,
      lifecycleRules: [{ description: 'Retain last 10 images', maxImageCount: 10 }],
    });

    // ====================================================================
    // Encrypted logging (finite retention) + KMS key for CloudWatch Logs
    // ====================================================================
    this.logEncryptionKey = new kms.Key(this, 'LogEncryptionKey', {
      description: 'CSUB platform CloudWatch Logs encryption key.',
      enableKeyRotation: true,
      removalPolicy,
    });
    this.logEncryptionKey.addToResourcePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        principals: [new iam.ServicePrincipal(`logs.${this.region}.amazonaws.com`)],
        actions: [
          'kms:Encrypt',
          'kms:Decrypt',
          'kms:ReEncrypt*',
          'kms:GenerateDataKey*',
          'kms:Describe*',
        ],
        resources: ['*'],
        conditions: {
          ArnLike: {
            'kms:EncryptionContext:aws:logs:arn': `arn:aws:logs:${this.region}:${this.account}:log-group:*`,
          },
        },
      }),
    );

    const logRetention = toLogRetention(retentionDays);
    const proxyLogGroup = new logs.LogGroup(this, 'ProxyLogGroup', {
      logGroupName: `/csub/${appEnv}/case-proxy`,
      retention: logRetention,
      encryptionKey: this.logEncryptionKey,
      removalPolicy,
    });
    const apiAccessLogGroup = new logs.LogGroup(this, 'ApiAccessLogGroup', {
      logGroupName: `/csub/${appEnv}/api-access`,
      retention: logRetention,
      encryptionKey: this.logEncryptionKey,
      removalPolicy,
    });

    // ====================================================================
    // CloudTrail management-event audit
    // ====================================================================
    new cloudtrail.Trail(this, 'ManagementAudit', {
      bucket: auditBucket,
      includeGlobalServiceEvents: true,
      isMultiRegionTrail: false,
      managementEvents: cloudtrail.ReadWriteType.WRITE_ONLY,
      encryptionKey: dataKey,
    });

    // ====================================================================
    // Secrets Manager — import an EXISTING Slack secret only (no placeholder)
    // ====================================================================
    let slackSecret: secretsmanager.ISecret | undefined;
    if (config.slackSecretArn) {
      slackSecret = secretsmanager.Secret.fromSecretCompleteArn(
        this,
        'SlackSecret',
        config.slackSecretArn,
      );
    }

    // ====================================================================
    // Async analysis boundary: encrypted worker queue + DLQ
    // ====================================================================
    this.analysisDlq = new sqs.Queue(this, 'AnalysisDlq', {
      queueName: `csub-analysis-dlq-${appEnv}`,
      encryption: sqs.QueueEncryption.KMS,
      encryptionMasterKey: dataKey,
      enforceSSL: true,
      retentionPeriod: cdk.Duration.days(Math.min(retentionDays, 14)),
      removalPolicy,
    });
    this.analysisQueue = new sqs.Queue(this, 'AnalysisQueue', {
      queueName: `csub-analysis-${appEnv}`,
      encryption: sqs.QueueEncryption.KMS,
      encryptionMasterKey: dataKey,
      enforceSSL: true,
      visibilityTimeout: cdk.Duration.minutes(6),
      deadLetterQueue: { queue: this.analysisDlq, maxReceiveCount: 5 },
      removalPolicy,
    });

    // ====================================================================
    // Guardrail (content + prompt-attack + PII + contextual grounding)
    // ====================================================================
    let guardrailVersion: bedrock.CfnGuardrailVersion | undefined;
    if (config.enableGuardrail) {
      this.guardrail = new bedrock.CfnGuardrail(this, 'ReviewGuardrail', {
        name: `csub-review-guardrail-${appEnv}`,
        description: 'Content, prompt-attack, PII, and contextual-grounding controls.',
        blockedInputMessaging: 'This request was blocked by the review guardrail.',
        blockedOutputsMessaging: 'This response was blocked by the review guardrail.',
        kmsKeyArn: dataKey.keyArn,
        contentPolicyConfig: {
          filtersConfig: [
            { type: 'SEXUAL', inputStrength: 'HIGH', outputStrength: 'HIGH' },
            { type: 'VIOLENCE', inputStrength: 'HIGH', outputStrength: 'HIGH' },
            { type: 'HATE', inputStrength: 'HIGH', outputStrength: 'HIGH' },
            { type: 'INSULTS', inputStrength: 'MEDIUM', outputStrength: 'MEDIUM' },
            { type: 'MISCONDUCT', inputStrength: 'HIGH', outputStrength: 'HIGH' },
            // Prompt-attack filtering applies to input only.
            { type: 'PROMPT_ATTACK', inputStrength: 'HIGH', outputStrength: 'NONE' },
          ],
        },
        contextualGroundingPolicyConfig: {
          filtersConfig: [
            { type: 'GROUNDING', threshold: 0.75 },
            { type: 'RELEVANCE', threshold: 0.75 },
          ],
        },
        sensitiveInformationPolicyConfig: {
          piiEntitiesConfig: [
            { type: 'EMAIL', action: 'ANONYMIZE' },
            { type: 'PHONE', action: 'ANONYMIZE' },
            { type: 'NAME', action: 'ANONYMIZE' },
            { type: 'ADDRESS', action: 'ANONYMIZE' },
            { type: 'US_SOCIAL_SECURITY_NUMBER', action: 'BLOCK' },
            { type: 'CREDIT_DEBIT_CARD_NUMBER', action: 'BLOCK' },
            { type: 'PASSWORD', action: 'BLOCK' },
          ],
        },
      });

      // Pin an immutable version for application use; never reference DRAFT.
      guardrailVersion = new bedrock.CfnGuardrailVersion(this, 'ReviewGuardrailVersion', {
        guardrailIdentifier: this.guardrail.attrGuardrailId,
        description: `Pinned guardrail version for ${appEnv}.`,
      });
    }

    // ====================================================================
    // Retrieval scopes: S3 Vectors + Knowledge Bases
    // GATE: only when enableVectorStores is true. Some AWS Organizations SCPs
    // explicitly deny s3vectors:CreateVectorBucket, so this defaults off to keep
    // the core platform deployable; the full infrastructure is preserved here
    // for a future allowed account.
    // ====================================================================
    let knowledgeBasesConfigured = false;
    if (config.enableVectorStores) {
      const vectorEncryption: s3vectors.CfnVectorBucket.EncryptionConfigurationProperty = {
        sseType: 'aws:kms',
        kmsKeyArn: dataKey.keyArn,
      };

      const makeVectorScope = (
        scope: string,
      ): { bucket: s3vectors.CfnVectorBucket; index: s3vectors.CfnIndex } => {
        const bucket = new s3vectors.CfnVectorBucket(this, `${scope}VectorBucket`, {
          vectorBucketName: `csub-${scope.toLowerCase()}-vectors-${appEnv}-${this.account}`,
          encryptionConfiguration: vectorEncryption,
        });
        const index = new s3vectors.CfnIndex(this, `${scope}VectorIndex`, {
          indexName: `csub-${scope.toLowerCase()}-index`,
          vectorBucketArn: bucket.attrVectorBucketArn,
          dataType: 'float32',
          dimension: config.embeddingDimension,
          distanceMetric: 'cosine',
          // Metadata-filterable retrieval per scope (vendor/product, policy).
          metadataConfiguration: { nonFilterableMetadataKeys: ['source_text'] },
        });
        index.addDependency(bucket);
        return { bucket, index };
      };

      const policyScope = makeVectorScope('Policy');
      const evidenceScope = makeVectorScope('Evidence');

      const embeddingModelArn = config.embeddingModelArn;
      if (embeddingModelArn !== undefined) {
        const kbRole = new iam.Role(this, 'KnowledgeBaseRole', {
          assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com', {
            conditions: { StringEquals: { 'aws:SourceAccount': this.account } },
          }),
          description: 'Least-privilege role for CSUB Knowledge Base ingestion/query.',
        });
        kbRole.addToPolicy(
          new iam.PolicyStatement({
            actions: ['bedrock:InvokeModel'],
            resources: [embeddingModelArn],
          }),
        );
        kbRole.addToPolicy(
          new iam.PolicyStatement({
            actions: ['s3:GetObject', 's3:ListBucket'],
            resources: [this.evidenceBucket.bucketArn, this.evidenceBucket.arnForObjects('*')],
          }),
        );
        kbRole.addToPolicy(
          new iam.PolicyStatement({
            actions: [
              's3vectors:GetIndex',
              's3vectors:QueryVectors',
              's3vectors:PutVectors',
              's3vectors:GetVectors',
              's3vectors:DeleteVectors',
            ],
            resources: [policyScope.index.attrIndexArn, evidenceScope.index.attrIndexArn],
          }),
        );
        dataKey.grantEncryptDecrypt(kbRole);

        const makeKnowledgeBase = (
          scope: string,
          index: s3vectors.CfnIndex,
        ): bedrock.CfnKnowledgeBase =>
          new bedrock.CfnKnowledgeBase(this, `${scope}KnowledgeBase`, {
            name: `csub-${scope.toLowerCase()}-kb-${appEnv}`,
            roleArn: kbRole.roleArn,
            knowledgeBaseConfiguration: {
              type: 'VECTOR',
              vectorKnowledgeBaseConfiguration: {
                embeddingModelArn,
              },
            },
            storageConfiguration: {
              type: 'S3_VECTORS',
              s3VectorsConfiguration: { indexArn: index.attrIndexArn },
            },
          });

        makeKnowledgeBase('Policy', policyScope.index);
        makeKnowledgeBase('Evidence', evidenceScope.index);
        knowledgeBasesConfigured = true;
      }
    }

    // ====================================================================
    // AgentCore: execution role, Memory, Browser, Runtime/Endpoint
    // GATE: only when enableAgentCoreServices is true. Some AWS Organizations
    // SCPs explicitly deny bedrock-agentcore:CreateMemory (and related), so this
    // defaults off to keep the core platform deployable. When disabled, NO
    // AWS::BedrockAgentCore::* resources and NO AgentCore-specific roles,
    // policies, or alarms are synthesized — and a configured runtime image URI
    // does NOT bypass this gate.
    // ====================================================================
    let agentEndpoint: agentcore.CfnRuntimeEndpoint | undefined;
    if (config.enableAgentCoreServices) {
      const agentExecutionRole = new iam.Role(this, 'AgentRuntimeExecutionRole', {
        assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com', {
          conditions: {
            StringEquals: { 'aws:SourceAccount': this.account },
            ArnLike: {
              'aws:SourceArn': `arn:aws:bedrock-agentcore:${this.region}:${this.account}:*`,
            },
          },
        }),
        description: 'Least-privilege AgentCore runtime execution role.',
      });
      this.ecrRepository.grantPull(agentExecutionRole);
      dataKey.grantEncryptDecrypt(agentExecutionRole);
      this.evidenceBucket.grantReadWrite(agentExecutionRole);
      this.generatedBucket.grantReadWrite(agentExecutionRole);
      // Shared foundation cases table (coordinated by reference, not by export).
      foundationStack.casesTable.grantReadWriteData(agentExecutionRole);
      agentExecutionRole.addToPolicy(
        new iam.PolicyStatement({
          actions: ['logs:CreateLogStream', 'logs:PutLogEvents', 'logs:DescribeLogStreams'],
          resources: [
            `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*`,
          ],
        }),
      );
      // Model invocation is scoped to Bedrock foundation-model/inference-profile
      // ARNs in this account/region; no specific model ID is hard-coded here.
      agentExecutionRole.addToPolicy(
        new iam.PolicyStatement({
          actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
          resources: [
            `arn:aws:bedrock:${this.region}::foundation-model/*`,
            `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
          ],
        }),
      );
      if (this.guardrail) {
        agentExecutionRole.addToPolicy(
          new iam.PolicyStatement({
            actions: ['bedrock:ApplyGuardrail'],
            resources: [this.guardrail.attrGuardrailArn],
          }),
        );
      }

      // Seven-day short-term Memory (encrypted; no institutional data at synth).
      new agentcore.CfnMemory(this, 'AgentMemory', {
        name: `csub_review_memory_${appEnv}`,
        description: 'Seven-day short-term AgentCore memory for the review workflow.',
        eventExpiryDuration: 7,
        encryptionKeyArn: dataKey.keyArn,
      });

      // Managed Browser for allowlisted official trust-center research only.
      const browserRole = new iam.Role(this, 'AgentBrowserRole', {
        assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com', {
          conditions: { StringEquals: { 'aws:SourceAccount': this.account } },
        }),
        description: 'Least-privilege AgentCore managed browser role.',
      });
      dataKey.grantEncryptDecrypt(browserRole);
      new agentcore.CfnBrowserCustom(this, 'AgentBrowser', {
        name: `csub_review_browser_${appEnv}`,
        description: 'Managed browser restricted to allowlisted official domains.',
        executionRoleArn: browserRole.roleArn,
        networkConfiguration: { networkMode: config.agentCoreNetworkMode },
      });

      // Runtime/Endpoint additionally require a supplied immutable image URI.
      if (config.agentCoreImageUri) {
        const cognitoDiscoveryUrl = `https://cognito-idp.${this.region}.amazonaws.com/${this.userPool.userPoolId}/.well-known/openid-configuration`;
        this.agentRuntime = new agentcore.CfnRuntime(this, 'AgentRuntime', {
          agentRuntimeName: `csub_review_runtime_${appEnv}`,
          description: 'ARM64 HTTP AgentCore runtime (GET /ping, POST /invocations, port 8080).',
          roleArn: agentExecutionRole.roleArn,
          agentRuntimeArtifact: {
            containerConfiguration: { containerUri: config.agentCoreImageUri },
          },
          networkConfiguration: { networkMode: config.agentCoreNetworkMode },
          protocolConfiguration: 'HTTP',
          // Authenticated inbound via Cognito JWT; never anonymous.
          authorizerConfiguration: {
            customJwtAuthorizer: {
              discoveryUrl: cognitoDiscoveryUrl,
              allowedClients: [this.userPoolClient.userPoolClientId],
            },
          },
          // Allowlist only safe headers into the container; never Host/Authorization.
          requestHeaderConfiguration: {
            requestHeaderAllowlist: ['X-Correlation-Id', 'Content-Type'],
          },
        });

        agentEndpoint = new agentcore.CfnRuntimeEndpoint(this, 'AgentRuntimeEndpoint', {
          agentRuntimeId: this.agentRuntime.attrAgentRuntimeId,
          name: `csub_${appEnv}`,
        });
        agentEndpoint.addDependency(this.agentRuntime);
      }
    }

    // ====================================================================
    // Lambda proxy (Node 22, ARM64, SDK v3) + HTTP API
    // ====================================================================
    this.proxyFunction = new lambda.Function(this, 'CaseProxyFunction', {
      functionName: `csub-case-proxy-${appEnv}`,
      runtime: lambda.Runtime.NODEJS_22_X,
      architecture: lambda.Architecture.ARM_64,
      handler: 'index.handler',
      // Committed, dependency-light asset; the tested TS source of truth lives
      // in services/case-api/src and is bundled to this shape on deploy.
      code: lambda.Code.fromAsset(path.join(__dirname, '..', 'lambda', 'case-proxy')),
      memorySize: 256,
      timeout: cdk.Duration.seconds(29),
      logGroup: proxyLogGroup,
      environment: {
        APP_ENV: appEnv,
        EVIDENCE_BUCKET: this.evidenceBucket.bucketName,
        GENERATED_BUCKET: this.generatedBucket.bucketName,
        ANALYSIS_QUEUE_URL: this.analysisQueue.queueUrl,
        INVITE_TABLE: this.tables.InviteTable.tableName,
        AUDIT_TABLE: this.tables.AuditTable.tableName,
        IDEMPOTENCY_TABLE: this.tables.IdempotencyTable.tableName,
        CASES_TABLE: foundationStack.casesTable.tableName,
        MAX_JSON_BYTES: '1048576', // <= 1 MiB metadata surface
        PRESIGN_TTL_SECONDS: '300',
        SERVICE_NOW_TABLE: config.serviceNowTableName,
        ...(agentEndpoint
          ? { AGENT_RUNTIME_ENDPOINT_ARN: agentEndpoint.attrAgentRuntimeEndpointArn }
          : {}),
        ...(this.guardrail && guardrailVersion
          ? {
              GUARDRAIL_ID: this.guardrail.attrGuardrailId,
              GUARDRAIL_VERSION: guardrailVersion.attrVersion,
            }
          : {}),
        ...(slackSecret ? { SLACK_SECRET_ARN: slackSecret.secretArn } : {}),
      },
    });

    // Least-privilege grants for the proxy.
    this.evidenceBucket.grantReadWrite(this.proxyFunction); // presigned PUT/GET issuance
    this.generatedBucket.grantRead(this.proxyFunction);
    this.analysisQueue.grantSendMessages(this.proxyFunction);
    this.tables.InviteTable.grantReadWriteData(this.proxyFunction);
    this.tables.AuditTable.grantReadWriteData(this.proxyFunction);
    this.tables.IdempotencyTable.grantReadWriteData(this.proxyFunction);
    this.tables.ReviewTable.grantReadWriteData(this.proxyFunction);
    this.tables.SubmissionTable.grantReadWriteData(this.proxyFunction);
    foundationStack.casesTable.grantReadWriteData(this.proxyFunction);
    dataKey.grantEncryptDecrypt(this.proxyFunction);
    if (slackSecret) {
      slackSecret.grantRead(this.proxyFunction);
    }
    // Invoke AgentCore via the data-plane; scoped to this account/region
    // runtimes. AgentCore-specific — only granted when AgentCore is enabled.
    if (config.enableAgentCoreServices) {
      this.proxyFunction.addToRolePolicy(
        new iam.PolicyStatement({
          actions: ['bedrock-agentcore:InvokeAgentRuntime'],
          resources: [
            `arn:aws:bedrock-agentcore:${this.region}:${this.account}:runtime/*`,
            `arn:aws:bedrock-agentcore:${this.region}:${this.account}:runtime/*/runtime-endpoint/*`,
          ],
        }),
      );
    }

    const cognitoAuthorizer = new HttpUserPoolAuthorizer('ReviewerAuthorizer', this.userPool, {
      userPoolClients: [this.userPoolClient],
    });

    this.api = new apigwv2.HttpApi(this, 'CaseApi', {
      apiName: `csub-case-api-${appEnv}`,
      description: 'Reviewer, vendor-intake, and integration surface for the review agent.',
      corsPreflight: {
        allowOrigins: ['*'],
        allowMethods: [
          apigwv2.CorsHttpMethod.GET,
          apigwv2.CorsHttpMethod.POST,
          apigwv2.CorsHttpMethod.OPTIONS,
        ],
        allowHeaders: ['Content-Type', 'Authorization', 'X-Correlation-Id'],
        maxAge: cdk.Duration.hours(1),
      },
    });

    // Structured JSON access logs (no bodies/tokens) with finite retention.
    const defaultStage = this.api.defaultStage!.node.defaultChild as apigwv2.CfnStage;
    defaultStage.accessLogSettings = {
      destinationArn: apiAccessLogGroup.logGroupArn,
      format: JSON.stringify({
        requestId: '$context.requestId',
        httpMethod: '$context.httpMethod',
        routeKey: '$context.routeKey',
        status: '$context.status',
        integrationStatus: '$context.integrationStatus',
        responseLatency: '$context.responseLatency',
      }),
    };

    const integration = new HttpLambdaIntegration('CaseProxyIntegration', this.proxyFunction);

    // --- Reviewer/admin routes: Cognito JWT required ---
    const protectedRoutes: Array<[string, apigwv2.HttpMethod[]]> = [
      ['/cases', [apigwv2.HttpMethod.POST]],
      ['/cases/{id}', [apigwv2.HttpMethod.GET]],
      ['/cases/{id}/documents', [apigwv2.HttpMethod.POST]],
      ['/cases/{id}/analyze', [apigwv2.HttpMethod.POST]],
      ['/cases/{id}/review', [apigwv2.HttpMethod.POST]],
      ['/cases/{id}/packet', [apigwv2.HttpMethod.GET]],
      ['/cases/{id}/servicenow/preview', [apigwv2.HttpMethod.POST]],
      ['/cases/{id}/servicenow/commit', [apigwv2.HttpMethod.POST]],
      ['/review-queue', [apigwv2.HttpMethod.GET]],
      ['/vendors', [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST]],
      ['/catalog', [apigwv2.HttpMethod.GET]],
      ['/profile', [apigwv2.HttpMethod.GET]],
    ];
    for (const [routePath, methods] of protectedRoutes) {
      this.api.addRoutes({ path: routePath, methods, integration, authorizer: cognitoAuthorizer });
    }

    // --- Public-at-gateway routes: enforced downstream, NOT by Cognito ---
    // Invite intake is token-FREE at the URL: the opaque invite token is read
    // only from the Authorization: Bearer header inside the Lambda (never in the
    // path/query), so it cannot leak into API Gateway, CloudFront, browser
    // history, or access logs. Authenticity is enforced downstream by hash.
    this.api.addRoutes({
      path: '/intake',
      methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
      integration,
    });
    // Slack events: authenticity enforced by signature verification downstream.
    this.api.addRoutes({
      path: '/slack/events',
      methods: [apigwv2.HttpMethod.POST],
      integration,
    });

    // ====================================================================
    // Observability: alarms + dashboard
    // ====================================================================
    const apiErrorAlarm = new cloudwatch.Alarm(this, 'ApiServerErrorAlarm', {
      alarmDescription: 'HTTP API 5xx responses exceeded threshold.',
      metric: this.api.metricServerError({ period: cdk.Duration.minutes(5) }),
      threshold: 5,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    const proxyErrorAlarm = new cloudwatch.Alarm(this, 'ProxyErrorAlarm', {
      alarmDescription: 'Case proxy Lambda errors exceeded threshold.',
      metric: this.proxyFunction.metricErrors({ period: cdk.Duration.minutes(5) }),
      threshold: 3,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    const dlqAlarm = new cloudwatch.Alarm(this, 'AnalysisDlqAlarm', {
      alarmDescription: 'Messages landed in the analysis dead-letter queue.',
      metric: this.analysisDlq.metricApproximateNumberOfMessagesVisible({
        period: cdk.Duration.minutes(5),
      }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    // Knowledge Base ingestion-failure alarm — only when vector stores/KBs exist.
    const dashboardAlarms: cloudwatch.IAlarm[] = [apiErrorAlarm, proxyErrorAlarm, dlqAlarm];
    if (config.enableVectorStores) {
      const kbIngestionAlarm = new cloudwatch.Alarm(this, 'KbIngestionFailureAlarm', {
        alarmDescription: 'Knowledge Base ingestion documents failed.',
        metric: new cloudwatch.Metric({
          namespace: 'AWS/Bedrock',
          metricName: 'IngestionDocumentFailed',
          period: cdk.Duration.minutes(15),
          statistic: cloudwatch.Stats.SUM,
        }),
        threshold: 1,
        evaluationPeriods: 1,
        comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      });
      dashboardAlarms.push(kbIngestionAlarm);
    }

    const dashboard = new cloudwatch.Dashboard(this, 'PlatformDashboard', {
      dashboardName: `csub-platform-${appEnv}`,
    });
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'API traffic and errors',
        left: [this.api.metricCount(), this.api.metricServerError(), this.api.metricClientError()],
      }),
      new cloudwatch.GraphWidget({
        title: 'Proxy latency and failures',
        left: [this.proxyFunction.metricDuration()],
        right: [this.proxyFunction.metricErrors(), this.proxyFunction.metricThrottles()],
      }),
      new cloudwatch.GraphWidget({
        title: 'Analysis DLQ depth',
        left: [this.analysisDlq.metricApproximateNumberOfMessagesVisible()],
      }),
      new cloudwatch.AlarmStatusWidget({
        title: 'Alarms',
        alarms: dashboardAlarms,
      }),
    );

    // ====================================================================
    // Parameterized monthly AWS Budget
    // ====================================================================
    new budgets.CfnBudget(this, 'MonthlyBudget', {
      budget: {
        budgetName: `csub-platform-${appEnv}`,
        budgetType: 'COST',
        timeUnit: 'MONTHLY',
        budgetLimit: { amount: config.budgetLimitUsd, unit: 'USD' },
      },
      notificationsWithSubscribers: config.budgetNotificationEmail
        ? [
            {
              notification: {
                notificationType: 'ACTUAL',
                comparisonOperator: 'GREATER_THAN',
                threshold: 80,
                thresholdType: 'PERCENTAGE',
              },
              subscribers: [
                { subscriptionType: 'EMAIL', address: config.budgetNotificationEmail },
              ],
            },
            {
              notification: {
                notificationType: 'FORECASTED',
                comparisonOperator: 'GREATER_THAN',
                threshold: 100,
                thresholdType: 'PERCENTAGE',
              },
              subscribers: [
                { subscriptionType: 'EMAIL', address: config.budgetNotificationEmail },
              ],
            },
          ]
        : undefined,
    });

    // ====================================================================
    // Outputs
    // ====================================================================
    new cdk.CfnOutput(this, 'ApiEndpoint', { value: this.api.apiEndpoint });
    new cdk.CfnOutput(this, 'CloudFrontDomain', { value: this.distribution.distributionDomainName });
    new cdk.CfnOutput(this, 'UserPoolId', { value: this.userPool.userPoolId });
    new cdk.CfnOutput(this, 'UserPoolClientId', { value: this.userPoolClient.userPoolClientId });
    new cdk.CfnOutput(this, 'FrontendBucketName', { value: this.frontendBucket.bucketName });
    new cdk.CfnOutput(this, 'EvidenceBucketName', { value: this.evidenceBucket.bucketName });
    new cdk.CfnOutput(this, 'EcrRepositoryUri', { value: this.ecrRepository.repositoryUri });
    new cdk.CfnOutput(this, 'AnalysisQueueUrl', { value: this.analysisQueue.queueUrl });
    new cdk.CfnOutput(this, 'AgentCoreServicesEnabled', {
      value: config.enableAgentCoreServices ? 'true' : 'false',
      description: 'Whether AWS::BedrockAgentCore::* resources are synthesized.',
    });
    new cdk.CfnOutput(this, 'AgentRuntimeConfigured', {
      value: this.agentRuntime ? 'true' : 'false',
      description: 'Whether an AgentCore Runtime/Endpoint is synthesized (needs services + image URI).',
    });
    new cdk.CfnOutput(this, 'VectorStoresEnabled', {
      value: config.enableVectorStores ? 'true' : 'false',
      description: 'Whether AWS::S3Vectors::* resources are synthesized.',
    });
    new cdk.CfnOutput(this, 'KnowledgeBasesConfigured', {
      value: knowledgeBasesConfigured ? 'true' : 'false',
      description: 'Whether Knowledge Bases are synthesized (needs vector stores + embedding model ARN).',
    });
    new cdk.CfnOutput(this, 'GuardrailEnabled', {
      value: config.enableGuardrail ? 'true' : 'false',
      description: 'Whether the Bedrock Guardrail + version are synthesized.',
    });
  }
}
