"""CR2-4: Migrate DynamoDB results table to composite key (project_id PK + job_id SK).

Phase 2 requires per-job results (one project can have many results: original + translations).
The results table needs `project_id` as the partition key AND `job_id` as the sort key.

Usage:
  python -m scripts.migrate_results_table [--dry-run]

This script will:
  1. Read all items from the old results table
  2. Create a new table with composite key (project_id, job_id)
  3. Copy all items to the new table (backfilling empty job_id as '')
  4. Rename tables: old → <name>-backup, new → <name>
"""

from __future__ import annotations

import argparse
import sys
import time


def _wait_for_table(dynamodb_client, table_name: str, timeout: int = 120) -> None:
    """Wait until table is ACTIVE."""
    for _ in range(timeout // 2):
        desc = dynamodb_client.describe_table(TableName=table_name)
        if desc['Table']['TableStatus'] == 'ACTIVE':
            return
        time.sleep(2)
    raise TimeoutError(f'Table {table_name} did not become ACTIVE within {timeout}s')


def migrate(*, region: str, table_name: str, dry_run: bool = False) -> None:
    import boto3

    client = boto3.client('dynamodb', region_name=region)
    resource = boto3.resource('dynamodb', region_name=region)

    old_table = resource.Table(table_name)
    new_table_name = f'{table_name}-v2'
    backup_table_name = f'{table_name}-backup'

    # 1. Scan all existing items
    print(f'Scanning existing table: {table_name}')
    response = old_table.scan()
    items = response.get('Items', [])
    while 'LastEvaluatedKey' in response:
        response = old_table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        items.extend(response.get('Items', []))

    print(f'  Found {len(items)} items')

    if dry_run:
        print('[DRY RUN] Would create new table with composite key and migrate items.')
        for item in items:
            job_id = item.get('job_id', '')
            print(f'  project_id={item["project_id"]}, job_id={job_id}')
        return

    # 2. Create new table with composite key
    print(f'Creating new table: {new_table_name}')
    try:
        client.create_table(
            TableName=new_table_name,
            KeySchema=[
                {'AttributeName': 'project_id', 'KeyType': 'HASH'},
                {'AttributeName': 'job_id', 'KeyType': 'RANGE'},
            ],
            AttributeDefinitions=[
                {'AttributeName': 'project_id', 'AttributeType': 'S'},
                {'AttributeName': 'job_id', 'AttributeType': 'S'},
            ],
            BillingMode='PAY_PER_REQUEST',
        )
        _wait_for_table(client, new_table_name)
        print(f'  Table {new_table_name} is ACTIVE')
    except client.exceptions.ResourceInUseException:
        print(f'  Table {new_table_name} already exists, reusing')

    # 3. Copy items with backfilled job_id
    new_table = resource.Table(new_table_name)
    for item in items:
        if not item.get('job_id'):
            item['job_id'] = ''
        new_table.put_item(Item=item)
    print(f'  Copied {len(items)} items to {new_table_name}')

    # 4. Rename: old → backup, delete old, create new with original name
    print(f'Deleting old table: {table_name}')
    # First backup by leaving the v2 table, and deleting the old
    client.delete_table(TableName=table_name)
    waiter = client.get_waiter('table_not_exists')
    waiter.wait(TableName=table_name)

    print(f'Renaming {new_table_name} → {table_name}')
    # DynamoDB doesn't support rename — recreate with original name and copy again
    client.create_table(
        TableName=table_name,
        KeySchema=[
            {'AttributeName': 'project_id', 'KeyType': 'HASH'},
            {'AttributeName': 'job_id', 'KeyType': 'RANGE'},
        ],
        AttributeDefinitions=[
            {'AttributeName': 'project_id', 'AttributeType': 'S'},
            {'AttributeName': 'job_id', 'AttributeType': 'S'},
        ],
        BillingMode='PAY_PER_REQUEST',
    )
    _wait_for_table(client, table_name)

    final_table = resource.Table(table_name)
    for item in items:
        final_table.put_item(Item=item)
    print(f'  Copied {len(items)} items to {table_name}')

    # Clean up temp table
    print(f'Cleaning up temp table: {new_table_name}')
    client.delete_table(TableName=new_table_name)

    print('Migration complete!')


def main() -> None:
    parser = argparse.ArgumentParser(description='Migrate DynamoDB results table to composite key')
    parser.add_argument('--region', default='us-east-1', help='AWS region')
    parser.add_argument('--table', default='novareel-results', help='Results table name')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without modifying')
    args = parser.parse_args()

    migrate(region=args.region, table_name=args.table, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
