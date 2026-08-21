import argparse
import csv
import getpass
import os
import re
import sys
from typing import Dict, List, Optional, Set, Tuple

from ostrichApi import (ApiError, Assessment, BusinessUnit, Contributor, OstrichApi,
                        OVERRIDE_STRATEGY, PROD_BASE_URL, TargetRequest, WEIGHTS, aspect_ids,
                        aspect_subs, current_targets, flatten_business_units, leaf_assessments,
                        sub_holds, target_contributors)

TEMPLATE_FILE = 'OstrichTargetTemplate.csv'
TEMPLATE_COLUMNS = ['businessUnit', 'businessUnitId', 'assessment', 'assessmentId', 'aspectId',
                    'currentTarget', 'currentWeight', 'target', 'weight']
REQUIRED_COLUMNS = ['businessUnitId', 'assessmentId', 'aspectId']
EDITABLE_COLUMNS = ['target', 'weight']
API_KEY_ENV_VAR = 'OSTRICH_API_KEY'

BatchKey = Tuple[str, str]


class SetupError(Exception):
    """Something the operator has to fix before the script can do anything. Reported as one line
    rather than a traceback, because the people running this are not reading the source."""


def main() -> None:
    major_version = sys.version_info.major
    minor_version = sys.version_info.minor
    if major_version != 3 or minor_version < 12:
        raise Exception(f'Running in Python {major_version}.{minor_version} ... Minimum required Python version is 3.12')

    # Without this, progress on stdout and errors on stderr land out of order once the output is
    # redirected to a file, which makes a failed run hard to read back.
    sys.stdout.reconfigure(line_buffering=True)

    args = parse_args()

    try:
        if args.apply:
            require_answerable_prompts(args)
        api_client = OstrichApi(api_key=read_api_key(), base_url=args.baseUrl)
        if args.template:
            write_template(api_client, args)
        else:
            apply_targets(api_client, args)
    except SetupError as error:
        print(f'{error}', file=sys.stderr)
        sys.exit(2)
    except ValueError as error:
        print(f'{error}', file=sys.stderr)
        sys.exit(2)
    except ApiError as error:
        print(f'{error}', file=sys.stderr)
        sys.exit(2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Read and write assessment targets in bulk through the Birdseye public API.')

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--template', nargs='?', const=TEMPLATE_FILE, metavar='CSV',
                      help=f'Write every aspect of every assessment the key can reach to a CSV, along '
                           f'with its current target, ready to be filled in. Defaults to {TEMPLATE_FILE}.')
    mode.add_argument('--apply', metavar='CSV',
                      help='Read a filled-in CSV and save the targets in it.')

    parser.add_argument('--dryRun', action='store_true',
                        help='Check the CSV and report what would be sent, without saving anything. '
                             'Applies to --apply.')
    parser.add_argument('--yes', action='store_true',
                        help='Answer yes to the prompt shown when someone has already set targets on '
                             'an assessment. Required when running unattended.')
    parser.add_argument('--overwrite', action='store_true',
                        help='Allow --template to replace an existing file.')
    parser.add_argument('--businessUnitFilter', type=re.compile,
                        help='A regex matched against business unit names. Applies to --template.')
    parser.add_argument('--assessmentFilter', type=re.compile,
                        help='A regex matched against assessment names. Applies to --template.')
    parser.add_argument('--baseUrl', default=PROD_BASE_URL,
                        help=f'The API to talk to. Must be https. Defaults to {PROD_BASE_URL}.')

    return parser.parse_args()


def read_api_key() -> str:
    from_env = os.environ.get(API_KEY_ENV_VAR, '').strip()
    if from_env:
        return from_env
    if not sys.stdin.isatty():
        raise SetupError(f'No terminal to read the API key from. Set {API_KEY_ENV_VAR} instead of '
                         f'piping the key in, so the key does not consume the input the prompts need.')
    # getpass rather than input so the key does not stay in the scrollback of a shared console.
    return getpass.getpass('Enter your Api Key (not shown): ').strip()


def require_answerable_prompts(args: argparse.Namespace) -> None:
    """The confirmation during --apply cannot be answered without a terminal, and finding that out
    halfway through means some assessments are already written. Refuse before the first write."""
    if args.yes or args.dryRun or sys.stdin.isatty():
        return
    raise SetupError('No terminal available to confirm writes to assessments that already have '
                     'targets. Re-run with --yes to accept them all, or --dryRun to check the file.')


