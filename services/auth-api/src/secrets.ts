import {
  GetSecretValueCommand,
  SecretsManagerClient,
  type GetSecretValueCommandOutput,
} from '@aws-sdk/client-secrets-manager';

import type { AuthRuntimeConfig, AuthRuntimeSecrets } from './config.js';

type SecretValueOutput = Pick<GetSecretValueCommandOutput, 'SecretString' | 'SecretBinary'>;

export interface SecretsManagerReader {
  send(command: GetSecretValueCommand): Promise<SecretValueOutput>;
}

function decodeSecret(output: SecretValueOutput, label: string): string {
  if (output.SecretString !== undefined) return output.SecretString;
  if (output.SecretBinary !== undefined) {
    return Buffer.from(output.SecretBinary).toString('utf8');
  }
  throw new Error(`${label} has no secret value`);
}

async function getSecret(
  reader: SecretsManagerReader,
  secretId: string,
  label: string,
): Promise<string> {
  const output = await reader.send(new GetSecretValueCommand({ SecretId: secretId }));
  return decodeSecret(output, label);
}

function parseCognitoClientCredentials(
  value: string,
): Pick<AuthRuntimeSecrets, 'cognitoClientId' | 'cognitoClientSecret'> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error('Cognito client secret must be a JSON object');
  }
  if (
    typeof parsed !== 'object' ||
    parsed === null ||
    !('clientId' in parsed) ||
    typeof parsed.clientId !== 'string' ||
    parsed.clientId.length === 0 ||
    !('clientSecret' in parsed) ||
    typeof parsed.clientSecret !== 'string' ||
    parsed.clientSecret.length === 0
  ) {
    throw new Error('Cognito client secret JSON must contain clientId and clientSecret');
  }
  return {
    cognitoClientId: parsed.clientId,
    cognitoClientSecret: parsed.clientSecret,
  };
}

export async function loadRuntimeSecrets(
  config: AuthRuntimeConfig,
  reader: SecretsManagerReader = new SecretsManagerClient({}),
): Promise<AuthRuntimeSecrets> {
  const [betterAuthSecretValue, cognitoClientSecretValue] = await Promise.all([
    getSecret(reader, config.betterAuthSecretId, 'Better Auth secret'),
    getSecret(reader, config.cognitoClientSecretId, 'Cognito client secret'),
  ]);
  if (Buffer.byteLength(betterAuthSecretValue, 'utf8') < 32) {
    throw new Error('Better Auth secret must contain at least 32 bytes');
  }
  return {
    betterAuthSecret: betterAuthSecretValue,
    ...parseCognitoClientCredentials(cognitoClientSecretValue),
  };
}
