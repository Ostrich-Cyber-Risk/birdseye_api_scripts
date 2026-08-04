import argparse
import csv
import re
import sys
from typing import Dict, List, Optional, Tuple

from ostrichApi import (ApiError, Assessment, BusinessUnit, Contributor, OstrichApi,
                        OVERRIDE_STRATEGY, PROD_BASE_URL, TargetRequest, WEIGHTS, aspect_ids,
                        aspect_subs, business_unit_path, current_targets, flatten_business_units,
                        leaf_assessments, target_contributors)

TEMPLATE_FILE = 'OstrichTargetTemplate.csv'
TEMPLATE_COLUMNS = ['businessUnit', 'businessUnitId', 'assessment', 'assessmentId', 'aspectId',
                    'currentTarget', 'currentWeight', 'target', 'weight']
REQUIRED_COLUMNS = ['businessUnitId', 'assessmentId', 'aspectId']

BatchKey = Tuple[str, str]


def main() -> None:
    major_version = sys.version_info.major
    minor_version = sys.version_info.minor
    if major_version != 3 or minor_version < 12:
        raise Exception(f'Running in Python {major_version}.{minor_version} ... Minimum required Python version is 3.12')

    # Without this, progress on stdout and errors on stderr land out of order once the output is
    # redirected to a file, which makes a failed run hard to read back.
    sys.stdout.reconfigure(line_buffering=True)

    args = parse_args()

    api_key: str = input('Enter your Api Key:\n').strip()
    api_client = OstrichApi(api_key=api_key, base_url=args.baseUrl)

    if args.template:
        write_template(api_client, args)
    else:
        apply_targets(api_client, args)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Read and write assessment targets in bulk through the Birdseye public API.')

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--template', action='store_true',
                      help=f'Write every aspect of every assessment the key can reach to {TEMPLATE_FILE}, '
                           f'along with its current target, ready to be filled in.')
    mode.add_argument('--apply', metavar='CSV',
                      help='Read a filled-in CSV and save the targets in it.')

    parser.add_argument('--dryRun', action='store_true',
                        help='Check the CSV and report what would be sent, without saving anything.')
    parser.add_argument('--yes', action='store_true',
                        help='Answer yes to the prompt shown when someone has already set targets on an assessment.')
    parser.add_argument('--businessUnitFilter', type=re.compile,
                        help='A regex matched against business unit names. Template mode only.')
    parser.add_argument('--assessmentFilter', type=re.compile,
                        help='A regex matched against assessment names. Template mode only.')
    parser.add_argument('--baseUrl', default=PROD_BASE_URL,
                        help=f'The API to talk to. Defaults to {PROD_BASE_URL}.')

    return parser.parse_args()


def write_template(api_client: OstrichApi, args: argparse.Namespace) -> None:
    assessments = discover_assessments(api_client, args)
    if not assessments:
        print('No assessments matched.')
        return

    print(f'Reading aspects and current targets for {len(assessments)} assessment(s)...')
    rows: List[dict] = []
    for business_unit, assessment in assessments:
        label = f"{business_unit_path(business_unit)} > {assessment['assessmentName']}"
        try:
            content = api_client.get_assessment_content(assessment['businessUnitId'], assessment['assessmentId'])
            scores = api_client.get_scores(assessment['businessUnitId'], assessment['assessmentId'])
        except ApiError as error:
            print(f'  skipped {label} - {error.message}', file=sys.stderr)
            continue

        aspects = aspect_ids(content, scores)
        targets = current_targets(scores, aspects)
        print(f'  {label} - {len(aspects)} aspect(s)')

        for aspect in aspects:
            target, weight = targets.get(aspect, (None, None))
            rows.append({
                'businessUnit': business_unit.get('name', ''),
                'businessUnitId': assessment['businessUnitId'],
                'assessment': assessment['assessmentName'],
                'assessmentId': assessment['assessmentId'],
                'aspectId': aspect,
                'currentTarget': '' if target is None else target,
                'currentWeight': weight or '',
                'target': '',
                'weight': '',
            })

    if not rows:
        print('No aspects were found.')
        return

    with open(TEMPLATE_FILE, 'w', newline='', encoding='utf-8') as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=TEMPLATE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f'\nWrote {len(rows)} row(s) to {TEMPLATE_FILE}.')
    print('Fill in the target and weight columns, delete or blank the rows you do not want to change,')
    print(f'then run: python setTargets.py --apply {TEMPLATE_FILE} --dryRun')


