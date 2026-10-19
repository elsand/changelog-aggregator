# Changelog Aggregator

Aggregates lines added to changelog files in public repositories in a GitHub organization.

The output is intentionally machine-oriented: it is delimited so an LLM or another
processor can later identify which repository and commit each block came from.

## Usage

```bash
python3 changelog_aggregator.py --org altinn --week 2026-W20
```

You can also run a custom inclusive date range:

```bash
python3 changelog_aggregator.py --org altinn --from 2026-05-01 --to 2026-05-07
```

Each run writes its report to a period-specific file under:

```text
.changelog-aggregator/runs/
```

The first run discovers public repositories and stores changelog paths in:

```text
.changelog-aggregator/changelogs.json
```

Discovery also records repositories that use GitHub-generated release notes via
`.github/release.yml`. For those repositories, published release bodies inside
the requested period are included alongside file-based changelog additions.

Later runs reuse that file. Force rediscovery with:

```bash
python3 changelog_aggregator.py --org altinn --week 2026-W20 --discover
```

Use rediscovery after repositories add or remove `.github/release.yml`.

Write to a specific report file:

```bash
python3 changelog_aggregator.py --org altinn --week 2026-W20 --output report.md
```

Write to stdout explicitly:

```bash
python3 changelog_aggregator.py --org altinn --week 2026-W20 --output -
```

Emit JSON:

```bash
python3 changelog_aggregator.py --org altinn --week 2026-W20 --format json
```

The default `llm` format contains only metadata and added changelog lines from
commits touching each discovered changelog file, plus published GitHub release
bodies for repositories configured with `.github/release.yml`. It does not
parse Markdown sections or infer release structure from changelog contents.

Repository display names are stored in:

```text
reponames.json
```

The file is generated automatically with each repository's full repository key
as the default display name. Edit values manually to produce clearer
human-facing digest headings without changing the repository identifiers. Multiple
repositories may intentionally map to the same display name, which lets related
subcomponents or split repositories collapse into one logical digest section.

Because `reponames.json` lives at the repository root, it can be versioned. It is
preserved by default once it exists. Regenerate it from the current discovery
index with:

```bash
python3 changelog_aggregator.py --org altinn --week 2026-W20 --refresh-reponames
```

The script prints progress to stderr while it works, keeping stdout reserved for
the report. Suppress progress output with:

```bash
python3 changelog_aggregator.py --org altinn --week 2026-W20 --quiet
```

GitHub rate-limit responses are retried automatically. The script honors
`retry-after` first, then `x-ratelimit-reset` when `x-ratelimit-remaining` is
`0`, and otherwise uses exponential backoff. Tune retry attempts with:

```bash
python3 changelog_aggregator.py --org altinn --week 2026-W20 --max-rate-limit-retries 8
```

## Turn Aggregation Output Into a Human Digest

`prompt.txt` contains instructions for converting a machine-oriented aggregation
run into a human-readable Markdown digest. It uses the repository display names
embedded in the aggregation output and tells the LLM to append source issue or
pull request links to matching summary bullets.

Set the aggregation file you want to summarize:

```bash
RUN=.changelog-aggregator/runs/changelog-aggregation-2026-W20.txt
```

Run Claude Code non-interactively and redirect the Markdown output to
`digest.md`:

```bash
python3 digest_with_claude.py "$RUN" digest.md
```

The helper script:
- loads `prompt.txt`
- replaces `{{REPONAMES}}` using only overridden mappings from `reponames.json`, where an override means `key != value`
- appends the aggregation run content
- invokes `claude -p` non-interactively with all tools disabled

The shared prompt builder can also be used directly, including from GitHub
Actions or with another LLM:

```bash
python3 build_digest_prompt.py "$RUN" .generated/digest-prompt.md
```

Set `GITHUB_TOKEN` to increase GitHub API limits.

## GitHub Actions Automation

The repository includes reusable workflows:

- `aggregate-changelogs.yml`: runs `changelog_aggregator.py` for `altinn`, restores/saves `.changelog-aggregator/changelogs.json` through GitHub Actions cache, and uploads `changelog-index` and `aggregation-output` artifacts.
- `build-digest-claude.yml`: downloads `aggregation-output`, installs Claude Code, runs `digest_with_claude.py`, and uploads `claude-digest`.
- `post-digest-slack.yml`: downloads `claude-digest` and posts it to Slack with `post_digest_slack.py`: the title and executive highlights as the channel message, the detailed changes as thread replies (split to stay within Slack's message limits).

Two orchestration workflows are also included:

- `manual-changelog.yml`: manually select ISO week, whether to rediscover, and whether to post to Slack.
- `weekly-changelog.yml`: runs every Monday at `06:00 UTC` for the previous ISO week.

Required repository secrets:

- `ALTINN_GITHUB_TOKEN`: GitHub token used by the aggregator when calling the GitHub API.
- `CLAUDE_CODE_OAUTH_TOKEN`: Claude subscription token used by `claude -p`. Generate it with `claude setup-token` (valid for one year) and rotate before it expires.
- `SLACK_BOT_TOKEN`: Slack app bot token (`xoxb-…`) with the `chat:write` scope. Invite the bot to the target channel.
- `SLACK_CHANNEL_ID`: ID of the channel to post to (for example `C0123456789`).
