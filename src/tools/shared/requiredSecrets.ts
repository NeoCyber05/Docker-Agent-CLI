import * as crypto from "node:crypto";

export interface RequiredSecretRule {
  imagePattern: RegExp;
  required: string[];
  optional?: string[];
  safeDefaults?: Record<string, () => string>;
}

function randomPassword(): string {
  return crypto.randomBytes(24).toString("base64url");
}

export const REQUIRED_SECRETS_BY_IMAGE: RequiredSecretRule[] = [
  {
    imagePattern: /^postgres(:|$)/,
    required: ["POSTGRES_PASSWORD"],
    optional: ["POSTGRES_USER", "POSTGRES_DB"],
    safeDefaults: { POSTGRES_PASSWORD: randomPassword },
  },
  {
    imagePattern: /^mysql(:|$)/,
    required: ["MYSQL_ROOT_PASSWORD"],
    safeDefaults: { MYSQL_ROOT_PASSWORD: randomPassword },
  },
  {
    imagePattern: /^mariadb(:|$)/,
    required: ["MARIADB_ROOT_PASSWORD"],
    safeDefaults: { MARIADB_ROOT_PASSWORD: randomPassword },
  },
  {
    imagePattern: /^mongo(:|$)/,
    required: ["MONGO_INITDB_ROOT_PASSWORD"],
    optional: ["MONGO_INITDB_ROOT_USERNAME"],
    safeDefaults: { MONGO_INITDB_ROOT_PASSWORD: randomPassword },
  },
  { imagePattern: /^redis(:|$)/, required: [] },
];

export function findRequiredSecrets(image: string): RequiredSecretRule | undefined {
  return REQUIRED_SECRETS_BY_IMAGE.find((rule) => rule.imagePattern.test(image));
}
