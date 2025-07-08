import csv
from ostrichApi import OstrichApi, Assessment, AssessmentScores, BusinessUnit, Score, SubInfo
import sys
from typing import List, Optional, Dict


def main():
    major_version = sys.version_info.major
    minor_version = sys.version_info.minor
    if major_version < 3 or minor_version < 12:
        raise Exception(f"Running in Python {major_version}.{minor_version} ... Minimum required Python version is 3.12")

    api_key: str = input('Enter your Api Key:\n').strip()
    api_client = OstrichApi(api_key=api_key)

    print('Retrieving Business Units...')
    business_units: List[BusinessUnit] = api_client.get_business_units()
    flat_business_units: List[BusinessUnit] = flatten_business_units(business_units)
    mapped_business_units: Dict[str, BusinessUnit] = {bu['businessUnitId']: bu for bu in flat_business_units}

    print('Retrieving Assessments...')
    flat_assessments: List[Assessment] = get_all_assessments(api_client, flat_business_units)

    print('Retrieving Scores and beginning report...')
    csv_rows: List[dict] = []
    for assessment in flat_assessments:
        try:
            assessment_scores: AssessmentScores = api_client.get_assessment_scores(assessment['businessUnitId'], assessment['assessmentId'])
        except Exception as e:
            print(f'Failed to get scores for {assessment['assessmentName']}: {e}', file=sys.stderr)
            continue

        summary: Optional[Score] = extract_summary(assessment_scores)
        if summary is None:
            print(f'Summary Not Available for Assessment - BusinessUnit: {assessment['businessUnitName']} Assessment: {assessment['assessmentName']}', file=sys.stderr)
            continue

        try:
            business_unit = mapped_business_units[assessment['businessUnitId']]
            hierarchy = business_unit.get('name', 'N/A')
            current_business_unit = business_unit
            while current_business_unit.get('parent') is not None:
                current_business_unit = current_business_unit.get('parent')
                hierarchy = f'{current_business_unit.get('name', 'N/A')} > {hierarchy}'

            print(
                f'Hierarchy: {hierarchy}, ParentBusinessUnit: {business_unit.get('parent', dict()).get('name', 'N/A')}, BusinessUnit: {assessment['businessUnitName']}, Assessment: {assessment['assessmentName']}, PercentDone: {summary.get('percentDone', 'N/A')}%, QuestionCount: {summary.get('questionCount', 'N/A')}')
            for score in assessment_scores.get('scores', set()):
                csv_rows.append({
                    'Hierarchy': hierarchy,
                    'ParentBusinessUnit': business_unit.get('parent', dict()).get('name', 'N/A'),
                    'BusinessUnit': assessment['businessUnitName'],
                    'Assessment': assessment['assessmentName'],
                    'ItemId': score.get('itemId', 'N/A'),
                    'Sub': '',
                    'Email': '',
                    'Score': score.get('score', '(N/A)'),
                    'LastModifiedAt': 'N/A',
                    'PercentDone': score.get('percentDone', '(N/A)'),
                    'Answered': f'{score.get('answerCount', '(N/A)')}/{score.get('questionCount', '(N/A)')}'})
                for sub in score.get('subs', set()):
                    sub_info: SubInfo = api_client.get_sub_info(sub['subId'])
                    csv_rows.append({
                        'Hierarchy': hierarchy,
                        'ParentBusinessUnit': business_unit.get('parent', dict()).get('name', 'N/A'),
                        'BusinessUnit': assessment['businessUnitName'],
                        'Assessment': assessment['assessmentName'],
                        'ItemId': score.get('itemId', 'N/A'),
                        'Sub': sub_info['displayName'],
                        'Email': sub_info['email'],
                        'Score': sub.get('score', '(N/A)'),
                        'LastModifiedAt': sub.get('lastModifiedAt', '(N/A)'),
                        'PercentDone': sub.get('percentDone', '(N/A)'),
                        'Answered': f'{sub.get('answerCount', '(N/A)')}/{sub.get('questionCount', '(N/A)')}'})

        except Exception as e:
            print(f'Error handling assessment {assessment.get('assessmentName', 'Unknown Assessment')}: {e}', file=sys.stderr)

    print('End Report. Saving to OstrichAssessmentReport.csv')
    with open('OstrichAssessmentReport.csv', 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=csv_rows[0].keys())
        writer.writeheader()
        writer.writerows(csv_rows)


def flatten_business_units(root_business_units: List[BusinessUnit]) -> List[BusinessUnit]:
    business_units: List[BusinessUnit] = root_business_units.copy()
    if len(business_units) == 0:
        return []

    children_business_units: List[BusinessUnit] = []
    for business_unit in business_units:
        children_units = business_unit.get('businessUnits', list())
        for child_unit in children_units:
            child_unit['parent'] = business_unit
            children_business_units.append(child_unit)

    business_units.extend(flatten_business_units(children_business_units))
    return business_units


def get_all_assessments(api_client: OstrichApi, business_units: List[BusinessUnit]) -> List[Assessment]:
    assessments: List[Assessment] = []
    for business_unit in business_units:
        print(f"Getting Assessments for {business_unit.get('name', 'Unknown Business Unit')}")
        bu_assessments = api_client.get_assessments(business_unit['businessUnitId'])
        print(f'\tFound {len(bu_assessments)} Assessment(s)')
        assessments.extend(bu_assessments)
    return assessments


def extract_summary(assessment_scores: AssessmentScores) -> Optional[Score]:
    summary: Optional[Score] = None
    for score in assessment_scores.get('scores', set()):
        if score['itemId'] == 'summary':
            summary = score
            break
    else:
        print(f'summary wasn\'t found in assessment_scores: {assessment_scores}', file=sys.stderr)

    return summary


if __name__ == '__main__':
    main()
