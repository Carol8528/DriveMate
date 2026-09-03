# Security Notes

- No production secret is stored in source code.
- `DRIVEMATE_API_TOKEN`, `DRIVEMATE_SIMULATOR_TOKEN`, `DASHSCOPE_API_KEY`, and `CRM_API_KEY` are environment-only.
- The Agent API and cockpit simulator reject unauthenticated requests with HTTP 401.
- `start_demo.py` binds both services to loopback by default and generates separate one-time tokens.
- L2 confirmation is enforced by `safety_guard.py`, not by the LLM prompt alone.
- Confirmation grants bind the tool and resolved arguments to safety-relevant snapshot data; volatile sensor timestamps are excluded.
- `contact_vehicle` requires verified passenger/vehicle coordinates and a measured distance <= 100m.
- Frontend-generated sensor values are explicitly marked as simulated.
- SQLite audit records are demo data and should follow normal retention/access-control policies in a production deployment.
