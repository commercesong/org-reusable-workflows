"""Fixture for the manual GitHub Actions smoke test; fixed private dev target only."""

import argparse
import os
from pathlib import Path
import re

import boto3


DEV_ACCOUNT = '478543871670'
BUCKET = 'slopapalooza-com-dev'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'verify-and-cleanup'])
    operation = parser.parse_args().operation
    run_id = os.environ['GITHUB_RUN_ID']
    attempt = os.environ['GITHUB_RUN_ATTEMPT']
    if not re.fullmatch(r'[0-9]+', run_id) or not re.fullmatch(r'[0-9]+', attempt):
        raise ValueError('Expected numeric GitHub run ID and attempt for the isolated test prefix')
    prefix = f'_workflow-tests/static-site/github-{run_id}-{attempt}/'
    session = boto3.Session(region_name='us-east-1')
    if session.client('sts').get_caller_identity()['Account'] != DEV_ACCOUNT:
        raise RuntimeError('Smoke test requires the CommerceSong dev account')
    s3 = session.client('s3')
    block = s3.get_public_access_block(Bucket=BUCKET)['PublicAccessBlockConfiguration']
    if not all(block.get(name) is True for name in
               ('BlockPublicAcls', 'IgnorePublicAcls', 'BlockPublicPolicy', 'RestrictPublicBuckets')):
        raise RuntimeError('Smoke test bucket must block all public S3 access')
    print(f'Dev smoke fixture: s3://{BUCKET}/{prefix}', flush=True)

    def keys():
        return {item['Key'] for page in s3.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix=prefix)
                for item in page.get('Contents', [])}

    marker = f'GitHub run {run_id}, attempt {attempt}, commit {os.environ["GITHUB_SHA"]}\n'
    files = {'index.html': f'<h1>Static-site smoke test</h1>\n<!-- {marker.strip()} -->\n'.encode(),
             'proof.txt': marker.encode(), 'contact.vcf': b'BEGIN:VCARD\nVERSION:3.0\nFN:Workflow test\nEND:VCARD\n'}
    if operation == 'prepare':
        if keys():
            raise RuntimeError('Expected an empty test prefix; refusing to overwrite existing objects')
        site = Path('smoke-site')
        site.mkdir()
        for name, body in files.items():
            (site / name).write_bytes(body)
        print(f'Prepared {len(files)} tiny files; private dev account and empty prefix confirmed')
        return

    try:
        if os.environ['DEPLOY_RESULT'] != 'success':
            raise RuntimeError(f'Reusable deployment job did not succeed: {os.environ["DEPLOY_RESULT"]}')
        expected = {**files, 'contact.vcf.': files['contact.vcf']}
        if keys() != {prefix + name for name in expected}:
            raise AssertionError('Uploaded keys do not match the four expected smoke-test objects')
        for name, body in expected.items():
            response = s3.get_object(Bucket=BUCKET, Key=prefix + name)
            if response['Body'].read() != body:
                raise AssertionError(f'Uploaded bytes differ for {name}')
            if name.startswith('contact.vcf'):
                if response['ContentType'] != 'text/vcard':
                    raise AssertionError(f'Incorrect Content-Type for {name}')
            elif response.get('CacheControl') != 'no-cache':
                raise AssertionError(f'Incorrect Cache-Control for {name}')
            if name == 'contact.vcf' and response.get('ContentDisposition') != 'attachment; filename="contact.vcf"':
                raise AssertionError('Incorrect vCard Content-Disposition')
            print(f'Verified {name}: exact bytes and expected headers', flush=True)
        print('Smoke test passed: artifact transport, dev OIDC, S3 sync/copy, aliases and headers', flush=True)
    finally:
        for key in keys():
            s3.delete_object(Bucket=BUCKET, Key=key)
        if keys():
            raise RuntimeError('Smoke fixture cleanup failed')
        print('Cleanup complete: isolated test prefix is empty', flush=True)


if __name__ == '__main__':
    main()
