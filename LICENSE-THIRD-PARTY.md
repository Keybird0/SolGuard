# Third-Party Licenses

SolGuard is licensed under the [MIT License](./LICENSE). It depends on
third-party software distributed under its own licenses. This file
enumerates the direct runtime / dev dependencies of SolGuard and their
licenses. It is **informational**; the authoritative source is each
package's own `LICENSE` file inside `node_modules/` or `site-packages/`.

Last updated: 2026-04-20

---

## Node.js dependencies (`solguard-server/`)

| Package | Version | License |
|---------|---------|---------|
| `@solana/pay` | ^0.2.6 | Apache-2.0 |
| `@solana/web3.js` | ^1.95.0 | Apache-2.0 |
| `bignumber.js` | ^9.1.2 | MIT |
| `cors` | ^2.8.5 | MIT |
| `dotenv` | ^16.4.5 | BSD-2-Clause |
| `express` | ^4.19.2 | MIT |
| `nodemailer` | ^6.9.14 | MIT |
| `pino` | ^9.3.2 | MIT |
| `pino-http` | ^10.2.0 | MIT |
| `uuid` | ^10.0.0 | MIT |
| `zod` | ^3.23.8 | MIT |

### Dev dependencies

| Package | License |
|---------|---------|
| `typescript` | Apache-2.0 |
| `tsx` | MIT |
| `eslint` | MIT |
| `prettier` | MIT |
| `@typescript-eslint/*` | MIT / BSD-2-Clause |

## Python dependencies (`skill/solana-security-audit-skill/`)

| Package | License |
|---------|---------|
| `anthropic` | MIT |
| `openai` | Apache-2.0 |
| `pydantic` | MIT |
| `python-dotenv` | BSD-3-Clause |
| `pyyaml` | MIT |
| `httpx` | BSD-3-Clause |
| `tenacity` | Apache-2.0 |
| `pytest` | MIT |
| `ruff` | MIT |
| `black` | MIT |
| `mypy` | MIT |

## Upstream projects used as references (not redistributed)

These projects are **not** bundled in SolGuard releases; they inform
architecture and rule design only. Source clones may be placed under
`./references/` locally and are git-ignored.

- **OpenHarness** — Apache-2.0 (consult upstream)
- **GoatGuard** — consult upstream
- **Contract_Security_Audit_Skill** — consult upstream
- **Sealevel Attacks** (coral-xyz) — consult upstream

---

## License compatibility

All bundled dependencies use permissive licenses (MIT / BSD / Apache-2.0).
These are compatible with SolGuard's MIT license for both source and
binary redistribution. Apache-2.0 dependencies (`@solana/web3.js`,
`typescript`, `tenacity`, `openai`, `anchor`) carry a patent grant;
SolGuard inherits that grant when distributed together.

If you believe a package's license is misidentified here, please open an
issue at <https://github.com/Keybird0/SolGuard/issues>.
