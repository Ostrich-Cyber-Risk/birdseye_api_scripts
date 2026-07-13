import argparse
import csv
import re
import sys
import time
from typing import Dict, List, Optional

from ostrichApi import OstrichApi, Assessment, BusinessUnit

# The CSAT export scores each safeguard 0-100 in steps of 25, which lines up
# exactly with the Birdseye "process" aspect option values. No conversion needed.
VALID_PROCESS_SCORES = {0, 25, 50, 75, 100}
SAFEGUARD_PATTERN = re.compile(r'Safeguard\s+(\d+\.\d+)\b')
DEFAULT_ASSESSMENT_TYPE_ID = 'CIS 8.1'


def main():
    major_version = sys.version_info.major
    minor_version = sys.version_info.minor
    if major_version != 3 or minor_version < 12:
        raise Exception(f"Running in Python {major_version}.{minor_version} ... Minimum required Python version is 3.12")

    parser = argparse.ArgumentParser(
        description='Upload CIS safeguard scores from a CSAT tool CSV export into a Birdseye assessment.')
    parser.add_argument('--csv', required=True,
                        help='Path to the CSAT CSV export for one business unit.')
    parser.add_argument('--businessUnitId', required=True,
                        help='Id of the (leaf) business unit to upload scores to.')
    parser.add_argument('--assessmentTypeId', default=DEFAULT_ASSESSMENT_TYPE_ID,
                        help=f'Assessment content type to target (default: "{DEFAULT_ASSESSMENT_TYPE_ID}").')
    parser.add_argument('--assessmentName', default='CIS Controls v8.1 (CSAT import)',
                        help='Name to use if a new assessment has to be created.')
    parser.add_argument('--scoreNotApplicable', action='store_true',
                        help='Also upload scores for safeguards the export marks Not Applicable. '
                             'By default those safeguards are marked ignored instead.')
    parser.add_argument('--skipNotes', action='store_true',
                        help='Do not import the "Discussion Comments" and "History" columns as notes.')
    parser.add_argument('--dryRun', action='store_true',
                        help='Report what would happen without writing anything.')
    args = parser.parse_args()

    api_key: str = input('Enter your Api Key:\n').strip()
    api_client = OstrichApi(api_key=api_key)

    rows = read_csat_csv(args.csv)
    applicable = [r for r in rows if r['applicable']]
    not_applicable = [r for r in rows if not r['applicable']]
    print(f'Read {len(rows)} safeguards from {args.csv} '
          f'({len(applicable)} applicable, {len(not_applicable)} not applicable)')

    bad = sorted(r['number'] for r in applicable if r['score'] not in VALID_PROCESS_SCORES)
    if bad:
        raise Exception(f'Applicable safeguards with scores outside {sorted(VALID_PROCESS_SCORES)}: {bad}')

    assessment = get_or_create_assessment(api_client, args.businessUnitId, args.assessmentTypeId,
                                          args.assessmentName, args.dryRun)
    if assessment is None:
        print('[dry run] No existing assessment to read content from; '
              'stopping before score preview. Create the assessment first, or run without --dryRun.')
        return
    print(f"Using assessment {assessment['assessmentId']} ({assessment['assessmentName']})")

    content = api_client.get_assessment_content(args.businessUnitId, assessment['assessmentId'])
    safeguard_to_question = build_safeguard_map(content)

    unmatched = sorted(r['number'] for r in rows if r['number'] not in safeguard_to_question)
    if unmatched:
        print(f'WARNING: {len(unmatched)} safeguards in the export were not found in the '
              f'assessment content and will be skipped: {unmatched}', file=sys.stderr)

    scores: List[dict] = []
    ignored: List[dict] = []
    notes: List[dict] = []
    for row in rows:
        question_id = safeguard_to_question.get(row['number'])
        if question_id is None:
            continue
        aspect_id = f'{question_id}-PROCESS'
        if row['applicable'] or args.scoreNotApplicable:
            scores.append({'aspectId': aspect_id, 'score': row['score']})
        else:
            ignored.append({'aspectId': aspect_id, 'ignored': True})
        if not args.skipNotes:
            note_value = build_note_value(row)
            if note_value:
                notes.append({'aspectId': aspect_id, 'value': note_value})

    print(f'Prepared {len(notes)} notes, {len(ignored)} safeguards to mark ignored, '
          f'and {len(scores)} scores to upload.')

    if args.dryRun:
        for score in scores[:5]:
            print(f"  [dry run] score {score['aspectId']} = {score['score']}")
        if len(scores) > 5:
            print(f'  [dry run] ... and {len(scores) - 5} more scores')
        if notes:
            print(f"  [dry run] note {notes[0]['aspectId']}: {notes[0]['value'][:80]!r}...")
        return

    # Save notes before marking anything ignored, so notes land while every aspect is still active.
    if notes:
        api_client.save_notes(args.businessUnitId, assessment['assessmentId'], notes)
        print(f'Saved {len(notes)} notes.')
    # Ignored questions must be saved before scores: scoring an ignored aspect is rejected.
    if ignored:
        api_client.save_ignored_questions(args.businessUnitId, args.assessmentTypeId, ignored)
        print(f'Marked {len(ignored)} safeguards ignored.')
    if scores:
        api_client.save_scores(args.businessUnitId, assessment['assessmentId'], scores)
        print(f'Uploaded {len(scores)} scores.')
    print('Done.')