def discover_assessments(api_client: OstrichApi,
                         args: argparse.Namespace) -> List[Tuple[BusinessUnit, Assessment]]:
    print('Retrieving business units...')
    business_units = flatten_business_units(api_client.get_business_units())
    if args.businessUnitFilter:
        business_units = [unit for unit in business_units
                          if args.businessUnitFilter.fullmatch(unit.get('name', ''))]
        print(f'  {len(business_units)} business unit(s) matched {args.businessUnitFilter.pattern}')

    print('Retrieving assessments...')
    matched: List[Tuple[BusinessUnit, Assessment]] = []
    for business_unit in business_units:
        for assessment in leaf_assessments(api_client.get_assessments(business_unit['businessUnitId'])):
            if args.assessmentFilter and not args.assessmentFilter.fullmatch(assessment['assessmentName']):
                continue
            matched.append((business_unit, assessment))
    return matched


def apply_targets(api_client: OstrichApi, args: argparse.Namespace) -> None:
    rows = read_rows(args.apply)
    batches, labels, problems = build_batches(rows)

    for problem in problems:
        print(f'{args.apply} {problem}', file=sys.stderr)

    if not batches:
        print('Nothing to save. Every row was blank or rejected.')
        sys.exit(1 if problems else 0)

    strategies: Dict[str, Optional[str]] = {}
    saved_targets = 0
    saved_assessments = 0
    failures: List[str] = []
    unverified: List[str] = []

    print(f'\n{len(batches)} assessment(s) to update.')
    for key, targets in batches.items():
        business_unit_id, assessment_id = key
        label = labels[key]
        print(f'\n{label}')

        try:
            content = api_client.get_assessment_content(business_unit_id, assessment_id)
            scores = api_client.get_scores(business_unit_id, assessment_id)
        except ApiError as error:
            print(f'  could not read the assessment - {error.message}', file=sys.stderr)
            failures.append(f'{label} - {error.message}')
            continue

        aspects = aspect_ids(content, scores)
        unknown = [target['aspectId'] for target in targets if target['aspectId'] not in set(aspects)]
        if unknown:
            # The API rejects the whole request if any one aspect id is wrong, so stop here rather
            # than send a batch that cannot succeed.
            print(f'  {len(unknown)} aspect id(s) do not exist on this assessment: {", ".join(unknown[:5])}',
                  file=sys.stderr)
            failures.append(f'{label} - unknown aspect id(s): {", ".join(unknown[:5])}')
            continue

        if business_unit_id not in strategies:
            strategies[business_unit_id] = read_target_strategy(api_client, business_unit_id)
        strategy = strategies[business_unit_id]

        contributors = target_contributors(scores, aspects)
        if contributors and strategy != OVERRIDE_STRATEGY and not args.yes:
            if not confirm_shared_targets(contributors):
                print('  skipped')
                continue

        print(f'  {len(targets)} target(s) to save')
        if args.dryRun:
            for target in targets[:5]:
                print(f'    {describe(target)}')
            if len(targets) > 5:
                print(f'    ... and {len(targets) - 5} more')
            continue

        try:
            api_client.save_targets(business_unit_id, assessment_id, targets)
        except ApiError as error:
            print(f'  failed - {error.message}', file=sys.stderr)
            failures.append(f'{label} - {error.message}')
            continue

        saved_assessments += 1
        saved_targets += len(targets)
        missing = verify_saved(api_client, business_unit_id, assessment_id, targets)
        if missing:
            print(f'  saved, but {len(missing)} value(s) did not read back: {", ".join(missing[:5])}',
                  file=sys.stderr)
            unverified.append(f'{label} - {", ".join(missing[:5])}')
        else:
            print('  saved and verified')

    report(args, saved_assessments, saved_targets, problems, failures, unverified)


def read_rows(path: str) -> List[dict]:
    # utf-8-sig so a CSV saved out of Excel does not carry its byte order mark into the first column name.
    with open(path, mode='r', newline='', encoding='utf-8-sig') as csv_file:
        reader = csv.DictReader(csv_file)
        missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise Exception(f'{path} is missing required column(s): {", ".join(missing)}')
        return list(reader)


