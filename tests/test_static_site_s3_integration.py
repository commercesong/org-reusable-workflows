"""Real S3 contract check. Explicit private dev bucket required; no production writes.

Creates and cleans only a unique _workflow-tests/static-site/ prefix. Run separately
from the offline unit suite; see docs/static-site-s3-uploads.md.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

import boto3

from test_static_site_uploads import PLANNER_CODE, STEPS


class S3IntegrationTests(unittest.TestCase):
    def test_real_uploads_headers_aliases_filters_and_deletion(self):
        bucket = os.environ['S3_TEST_BUCKET']
        expected_account = os.environ['S3_TEST_ACCOUNT_ID']
        # This test fixture belongs to CommerceSong dev; never accept prod.
        self.assertEqual(expected_account, '478543871670')
        session = boto3.Session(region_name='us-east-1')
        self.assertEqual(session.client('sts').get_caller_identity()['Account'], expected_account)
        s3 = session.client('s3')
        block = s3.get_public_access_block(Bucket=bucket)['PublicAccessBlockConfiguration']
        self.assertTrue(all(block.values()), 'Integration fixture must block all public S3 access')
        prefix = f'_workflow-tests/static-site/{uuid.uuid4().hex}/'
        print(f'Integration fixture: s3://{bucket}/{prefix}', flush=True)

        def keys():
            return [item['Key'] for page in s3.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix)
                    for item in page.get('Contents', [])]

        self.assertEqual(keys(), [])

        def cleanup():
            for key in keys():
                s3.delete_object(Bucket=bucket, Key=key)
            self.assertEqual(keys(), [], 'Test prefix cleanup failed')

        self.addCleanup(cleanup)
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary).resolve()
            site = workspace / 'site'
            site.mkdir()
            (site / 'index.html').write_text('<h1>Integration test</h1>')
            (site / 'app.js').write_text('console.log("test")')
            (site / 'contact.vcf').write_text('BEGIN:VCARD\nEND:VCARD\n')
            (site / 'draft.txt').write_text('must be excluded')
            rules = [
                {'operation': 's3_sync', 'source_directory': '.', 'destination_prefix': prefix,
                 'exclude': ['*.html', '*.vcf', '*.txt'], 'cache_control': 'public,max-age=3600'},
                {'operation': 's3_copy', 'source_file': 'contact.vcf', 'destination_key': prefix + 'contact.vcf',
                 'content_type': 'text/vcard', 'content_disposition': 'attachment; filename="contact.vcf"'},
                {'operation': 's3_copy', 'source_file': 'contact.vcf', 'destination_key': prefix + 'contact.vcf.',
                 'content_type': 'text/vcard'},
                {'operation': 's3_sync', 'source_directory': '.', 'destination_prefix': prefix,
                 'exclude': ['*'], 'include': ['*.html'], 'cache_control': 'no-cache'},
            ]
            env = dict(os.environ, SOURCE_PATH='site', BUCKET_NAME=bucket, DELETE_REMOVED='true',
                       ARTIFACT_NAME='', AWS_ENV='dev', DEPLOY_REF='refs/heads/develop', COMMIT_HASH='integration-fixture',
                       GITHUB_WORKSPACE=str(workspace), RUNNER_TEMP=str(workspace))
            executor = next(step['run'] for step in STEPS if step['name'] == 'Execute S3 upload plan')

            def deploy(upload_rules):
                env['S3_UPLOAD_RULES'] = json.dumps(upload_rules)
                subprocess.run([sys.executable, '-c', PLANNER_CODE], env=env, check=True)
                result = subprocess.run([sys.executable, '-c', executor], env=env, check=True,
                                        capture_output=True, text=True)
                print(result.stdout, end='')
                self.assertIn(f'S3 upload plan completed: {len(upload_rules)}/{len(upload_rules)} rules succeeded', result.stdout)

            s3.put_object(Bucket=bucket, Key=prefix + 'retained.txt', Body=b'test fixture')
            deploy(rules)
            self.assertEqual(set(keys()), {prefix + name for name in
                             ('app.js', 'contact.vcf', 'contact.vcf.', 'index.html', 'retained.txt')})
            self.assertEqual(s3.head_object(Bucket=bucket, Key=prefix + 'app.js')['CacheControl'], 'public,max-age=3600')
            self.assertEqual(s3.head_object(Bucket=bucket, Key=prefix + 'index.html')['CacheControl'], 'no-cache')
            vcard = s3.head_object(Bucket=bucket, Key=prefix + 'contact.vcf')
            self.assertEqual(vcard['ContentType'], 'text/vcard')
            self.assertEqual(vcard['ContentDisposition'], 'attachment; filename="contact.vcf"')
            self.assertEqual(s3.get_object(Bucket=bucket, Key=prefix + 'contact.vcf.')['Body'].read(),
                             (site / 'contact.vcf').read_bytes())
            # Header changes on unchanged files require s3_copy; sync skips unchanged bytes.
            deploy([{**rules[1], 'content_type': 'text/plain'}])
            self.assertEqual(s3.head_object(Bucket=bucket, Key=prefix + 'contact.vcf')['ContentType'], 'text/plain')
            # Explicit deletion is scoped to this prefix; excluded files are retained.
            deploy([{'operation': 's3_sync', 'source_directory': '.', 'destination_prefix': prefix,
                     'exclude': ['*.txt'], 'delete_removed': True}])
            self.assertEqual(set(keys()), {prefix + name for name in
                             ('app.js', 'contact.vcf', 'index.html', 'retained.txt')})


if __name__ == '__main__':
    unittest.main()
