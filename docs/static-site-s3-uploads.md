# Static-site artifacts and S3 upload rules

The two optional inputs below extend `static-site-deploy.yml`. Existing callers
that omit both retain the original jobs, inputs, permissions, S3 sync, deletion
default, and production CloudFront behavior. No changes to container workflows.

## Quick use

1. Build and test in a caller job, then upload its output with `actions/upload-artifact`.
2. Make the deploy job depend on that job using `needs`.
3. Set `github_actions_artifact_name` to that artifact's name. Keep the existing
   bucket, branch, commit, and CloudFront inputs. Optionally set `s3_upload_rules`.

| New input | Default | Meaning |
| --- | --- | --- |
| `github_actions_artifact_name` | `''` | Named GitHub Actions artifact from the **current caller run**; extracted directly into `source_path`. No site checkout in this mode. Omit to use the caller checkout at `commit_hash`. |
| `s3_upload_rules` | `''` | JSON array of supported, ordered S3 operations. Omit for the existing whole-directory sync using top-level `delete_removed`. |

The inputs are independent: an artifact can use the default sync, and rules can
upload checked-out files without an artifact. `source_path` stays required; with
an artifact it names the download directory (e.g. `site` or `.`), not a subdirectory
inside the artifact. Publish an artifact containing only deployable files. For
artifact mode, `commit_hash` does not select artifact contents: the upstream build
must check out that revision. Artifacts from another run/repository are unsupported.

Use a push-only caller on `develop` and `main` (legacy `master` is also supported).
The caller owns tests/builds and `needs`; this workflow never runs application code.
It selects dev for `develop`, prod for `main`/`master`, and skips other refs.
It does not change bucket visibility or provision infrastructure.

## Supported rules

`operation` is an enum: only `s3_copy` and `s3_sync` are accepted. Arbitrary
commands, AWS options, S3-to-S3 transfers, other destinations, and ACL changes
are unsupported. All rules are validated before uploads; execution stops at the
first failed AWS command. Uploads already completed are not rolled back.

| Operation | Required fields | Optional fields |
| --- | --- | --- |
| `s3_copy` (`aws s3 cp`) | `source_file`, `destination_key` | `cache_control`, `content_type`, `content_disposition` |
| `s3_sync` (`aws s3 sync`) | `source_directory`, `destination_prefix` | `exclude`, `include`, `delete_removed`, `cache_control`, `content_type`, `content_disposition` |

- Sources are relative to `source_path`; `source_directory: "."` uploads that whole directory.
- Destinations are exact keys/prefixes inside the selected bucket. `destination_prefix: ""`
  means bucket root. A copy key must name a file, not end with `/`.
- Relative paths only: no absolute paths, `..`, URIs, backslashes, or control characters.
  Symbolic links are rejected. Missing sources, unknown fields, wrong types, duplicate
  JSON keys, and unsupported operations fail with a configuration error.
- `exclude` and `include` are arrays of AWS CLI wildcard patterns. Excludes apply first,
  then includes; include matches override excludes. To select only HTML, use
  `"exclude": ["*"], "include": ["*.html"]`. Include alone does not exclude other files.
- Rule-level `delete_removed` defaults to **false**, independently of the existing
  top-level input. Set it to `true` only to delete missing objects under that rule's
  destination prefix. Excluded objects are not deleted. Overlapping deleting rules
  can remove earlier uploads; use disjoint prefixes or intentional exclusions.
- Header fields are non-empty strings. Sync uploads only new/changed files, so header
  changes alone do not update existing objects. Use `s3_copy` to reupload an unchanged
  file with different headers. Copy always uploads the file.
- Production CloudFront invalidation runs after all uploads succeed, when configured.
  As before, it submits an invalidation without waiting for completion; dev does not invalidate.

Example error: `Invalid S3 upload configuration: Rule 2: unsupported operation
'copy'; expected s3_copy or s3_sync`.

The opt-in path logs the environment/ref/commit, artifact or checkout source,
bucket, and each rule's operation, paths, deletion setting, and successful completion.
AWS CLI reports transferred/deleted objects and errors; a no-change sync still gets
a rule-completed line. The final S3 success line appears only after every rule passes.
CloudFront's separate step reports the submitted invalidation ID/status, not proof
that the cache has finished clearing. No credentials or file contents are logged.

## Caller example

Add a build job to your existing caller; its commands belong to your application.
This example assumes `npm run build` creates `dist/`.

