# Security Policy

- `DRIVEMATE_API_TOKEN`, `DRIVEMATE_SIMULATOR_TOKEN`, `API_KEY`, and `CRM_API_KEY` are environment-only.
- Never commit real credentials, access tokens, vehicle identifiers, or production user data.
- The external LLM is restricted to semantic understanding. It receives no tool schemas and has no direct execution authority.
- L2 confirmation is enforced by local safety/authorization components, not by an LLM prompt.
- Vehicle and order side effects must pass the local ConstraintShield, schema validation, authorization, execution, and audit chain.
- Rotate any credential immediately if it appears in source code, documentation, screenshots, logs, or Git history.
