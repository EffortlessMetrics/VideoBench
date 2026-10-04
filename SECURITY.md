# Security policy

## Reporting

Do not open a public issue for a vulnerability that could expose credentials, private benchmark assets, proprietary model output, local Resolve projects, or arbitrary code execution.

Report privately through GitHub's security-advisory interface for the repository owner.

## Threat boundaries

VideoBench treats source media, captions, spoken audio, candidate artifacts, logs, imported judgments, and community packs as untrusted input.

Initial official operation does not execute arbitrary contributed validator code. Candidate commands are explicit local-operator actions and must run inside an environment appropriate to their risk.

Never commit:

- provider API keys;
- Resolve database credentials;
- personal access tokens;
- licensed source media without redistribution rights;
- private-canary pack contents;
- unredacted personal data.

Supported security fixes target the latest main branch until formal releases begin.