```yaml
jobs:
  build-and-test:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v6
        with:
          ref: ${{ github.sha }}
      - uses: actions/setup-node@v6
        with:
          node-version: '22'
      - run: npm ci
      - run: npm test
      - run: npm run build
      - uses: actions/upload-artifact@v7
        with:
          name: website
          path: dist/
          if-no-files-found: error

  content:
    needs: build-and-test # Also depend on infrastructure if it is in this caller.
    uses: commercesong/org-reusable-workflows/.github/workflows/static-site-deploy.yml@main
    permissions:
      contents: read
      id-token: write
    secrets:
      aws_account_id_dev: ${{ secrets.AWS_ACCOUNT_ID_DEV }}
      aws_account_id_prod: ${{ secrets.AWS_ACCOUNT_ID_PROD }}
    with:
      commit_hash: ${{ github.sha }}
      ref: ${{ github.ref }}
      bucket_name_dev: my-site-dev
      bucket_name_prod: my-site-prod
      github_actions_artifact_name: website
      source_path: site
      s3_upload_rules: |
        [
          {
            "operation": "s3_sync",
            "source_directory": ".",
            "destination_prefix": "",
            "exclude": ["*.html", "contact.vcf"],
            "cache_control": "public,max-age=3600"
          },
          {
            "operation": "s3_copy",
            "source_file": "contact.vcf",
            "destination_key": "contact.vcf",
            "content_type": "text/vcard",
            "content_disposition": "attachment; filename=\"contact.vcf\"",
            "cache_control": "no-cache"
          },
          {
            "operation": "s3_copy",
            "source_file": "contact.vcf",
            "destination_key": "contact.vcf.",
            "content_type": "text/vcard",
            "content_disposition": "attachment; filename=\"contact.vcf\"",
            "cache_control": "no-cache"
          },
          {
            "operation": "s3_sync",
            "source_directory": ".",
            "destination_prefix": "",
            "exclude": ["*"],
            "include": ["*.html"],
            "cache_control": "no-cache,max-age=0,must-revalidate"
          }
        ]
```

For Rosa, the build job runs its existing Python/Node tests and
`python3 scripts/prepare_site.py --environment dev|prod --output site`, selecting
the environment explicitly from the branch; upload `site/` as the artifact.
Use `rosa.vcf`/`rosa.vcf.` in the copy rules. Keep its infrastructure dependencies.
These rules preserve upload order, versioned assets, cache headers, and both vCard
URLs without deleting historical media. Changing Rosa's production branch or public
dev hosting is a caller/infrastructure migration, not part of this shared interface.

## Maintainer checks

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m unittest discover -s tests -p 'test_static_site_uploads.py' -v
actionlint -shellcheck= .github/workflows/static-site-deploy.yml
```

The unit suite executes the workflow's actual inline planner and compares the
legacy jobs/inputs to the pre-extension revision. Use full git history for that
comparison. The planner is inline so a caller's pinned workflow revision also pins
its implementation; it never downloads a helper from a moving branch.

Run the real S3 contract test separately against a private CommerceSong dev bucket:

```sh
export AWS_PROFILE=csdev
export S3_TEST_ACCOUNT_ID=478543871670
export S3_TEST_BUCKET=slopapalooza-com-dev
.venv/bin/python -m unittest discover -s tests -p 'test_static_site_s3_integration.py' -v
```

It requires all public-access blocks, verifies the dev account, writes only a unique
`_workflow-tests/static-site/` prefix, and cleans its objects. It verifies real S3
headers, aliases, filter behavior, retention, and explicit deletion. It does not
verify GitHub artifact transport/OIDC or CloudFront invalidation; those require
a GitHub Actions run after the shared change is published.

After publishing, run the **Smoke test static-site deployment (dev only)** workflow
manually in this repository. It calls the workflow at the same revision, exercising
artifact upload/download and real dev OIDC/S3 operations. It checks exact uploaded
bytes and headers, then cleans its unique run/attempt prefix even if verification
fails. Its account and private bucket are fixed; it never deploys a website or calls
production/CloudFront. If the runner is forcibly cancelled or credentials fail before
cleanup, the logged test prefix identifies the objects needing cleanup. No dummy
website commit is needed; Rosa must first adopt the reusable caller to test its own
pipeline.

To retry, use **Re-run all jobs** or a fresh dispatch, not **Re-run failed jobs**.
The artifact and destination are specific to the run attempt; selectively retrying
jobs can reuse an earlier artifact or skip the uploads needed for verification.

References: [GitHub artifact download](https://github.com/actions/download-artifact),
[AWS S3 sync semantics](https://docs.aws.amazon.com/cli/latest/reference/s3/sync.html).
