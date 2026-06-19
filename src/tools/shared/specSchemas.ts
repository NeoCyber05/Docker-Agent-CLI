import { z } from "zod";

export const ServiceSpecSchema = z.object({
  image: z.string(),
  command: z.union([z.string(), z.array(z.string())]).optional(),
  ports: z.array(z.string()).optional(),
  environment: z.record(z.string()).optional(),
  env_file: z.array(z.string()).optional(),
  volumes: z.array(z.string()).optional(),
  depends_on: z
    .union([
      z.array(z.string()),
      z.record(
        z.object({
          condition: z.enum([
            "service_started",
            "service_healthy",
            "service_completed_successfully",
          ]),
        }),
      ),
    ])
    .optional(),
  healthcheck: z
    .object({
      test: z.union([z.string(), z.array(z.string())]),
      interval: z.string().optional(),
      timeout: z.string().optional(),
      retries: z.number().optional(),
      start_period: z.string().optional(),
    })
    .optional(),
  restart: z.enum(["no", "always", "on-failure", "unless-stopped"]).optional(),
  labels: z.record(z.string()).optional(),
  networks: z.array(z.string()).optional(),
  scale: z.number().int().min(1).optional(),
});

export const ServicesSchema = z
  .record(ServiceSpecSchema)
  .refine((services) => Object.keys(services).length > 0, {
    message: "at least one service",
  });

export const StackDraftSchema = z.object({
  stackName: z.string().regex(/^[a-z][a-z0-9_-]{0,62}$/),
  intent: z.string(),
  services: ServicesSchema,
  networks: z.record(z.unknown()).optional(),
  volumes: z.record(z.unknown()).optional(),
  configFiles: z.record(z.string()).optional(),
});

export type StackDraft = z.infer<typeof StackDraftSchema>;
export type DraftServiceSpec = StackDraft["services"][string];
