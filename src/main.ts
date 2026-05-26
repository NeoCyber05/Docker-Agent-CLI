import { Command } from "commander";

export async function main(argv: string[]): Promise<number> {
  const program = new Command();
  program
    .name("docker-agent")
    .description("Natural-language CLI for managing Docker infrastructure")
    .version("0.1.0", "-v, --version", "print version");

  program.exitOverride();
  try {
    await program.parseAsync(argv);
    return 0;
  } catch (err) {
    if ((err as { code?: string }).code === "commander.version") return 0;
    if ((err as { code?: string }).code === "commander.helpDisplayed") return 0;
    process.stderr.write(`${(err as Error).message}\n`);
    return 1;
  }
}
