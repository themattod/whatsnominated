import argparse
import json
from pathlib import Path

from year_data_utils import load_year_payload, validate_year_payload


def main():
    parser = argparse.ArgumentParser(description='Validate a nominee-year JSON payload.')
    parser.add_argument('file', type=Path, help='Path to JSON payload (single-year or years bundle).')
    parser.add_argument('--year', type=int, default=None, help='Year key to validate when file has multiple years.')
    parser.add_argument('--json', action='store_true', help='Print machine-readable JSON result.')
    args = parser.parse_args()

    year, payload, schema_version = load_year_payload(args.file, year=args.year)
    result = validate_year_payload(year, payload)
    result['schemaVersion'] = schema_version
    result['file'] = str(args.file)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f'File: {args.file}')
        print(f'Year: {result["year"]}')
        print(f'Schema version: {schema_version}')
        print(f'Counts: {result["counts"]}')
        for warning in result['warnings']:
            print(f'WARN: {warning}')
        for error in result['errors']:
            print(f'ERROR: {error}')
        print('Validation passed.' if not result['errors'] else 'Validation failed.')

    raise SystemExit(1 if result['errors'] else 0)


if __name__ == '__main__':
    main()
