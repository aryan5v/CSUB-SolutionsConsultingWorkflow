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

  // ---- AgentCore Runtime gate ------------------------------------------
  /**
   * Immutable, digest-pinned ECR image URI for the ARM64 HTTP AgentCore
   * runtime. GATE: when omitted, the Runtime + RuntimeEndpoint are not
   * created so synth succeeds before the image is published.
   */
  readonly agentCoreImageUri?: string;
  /**
   * Network mode for the AgentCore runtime/browser. Sandbox default is
   * `PUBLIC`; production must switch to `VPC` (documented delta).
   */
  readonly agentCoreNetworkMode: 'PUBLIC' | 'VPC';

  // ---- Retrieval (Knowledge Base) gate ---------------------------------
  /**
   * Bedrock embedding model ARN (e.g. Titan Text Embeddings V2). GATE: when
   * omitted, the two Knowledge Bases + data sources are not created (S3
   * Vector scopes are always created). No model ID is ever hard-coded.
   */
  readonly embeddingModelArn?: string;
  /** Embedding vector dimension for the S3 Vector indexes (Titan V2 = 1024). */
  readonly embeddingDimension: number;
  /** S3 key prefix under the evidence/policy buckets holding campus policy docs. */
  readonly policyDocumentsPrefix?: string;

  // ---- Guardrail -------------------------------------------------------
  /** Create the Bedrock Guardrail + pinned version (default true). */
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
  const raw = (app.node.tryGetContext(key) as string | undefined) ?? process.env[envKey];
  if (raw === undefined) return fallback;
  return raw === 'true' || raw === '1';
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

  return {
    appEnv,
    retentionDays,
    agentCoreImageUri: ctx(app, 'agentCoreImageUri') ?? process.env.AGENTCORE_IMAGE_URI,
    agentCoreNetworkMode: networkModeRaw,
    embeddingModelArn: ctx(app, 'embeddingModelArn') ?? process.env.EMBEDDING_MODEL_ARN,
    embeddingDimension,
    policyDocumentsPrefix:
      ctx(app, 'policyDocumentsPrefix') ?? process.env.POLICY_DOCUMENTS_PREFIX ?? 'policy/',
    enableGuardrail: boolCtx(app, 'enableGuardrail', 'ENABLE_GUARDRAIL', true),
    slackSecretArn: ctx(app, 'slackSecretArn') ?? process.env.SLACK_SECRET_ARN,
    serviceNowTableName:
      ctx(app, 'serviceNowTableName') ?? process.env.SERVICE_NOW_TABLE_NAME ?? 'sc_req_item',
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