def write_template(api_client: OstrichApi, args: argparse.Namespace) -> None:
    if os.path.exists(args.template) and not args.overwrite:
        raise SetupError(f'{args.template} already exists. Move it, choose another name with '
                         f'--template <file>, or pass --overwrite to replace it.')

    assessments, denied = discover_assessments(api_client, args)
    if denied:
        print(f'  {len(denied)} business unit(s) skipped, the key holds no roles on them')
    if not assessments:
        print('No assessments matched.')
        return

    print(f'Reading aspects and current targets for {len(assessments)} assessment(s)...')
    rows: List[dict] = []
    unreadable: List[str] = []
    for unit_path, business_unit, assessment in assessments:
        label = f"{unit_path} > {assessment['assessmentName']}"
        try:
            content = api_client.get_assessment_content(assessment['businessUnitId'], assessment['assessmentId'])
            scores = api_client.get_scores(assessment['businessUnitId'], assessment['assessmentId'])
        except ApiError as error:
            print(f'  could not read {label} - {error.message}', file=sys.stderr)
            unreadable.append(f'{label} - {error.message}')
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
        sys.exit(1 if unreadable else 0)

    # utf-8-sig so Excel opens the file as UTF-8 and writes it back the same way.
    with open(args.template, 'w', newline='', encoding='utf-8-sig') as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=TEMPLATE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f'\nWrote {len(rows)} row(s) to {args.template}.')
    print('Fill in the target and weight columns, leave the rows you do not want to change blank,')
    print(f'then run: python setTargets.py --apply {args.template} --dryRun')

    if unreadable:
        print(f'\n{len(unreadable)} assessment(s) could not be read, so this template is incomplete:',
              file=sys.stderr)
        for entry in unreadable:
            print(f'  {entry}', file=sys.stderr)
        sys.exit(1)


def discover_assessments(api_client: OstrichApi, args: argparse.Namespace
                         ) -> Tuple[List[Tuple[str, BusinessUnit, Assessment]], List[str]]:
    print('Retrieving business units...')
    business_units = flatten_business_units(api_client.get_business_units())
    if args.businessUnitFilter:
        business_units = [(path, unit) for path, unit in business_units
                          if args.businessUnitFilter.fullmatch(unit.get('name', ''))]
        print(f'  {len(business_units)} business unit(s) matched {args.businessUnitFilter.pattern}')

    print('Retrieving assessments...')
    matched: List[Tuple[str, BusinessUnit, Assessment]] = []
    denied: List[str] = []
    for unit_path, business_unit in business_units:
        listed = api_client.get_assessments(business_unit['businessUnitId'])
        if listed is None:
            denied.append(unit_path)
            continue
        for assessment in leaf_assessments(listed):
            if args.assessmentFilter and not args.assessmentFilter.fullmatch(assessment['assessmentName']):
                continue
            matched.append((unit_path, business_unit, assessment))
    return matched, denied


def apply_targets(api_client: OstrichApi, args: argparse.Namespace) -> None:
    rows = read_rows(args.apply)
    batches, labels, problems, dropped = build_batches(rows)

    for problem in problems:
        print(f'{args.apply} {problem}', file=sys.stderr)
    for key in sorted(dropped):
        print(f'{labels.get(key, key[1])} skipped entirely, it has at least one bad row',
              file=sys.stderr)

    if not batches:
        print('Nothing to save. Every row was blank or rejected.')
        sys.exit(1 if problems else 0)

    strategies: Dict[str, Optional[str]] = {}
    saved_targets = 0
    saved_assessments = 0
    failures: List[str] = []
    unconfirmed: List[str] = []

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
        known = set(aspects)
        unknown = [target['aspectId'] for target in targets if target['aspectId'] not in known]
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
        if contributors and strategy != OVERRIDE_STRATEGY:
            if args.dryRun:
                listed = ', '.join(f"{c['name']} ({c['aspectCount']} aspect(s))" for c in contributors)
                print(f'  targets already exist here, set by: {listed}')
                print('  this business unit averages targets, so a real run would ask before saving')
            elif not args.yes and not confirm_shared_targets(contributors):
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
        absent = read_back(api_client, business_unit_id, assessment_id, targets)
        if absent:
            print(f'  saved, but {len(absent)} value(s) are not on the assessment: {", ".join(absent[:5])}',
                  file=sys.stderr)
            unconfirmed.append(f'{label} - {", ".join(absent[:5])}')
        else:
            print('  saved, and every value read back')

    report(args, saved_assessments, saved_targets, problems, dropped, failures, unconfirmed)


