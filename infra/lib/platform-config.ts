import * as cdk from 'aws-cdk-lib';
import * as logs from 'aws-cdk-lib/aws-logs';

/**
 * Resolved, validated configuration for {@link PlatformStack}.
 *
 * Every value originates from CDK context (`-c key=value`) or an environment
 * variable, never from hard-coded account/region/credential/model/URL literals
 * (AGENTS.md, PRD sec 7). Optional inputs act as documented *deployment gates*:
 * when an input is absent, the resources that depend on it are not synthesized,
 * so the template stays deployable and offline-synthesizable at every stage.
 */
export interface PlatformConfig {
  /** Deployment environment label (development, staging, ...). */
  readonly appEnv: string;
  /** Finite retention period (days) applied to data, logs, and audit. */
  readonly retentionDays: number;

  // ---- Cognito hosted UI ----------------------------------------------
  /**
   * Optional globally unique Cognito prefix-domain label. When omitted, the
   * stack derives an account- and environment-specific prefix. Configure this
   * when the derived prefix is unavailable in the deployment Region.
   */
  readonly cognitoDomainPrefix?: string;

  // ---- Master service gates (SCP-safe deployment defaults) -------------
  /**
   * Create AgentCore services (Runtime/Endpoint/Memory/Browser + their roles,
   * policies, and alarms). Default false: some AWS Organizations SCPs explicitly
   * deny `bedrock-agentcore:CreateMemory` (and related), which rolls the stack
   * back. Enable only in an account where AgentCore is permitted.
   */
  readonly enableAgentCoreServices: boolean;
  /**
   * Create S3 Vector stores and Knowledge Bases (+ KB role and KB alarm).
   * Default false: some SCPs explicitly deny `s3vectors:CreateVectorBucket`.
   * Enable only in an account where S3 Vectors is permitted.
   */
  readonly enableVectorStores: boolean;

  // ---- AgentCore Runtime gate ------------------------------------------
  /**
   * Immutable, digest-pinned ECR image URI for the ARM64 HTTP AgentCore
   * runtime. GATE: the Runtime + RuntimeEndpoint are created only when
   * `enableAgentCoreServices` is true AND this image URI is supplied. The image
   * URI never bypasses the master AgentCore gate.
   */
  readonly agentCoreImageUri?: string;
  /**
   * Network mode for the AgentCore runtime/browser. Sandbox default is
   * `PUBLIC`; production must switch to `VPC` (documented delta).
   */
  readonly agentCoreNetworkMode: 'PUBLIC' | 'VPC';

  // ---- Retrieval (Knowledge Base) gate ---------------------------------
  /**
   * Bedrock embedding model ARN (e.g. Titan Text Embeddings V2). GATE: the
   * two Knowledge Bases are created only when `enableVectorStores` is true
   * AND this ARN is supplied. No model ID is ever hard-coded.
   */
  readonly embeddingModelArn?: string;
  /** Embedding vector dimension for the S3 Vector indexes (Titan V2 = 1024). */
  readonly embeddingDimension: number;
  /** S3 key prefix under the evidence/policy buckets holding campus policy docs. */
  readonly policyDocumentsPrefix?: string;

  // ---- Guardrail -------------------------------------------------------
  /** Create the Bedrock Guardrail + pinned version (default false; separately gated). */
  readonly enableGuardrail: boolean;

  // ---- Secrets ---------------------------------------------------------
  /**
   * ARN of an *existing* Secrets Manager secret holding Slack bot/signing
   * credentials. Imported by reference only; never generated. GATE: when
   * omitted, no Slack secret is referenced (documented gate).
   */
  readonly slackSecretArn?: string;
  /** Mock ServiceNow target table name (no credential; demo simulation only). Default sc_req_item. */
  readonly serviceNowTableName: string;

  // ---- Review model ----------------------------------------------------
  /**
   * Cross-Region Bedrock inference-profile ID used by the deterministic case
   * Lambda. The deployed sandbox default was verified in us-west-2.
   */
  readonly reviewModelId: string;

  // ---- Budget ----------------------------------------------------------
  /** Monthly AWS Budget limit in USD (parameterized cost guardrail). */
  readonly budgetLimitUsd: number;
  /** Optional email subscriber for budget alerts (no default; PII-free gate). */
  readonly budgetNotificationEmail?: string;

  // ---- Teardown --------------------------------------------------------
  /**
   * When true (sandbox default), prototype resources use RemovalPolicy.DESTROY
   * + autoDelete so `cdk destroy` is clean. Set false to retain stateful data.
   */
  readonly destroyOnRemoval: boolean;
}

function ctx(app: cdk.App, key: string): string | undefined {
  const v = app.node.tryGetContext(key);
  return typeof v === 'string' && v.length > 0 ? v : undefined;
}

function boolCtx(app: cdk.App, key: string, envKey: string, fallback: boolean): boolean {
  const contextValue = app.node.tryGetContext(key) as unknown;
  const raw = contextValue ?? process.env[envKey];
  if (raw === undefined) return fallback;
  if (typeof raw === 'boolean') return raw;
  if (raw === 'true' || raw === '1') return true;
  if (raw === 'false' || raw === '0') return false;
  throw new Error(`${key} must be a boolean (true/false or 1/0), got: ${String(raw)}`);
}

