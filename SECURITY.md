# Security policy

## Scope

BuktiScope is an experimental, local-first image-screening tool. It is not a bank verification service and must not be used as the sole basis for releasing goods, denying a customer, or alleging fraud.

## Reporting a vulnerability

Please do not publish customer receipts, account details, access tokens, or other personal information in a public issue. For a security-sensitive report, contact the repository owner privately through GitHub's security advisory feature.

Include the affected version, a concise description, reproducible steps using synthetic or redacted files, and the potential impact.

## Data handling

The application processes request image bytes in memory and does not create an upload folder or persistent evidence database. The SHA-256 digest is kept in a bounded in-memory set for duplicate detection during the running process. Do not expose an unauthenticated development server to the public internet.

Reverse proxies, hosting platforms, operating systems, and process managers may independently record requests or temporary state. Review their configuration before deployment.
