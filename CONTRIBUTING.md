# Contributing

Contributions are welcome under the [contributor licence agreement](CLA.md). The project is offered under the [GNU Affero General Public License, version 3](LICENSE) and, separately, under a [commercial licence](COMMERCIAL-LICENSE.md); the agreement is what allows both.

## Before the first pull request

1. Read [CLA.md](CLA.md).
2. Add an entry to `signatories` in [.github/cla-signatories.json](.github/cla-signatories.json) in the same pull request as Your first change:

   ```json
   { "login": "your-github-login", "name": "Your Full Name", "date": "2026-01-31", "cla_version": "1.0" }
   ```

   `login` is Your GitHub account name, `date` is the signing date (`YYYY-MM-DD`) and `cla_version` is the version at the top of CLA.md. The entry is Your signature.
3. Make sure each commit's author is linked to that GitHub account (the commit email is one verified on the account).

The `CLA` check on a pull request fails until every commit author is a signatory at the current version. Maintainers, and automation such as Dependabot, are listed separately in the same file and need no entry.

## Working on the code

Setup, the test suites, linting and reproducing CI locally are in [docs/development.md](docs/development.md). The rules that apply to every change (documentation, tests, security and accessibility conventions) are in [CLAUDE.md](CLAUDE.md).