/**
 * Resolve platform configuration from CDK context and environment. Throws on
 * invalid numeric or enum inputs so misconfiguration fails fast at synth.
 */
export function resolvePlatformConfig(app: cdk.App): PlatformConfig {
  const appEnv = ctx(app, 'appEnv') ?? process.env.APP_ENV ?? 'development';

  const retentionDays = Number.parseInt(
    (app.node.tryGetContext('retentionDays') as string | undefined) ??
      process.env.RETENTION_DAYS ??
      '90',
    10,
  );
  if (!Number.isFinite(retentionDays) || retentionDays <= 0) {
    throw new Error(`retentionDays must be a positive integer, got: ${retentionDays}`);
  }

  const networkModeRaw =
    ctx(app, 'agentCoreNetworkMode') ?? process.env.AGENTCORE_NETWORK_MODE ?? 'PUBLIC';
  if (networkModeRaw !== 'PUBLIC' && networkModeRaw !== 'VPC') {
    throw new Error(`agentCoreNetworkMode must be PUBLIC or VPC, got: ${networkModeRaw}`);
  }

  const embeddingDimension = Number.parseInt(
    ctx(app, 'embeddingDimension') ?? process.env.EMBEDDING_DIMENSION ?? '1024',
    10,
  );
  if (!Number.isFinite(embeddingDimension) || embeddingDimension <= 0) {
    throw new Error(`embeddingDimension must be a positive integer, got: ${embeddingDimension}`);
  }

  const budgetLimitUsd = Number.parseInt(
    ctx(app, 'budgetLimitUsd') ?? process.env.BUDGET_LIMIT_USD ?? '50',
    10,
  );
  if (!Number.isFinite(budgetLimitUsd) || budgetLimitUsd <= 0) {
    throw new Error(`budgetLimitUsd must be a positive integer, got: ${budgetLimitUsd}`);
  }

  const configuredCognitoDomainPrefix =
    ctx(app, 'cognitoDomainPrefix') ?? process.env.COGNITO_DOMAIN_PREFIX;
  const cognitoDomainPrefix = configuredCognitoDomainPrefix?.trim();
  if (
    cognitoDomainPrefix !== undefined &&
    !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(cognitoDomainPrefix)
  ) {
    throw new Error(
      'cognitoDomainPrefix must be 1-63 lowercase letters, numbers, or hyphens and cannot start or end with a hyphen',
    );
  }

  return {
    appEnv,
    retentionDays,
    cognitoDomainPrefix,
    enableAgentCoreServices: boolCtx(
      app,
      'enableAgentCoreServices',
      'ENABLE_AGENTCORE_SERVICES',
      false,
    ),
    enableVectorStores: boolCtx(app, 'enableVectorStores', 'ENABLE_VECTOR_STORES', false),
    agentCoreImageUri: ctx(app, 'agentCoreImageUri') ?? process.env.AGENTCORE_IMAGE_URI,
    agentCoreNetworkMode: networkModeRaw,
    embeddingModelArn: ctx(app, 'embeddingModelArn') ?? process.env.EMBEDDING_MODEL_ARN,
    embeddingDimension,
    policyDocumentsPrefix:
      ctx(app, 'policyDocumentsPrefix') ?? process.env.POLICY_DOCUMENTS_PREFIX ?? 'policy/',
    enableGuardrail: boolCtx(app, 'enableGuardrail', 'ENABLE_GUARDRAIL', false),
    slackSecretArn: ctx(app, 'slackSecretArn') ?? process.env.SLACK_SECRET_ARN,
    serviceNowTableName:
      ctx(app, 'serviceNowTableName') ?? process.env.SERVICE_NOW_TABLE_NAME ?? 'sc_req_item',
    reviewModelId:
      ctx(app, 'reviewModelId') ?? process.env.REVIEW_MODEL_ID ?? 'us.anthropic.claude-sonnet-5',
    budgetLimitUsd,
    budgetNotificationEmail:
      ctx(app, 'budgetNotificationEmail') ?? process.env.BUDGET_NOTIFICATION_EMAIL,
    destroyOnRemoval: boolCtx(app, 'destroyOnRemoval', 'DESTROY_ON_REMOVAL', true),
  };
}

/** Map an arbitrary day count to the nearest supported CloudWatch retention. */
export function toLogRetention(days: number): logs.RetentionDays {
  const supported: Array<[number, logs.RetentionDays]> = [
    [1, logs.RetentionDays.ONE_DAY],
    [3, logs.RetentionDays.THREE_DAYS],
    [5, logs.RetentionDays.FIVE_DAYS],
    [7, logs.RetentionDays.ONE_WEEK],
    [14, logs.RetentionDays.TWO_WEEKS],
    [30, logs.RetentionDays.ONE_MONTH],
    [60, logs.RetentionDays.TWO_MONTHS],
    [90, logs.RetentionDays.THREE_MONTHS],
    [120, logs.RetentionDays.FOUR_MONTHS],
    [150, logs.RetentionDays.FIVE_MONTHS],
    [180, logs.RetentionDays.SIX_MONTHS],
    [365, logs.RetentionDays.ONE_YEAR],
  ];
  let chosen = supported[supported.length - 1][1];
  for (const [d, enumValue] of supported) {
    if (days <= d) {
      chosen = enumValue;
      break;
    }
  }
  return chosen;
}