def read_csat_csv(path: str) -> List[dict]:
    """Read the columns we care about from a CSAT export: safeguard number, score, applicability."""
    rows: List[dict] = []
    with open(path, mode='r', newline='', encoding='utf-8-sig') as csv_file:
        for row in csv.DictReader(csv_file):
            number = (row.get('Number') or '').strip()
            average = (row.get('Average') or '').strip()
            if not number or not average:
                continue
            rows.append({
                'number': number,
                'score': int(float(average)),
                'applicable': (row.get('Applicable') or '').strip().lower() == 'yes',
                'discussion': (row.get('Discussion Comments') or '').strip(),
                'history': (row.get('History') or '').strip(),
            })
    return rows


def build_note_value(row: dict) -> str:
    """Combine the free-text CSAT columns into a single note body for a safeguard."""
    sections = []
    if row.get('discussion'):
        sections.append(f"Discussion Comments:\n{row['discussion']}")
    if row.get('history'):
        sections.append(f"History:\n{row['history']}")
    return '\n\n'.join(sections)


def build_safeguard_map(content: dict) -> Dict[str, str]:
    """Map a CIS safeguard number (e.g. "1.1") to its Birdseye question id.

    The safeguard number cannot be derived from the question id (question ids are
    ordered by NIST CSF function), so it is parsed from each question's text.
    """
    nodes = content.get('nodes') or {}
    mapping: Dict[str, str] = {}
    for question_id, node in nodes.items():
        if not isinstance(node, dict) or 'process' not in node:
            continue
        match = SAFEGUARD_PATTERN.search(str(node.get('text', '')))
        if match:
            mapping[match.group(1)] = question_id
    return mapping


def get_or_create_assessment(api_client: OstrichApi, business_unit_id: str, assessment_type_id: str,
                             assessment_name: str, dry_run: bool) -> Optional[Assessment]:
    """Reuse the most recent assessment of the target type, otherwise create one."""
    existing = [a for a in api_client.get_assessments(business_unit_id)
                if a.get('assessmentTypeId') == assessment_type_id]
    if existing:
        return sorted(existing, key=lambda a: a.get('startDate', ''), reverse=True)[0]
    if dry_run:
        print(f'[dry run] Would create a "{assessment_type_id}" assessment named "{assessment_name}".')
        return None
    now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    api_client.create_assessment(business_unit_id, assessment_name, assessment_type_id, now, now)
    # Create does not return the new id, so re-list to find it.
    created = [a for a in api_client.get_assessments(business_unit_id)
               if a.get('assessmentTypeId') == assessment_type_id]
    if not created:
        raise Exception('Assessment was created but could not be found when re-listing.')
    return sorted(created, key=lambda a: a.get('startDate', ''), reverse=True)[0]


def flatten_business_units(root_business_units: List[BusinessUnit]) -> List[BusinessUnit]:
    business_units: List[BusinessUnit] = root_business_units.copy()
    for business_unit in root_business_units:
        business_units.extend(flatten_business_units(business_unit.get('businessUnits', [])))
    return business_units


if __name__ == '__main__':
    main()