def build_batches(rows: List[dict]) -> Tuple[Dict[BatchKey, List[TargetRequest]],
                                             Dict[BatchKey, str], List[str]]:
    batches: Dict[BatchKey, List[TargetRequest]] = {}
    labels: Dict[BatchKey, str] = {}
    problems: List[str] = []
    seen: set = set()

    for offset, row in enumerate(rows):
        line = offset + 2
        business_unit_id = (row.get('businessUnitId') or '').strip()
        assessment_id = (row.get('assessmentId') or '').strip()
        aspect_id = (row.get('aspectId') or '').strip()
        raw_target = (row.get('target') or '').strip()
        raw_weight = (row.get('weight') or '').strip().upper()

        if not business_unit_id and not assessment_id and not aspect_id:
            continue
        if not (business_unit_id and assessment_id and aspect_id):
            problems.append(f'line {line}: businessUnitId, assessmentId and aspectId are all required')
            continue
        if not raw_target and not raw_weight:
            continue

        target: TargetRequest = {'aspectId': aspect_id}
        if raw_target:
            try:
                target['target'] = int(raw_target)
            except ValueError:
                problems.append(f'line {line}: target "{raw_target}" is not a whole number')
                continue
        if raw_weight:
            if raw_weight not in WEIGHTS:
                problems.append(f'line {line}: weight "{raw_weight}" is not one of {", ".join(WEIGHTS)}')
                continue
            target['weight'] = raw_weight

        key: BatchKey = (business_unit_id, assessment_id)
        if (key, aspect_id) in seen:
            problems.append(f'line {line}: {aspect_id} appears more than once for this assessment')
            continue
        seen.add((key, aspect_id))

        batches.setdefault(key, []).append(target)
        labels.setdefault(key, describe_assessment(row, key))

    return batches, labels, problems


def describe_assessment(row: dict, key: BatchKey) -> str:
    business_unit = (row.get('businessUnit') or '').strip() or key[0]
    assessment = (row.get('assessment') or '').strip() or key[1]
    return f'{business_unit} > {assessment}'


def describe(target: TargetRequest) -> str:
    parts = [target['aspectId']]
    if 'target' in target:
        parts.append(f"target {target['target']}")
    if 'weight' in target:
        parts.append(f"weight {target['weight']}")
    return ', '.join(parts)


def read_target_strategy(api_client: OstrichApi, business_unit_id: str) -> Optional[str]:
    try:
        return api_client.get_business_unit(business_unit_id).get('targetStrategy')
    except ApiError as error:
        print(f'  could not read the target strategy - {error.message}', file=sys.stderr)
        return None


def confirm_shared_targets(contributors: List[Contributor]) -> bool:
    listed = ', '.join(f"{c['name']} ({c['aspectCount']} aspect(s))" for c in contributors)
    print(f'  targets already exist here, set by: {listed}')
    print('  this business unit averages targets across everyone who sets one, so saving replaces')
    print('  your own values and leaves theirs in the average')
    return input('  continue? [y/N] ').strip().lower() in ('y', 'yes')


def verify_saved(api_client: OstrichApi, business_unit_id: str, assessment_id: str,
                 targets: List[TargetRequest]) -> List[str]:
    try:
        scores = api_client.get_scores(business_unit_id, assessment_id)
    except ApiError as error:
        return [f'could not re-read the assessment - {error.message}']

    missing: List[str] = []
    for target in targets:
        subs = aspect_subs(scores, target['aspectId'])
        if 'target' in target and not any(sub.get('target') == target['target'] for sub in subs):
            missing.append(f"{target['aspectId']} target")
        if 'weight' in target and not any(sub.get('weightLabel') == target['weight'] for sub in subs):
            missing.append(f"{target['aspectId']} weight")
    return missing


def report(args: argparse.Namespace, saved_assessments: int, saved_targets: int,
           problems: List[str], failures: List[str], unverified: List[str]) -> None:
    print('')
    if args.dryRun:
        print('Dry run, nothing was saved.')
    else:
        print(f'Saved {saved_targets} target(s) across {saved_assessments} assessment(s).')

    if problems:
        print(f'{len(problems)} row(s) in {args.apply} were rejected before sending.')
    if failures:
        print(f'{len(failures)} assessment(s) failed:')
        for failure in failures:
            print(f'  {failure}')
    if unverified:
        print(f'{len(unverified)} assessment(s) saved values that did not read back:')
        for entry in unverified:
            print(f'  {entry}')

    if problems or failures or unverified:
        sys.exit(1)


if __name__ == '__main__':
    main()
