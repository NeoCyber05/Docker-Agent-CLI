import { z } from "zod";
import type { ServiceSpec } from "../../types/stack";

// Re-export resolved ServiceSpec as DraftServiceSpec for backward compatibility in validation tools
export type DraftServiceSpec = ServiceSpec;

// Supported catalog ids
const APPROVED_CATALOG_IDS = [
  "postgresql:16",
  "postgresql:15",
  "redis:7",
  "redis:6",
  "mysql:8.0",
  "mongodb:6.0",
  "nginx:1.27",
] as const;

export const HybridServiceIntentSchema = z
  .object({
    name: z.string().regex(/^[a-z][a-z0-9_-]{0,62}$/),
    kind: z.enum(["catalog", "custom"]),
    catalogId: z.string().optional(),
    image: z.string().optional(),
    command: z.union([z.string(), z.array(z.string())]).optional(),
    environment: z.record(z.string()).optional(),
    exposure: z.enum(["internal", "public"]).optional(),
    containerPort: z.number().optional(),
    hostPort: z.number().optional(),
    persistence: z
      .object({
        path: z.string().optional(),
        size: z.string().optional(),
      })
      .optional(),
    resources: z.enum(["small", "medium", "large"]).optional(),
    depends_on: z.array(z.string()).optional(),
    scale: z.number().int().min(1).optional(),
    configMounts: z
      .array(
        z.object({
          hostPath: z.string(),
          containerPath: z.string(),
        }),
      )
      .optional(),
  })
  .superRefine((val, ctx) => {
    if (val.kind === "catalog") {
      if (!val.catalogId) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "catalogId is required when kind is 'catalog'",
          path: ["catalogId"],
        });
      } else if (!APPROVED_CATALOG_IDS.includes(val.catalogId as any)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `catalogId '${val.catalogId}' is not allowed. Approved catalogIds: ${APPROVED_CATALOG_IDS.join(", ")}`,
          path: ["catalogId"],
        });
      }
      if (val.image) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "image cannot be specified for catalog services",
          path: ["image"],
        });
      }
    } else if (val.kind === "custom") {
      if (!val.image) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "image is required when kind is 'custom'",
          path: ["image"],
        });
      }
      if (val.catalogId) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "catalogId cannot be specified for custom services",
          path: ["catalogId"],
        });
      }
    }
  });

export const ServicesSchema = z
  .array(HybridServiceIntentSchema)
  .refine((services) => services.length > 0, {
    message: "at least one service",
  })
  .refine(
    (services) => {
      const names = services.map((s) => s.name);
      return new Set(names).size === names.length;
    },
    {
      message: "service names must be unique",
    },
  );

export const StackDraftSchema = z.object({
  stackName: z.string().regex(/^[a-z][a-z0-9_-]{0,62}$/),
  intent: z.string(),
  networkName: z.string().regex(/^[a-z][a-z0-9_-]{0,62}$/).optional(),
  services: ServicesSchema,
  configFiles: z.record(z.string()).optional(),
});

export type StackDraft = z.infer<typeof StackDraftSchema>;
export type HybridServiceIntent = z.infer<typeof HybridServiceIntentSchema>;
