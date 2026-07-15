import { GetSecretValueCommand } from '@aws-sdk/client-secrets-manager';
import { describe, expect, test } from 'vitest';

import type { AuthRuntimeConfig } from '../src/config.js';
import { loadRuntimeSecrets, type SecretsManagerReader } from '../src/secrets.js';

const config = {
  betterAuthSecretId: 'arn:better-auth',
  cognitoClientSecretId: 'arn:cognito-client',
} as AuthRuntimeConfig;

describe('Secrets Manager configuration', () => {
  test('loads both values by ARN and parses the Cognito secret without logging or environment values', async () => {
    const seen: string[] = [];
    const reader: SecretsManagerReader = {
      async send(command: GetSecretValueCommand) {
        const secretId = command.input.SecretId!;
        seen.push(secretId);
        return secretId === config.betterAuthSecretId
          ? { SecretString: 's'.repeat(64) }
          : { SecretString: JSON.stringify({ clientId: 'client-id', clientSecret: 'oauth-secret' }) };
      },
    };
    await expect(loadRuntimeSecrets(config, reader)).resolves.toEqual({
      betterAuthSecret: 's'.repeat(64),
      cognitoClientId: 'client-id',
      cognitoClientSecret: 'oauth-secret',
    });
    expect(seen.sort()).toEqual([config.betterAuthSecretId, config.cognitoClientSecretId].sort());
  });

  test('rejects short session keys and malformed Cognito secret documents', async () => {
    const shortReader: SecretsManagerReader = {
      async send(command: GetSecretValueCommand) {
        return command.input.SecretId === config.betterAuthSecretId
          ? { SecretString: 'short' }
          : { SecretString: JSON.stringify({ clientId: 'client-id', clientSecret: 'oauth-secret' }) };
      },
    };
    await expect(loadRuntimeSecrets(config, shortReader)).rejects.toThrow(/at least 32 bytes/);

    const malformedReader: SecretsManagerReader = {
      async send(command: GetSecretValueCommand) {
        return command.input.SecretId === config.betterAuthSecretId
          ? { SecretString: 's'.repeat(64) }
          : { SecretString: '{}' };
      },
    };
    await expect(loadRuntimeSecrets(config, malformedReader)).rejects.toThrow(/clientSecret/);
  });
});
