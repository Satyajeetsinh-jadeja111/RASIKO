# Rasiko contributor and AI handoff rules

Read `project.md` and `README.md` before changing the project. Preserve the existing brand and use mobile-first layouts.

For every meaningful change:
- Update `project.md` with the date, intent, behavior changed, configuration/migrations, actual checks and results, and remaining work.
- Update `README.md` when setup, deployment, environment, integration, backup, recovery, or user guidance changes.
- Keep planned, implemented, verified, and blocked work separate. Never claim checks passed unless run.
- Never record credentials, private keys, customer data, or decrypted integration configuration in documentation or logs.
- Test payment/inventory changes against an isolated PostgreSQL database. Do not migrate, seed, or benchmark the live database without explicit authorization.
- Capture real before/after browser evidence for visual fixes; record unavailable flows as blockers.
- Run relevant checks and the documentation guard before handoff. Document external prerequisites instead of pretending they were verified.
