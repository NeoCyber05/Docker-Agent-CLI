import * as crypto from "node:crypto";

export interface RequiredSecretRule {
  imagePattern: RegExp;
  required: string[];
  optional?: string[];
  safeDefaults?: Record<string, () => string>;
  weakValues?: string[];
}

function randomPassword(): string {
  return crypto.randomBytes(24).toString("base64url");
}

export const GENERIC_WEAK_VALUES: readonly string[] = [
  "",
  "password",
  "secret",
  "admin",
  "changeme",
  "test",
  "example",
  "root",
  "123456",
  "password123",
];

export const REQUIRED_SECRETS_BY_IMAGE: RequiredSecretRule[] = [
  {
    imagePattern: /^postgres(:|$)/,
    required: ["POSTGRES_PASSWORD"],
    optional: ["POSTGRES_USER", "POSTGRES_DB"],
    safeDefaults: { POSTGRES_PASSWORD: randomPassword },
    weakValues: ["postgres", "postgres123", "pg", "postgresql"],
  },
  {
    imagePattern: /^mysql(:|$)/,
    required: ["MYSQL_ROOT_PASSWORD"],
    safeDefaults: { MYSQL_ROOT_PASSWORD: randomPassword },
    weakValues: ["mysql", "mysql123", "root"],
  },
  {
    imagePattern: /^mariadb(:|$)/,
    required: ["MARIADB_ROOT_PASSWORD"],
    safeDefaults: { MARIADB_ROOT_PASSWORD: randomPassword },
    weakValues: ["mariadb", "mariadb123", "root"],
  },
  {
    imagePattern: /^mongo(:|$)/,
    required: ["MONGO_INITDB_ROOT_PASSWORD"],
    optional: ["MONGO_INITDB_ROOT_USERNAME"],
    safeDefaults: { MONGO_INITDB_ROOT_PASSWORD: randomPassword },
    weakValues: ["mongo", "mongo123", "mongoadmin"],
  },
  { imagePattern: /^redis(:|$)/, required: [] },
];

export function findRequiredSecrets(image: string): RequiredSecretRule | undefined {
  return REQUIRED_SECRETS_BY_IMAGE.find((rule) => rule.imagePattern.test(image));
}

export function isWeakSecretValue(_key: string, value: string, rule: RequiredSecretRule): boolean {
  const lowered = value.trim().toLowerCase();
  if (GENERIC_WEAK_VALUES.includes(lowered)) return true;
  if (rule.weakValues?.includes(lowered)) return true;
  return false;
}