def read_rows(path: str) -> List[dict]:
    # utf-8-sig so a CSV saved out of Excel does not carry a byte order mark into the first column name.
    try:
        with open(path, mode='r', newline='', encoding='utf-8-sig') as csv_file:
            reader = csv.DictReader(csv_file)
            headers = reader.fieldnames or []
            missing = [column for column in REQUIRED_COLUMNS if column not in headers]
            if missing:
                raise SetupError(f'{path} is missing required column(s): {", ".join(missing)}')
            if not any(column in headers for column in EDITABLE_COLUMNS):
                raise SetupError(f'{path} has no {" or ".join(EDITABLE_COLUMNS)} column, so there is '
                                 f'nothing to save.')
            return list(reader)
    except FileNotFoundError:
        raise SetupError(f'{path} does not exist.')
    except UnicodeDecodeError:
        raise SetupError(f'{path} is not UTF-8. In Excel, use File, Save As, "CSV UTF-8 (comma '
                         f'delimited)" and try again.')


def build_batches(rows: List[dict]) -> Tuple[Dict[BatchKey, List[TargetRequest]],
                                             Dict[BatchKey, str], List[str], Set[BatchKey]]:
    batches: Dict[BatchKey, List[TargetRequest]] = {}
    labels: Dict[BatchKey, str] = {}
    problems: List[str] = []
    dropped: Set[BatchKey] = set()
    seen: Set[Tuple[BatchKey, str]] = set()

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

        key: BatchKey = (business_unit_id, assessment_id)
        labels.setdefault(key, describe_assessment(row, key))

        if not raw_target and not raw_weight:
            continue

        target: TargetRequest = {'aspectId': aspect_id}
        if raw_target:
            try:
                target['target'] = int(raw_target)
            except ValueError:
                problems.append(f'line {line}: target "{raw_target}" is not a whole number')
                dropped.add(key)
                continue
        if raw_weight:
            if raw_weight not in WEIGHTS:
                problems.append(f'line {line}: weight "{raw_weight}" is not one of {", ".join(WEIGHTS)}')
                dropped.add(key)
                continue
            target['weight'] = raw_weight

        if (key, aspect_id) in seen:
            problems.append(f'line {line}: {aspect_id} appears more than once for this assessment')
            dropped.add(key)
            continue
        seen.add((key, aspect_id))

        batches.setdefault(key, []).append(target)

    # The API saves a request as a unit, so a batch holding a rejected row must not go at all.
    # Sending the rest would write a subset the operator never asked for.
    for key in dropped:
        batches.pop(key, None)

    return batches, labels, problems, dropped


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
    try:
        return input('  continue? [y/N] ').strip().lower() in ('y', 'yes')
    except EOFError:
        # isatty() at startup is not reliable on every platform (a redirected stdin can still
        # report as a terminal), so this is the backstop: stop the whole run rather than treat
        # an unanswerable prompt as "no" and report success on an assessment that was skipped.
        raise SetupError('No terminal available to confirm writes to assessments that already '
                         'have targets. Re-run with --yes to accept them all, or --dryRun to '
                         'check the file.') from None


def read_back(api_client: OstrichApi, business_unit_id: str, assessment_id: str,
              targets: List[TargetRequest]) -> List[str]:
    """Which requested values are not on the assessment afterwards. Under the aggregate strategy the
    API does not say which contributor a value belongs to, so this confirms the value is present, not
    that it is attributed to the account that ran the script."""
    try:
        scores = api_client.get_scores(business_unit_id, assessment_id)
    except ApiError as error:
        return [f'could not re-read the assessment - {error.message}']

    return [target['aspectId'] for target in targets
            if not any(sub_holds(sub, target) for sub in aspect_subs(scores, target['aspectId']))]


def report(args: argparse.Namespace, saved_assessments: int, saved_targets: int,
           problems: List[str], dropped: Set[BatchKey], failures: List[str],
           unconfirmed: List[str]) -> None:
    print('')
    if args.dryRun:
        print('Dry run, nothing was saved.')
    else:
        print(f'Saved {saved_targets} target(s) across {saved_assessments} assessment(s).')

    if problems:
        print(f'{len(problems)} row(s) in {args.apply} were rejected before sending.')
    if dropped:
        print(f'{len(dropped)} assessment(s) were skipped entirely because of those rows.')
    if failures:
        print(f'{len(failures)} assessment(s) failed:')
        for failure in failures:
            print(f'  {failure}')
    if unconfirmed:
        print(f'{len(unconfirmed)} assessment(s) saved values that are not on the assessment:')
        for entry in unconfirmed:
            print(f'  {entry}')

    if problems or failures or unconfirmed:
        sys.exit(1)


if __name__ == '__main__':
    main()
