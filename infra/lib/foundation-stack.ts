import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export interface ReviewFoundationStackProps extends cdk.StackProps {
  /** Deployment environment label (development, etc.). */
  readonly appEnv: string;
  /** Data retention period in days (default 90). */
  readonly retentionDays?: number;
}

/**
 * Storage foundation for the CSUB Technology Review Agent prototype (PRD sec 5):
 * a customer-managed KMS key, KMS-encrypted S3 buckets for raw and normalized
 * sources with public access blocked, and an on-demand DynamoDB cases table.
 *
 * Everything is teardown-safe (RemovalPolicy.DESTROY + autoDeleteObjects) because
 * this runs in a budget-capped Innovation Sandbox and must `cdk destroy` cleanly.
 */
export class ReviewFoundationStack extends cdk.Stack {
  public readonly rawBucket: s3.Bucket;
  public readonly normalizedBucket: s3.Bucket;
  public readonly casesTable: dynamodb.Table;
  public readonly dataKey: kms.IKey;

  constructor(scope: Construct, id: string, props: ReviewFoundationStackProps) {
    super(scope, id, props);

    const retentionDays = props.retentionDays ?? 90;

    const dataKey = new kms.Key(this, 'DataKey', {
      description: 'CSUB review agent S3 encryption key (prototype).',
      enableKeyRotation: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    this.dataKey = dataKey;

    const bucketDefaults: s3.BucketProps = {
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: dataKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    };

    // Originals: raw/<box-file-id>/<sha256>/<filename>. Versioned so an
    // accidental overwrite of an institutional source is recoverable.
    this.rawBucket = new s3.Bucket(this, 'RawSourcesBucket', {
      ...bucketDefaults,
      versioned: true,
      lifecycleRules: [
        {
          id: 'DeleteOldRawVersions',
          expiration: cdk.Duration.days(retentionDays),
          noncurrentVersionExpiration: cdk.Duration.days(retentionDays),
        },
      ],
    });

    // Lossless JSON/Parquet snapshots and normalized records.
    this.normalizedBucket = new s3.Bucket(this, 'NormalizedBucket', {
      ...bucketDefaults,
      lifecycleRules: [
        {
          id: 'DeleteOldNormalizedVersions',
          expiration: cdk.Duration.days(retentionDays),
          noncurrentVersionExpiration: cdk.Duration.days(retentionDays),
        },
      ],
    });

    this.casesTable = new dynamodb.Table(this, 'CasesTable', {
      partitionKey: { name: 'case_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    new cdk.CfnOutput(this, 'RawBucketName', { value: this.rawBucket.bucketName });
    new cdk.CfnOutput(this, 'NormalizedBucketName', { value: this.normalizedBucket.bucketName });
    new cdk.CfnOutput(this, 'CasesTableName', { value: this.casesTable.tableName });
    new cdk.CfnOutput(this, 'DataKeyArn', { value: dataKey.keyArn });
    new cdk.CfnOutput(this, 'AppEnv', { value: props.appEnv });
    new cdk.CfnOutput(this, 'RetentionDays', { value: retentionDays.toString() });
  }
}
