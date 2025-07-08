import csv
import sys
from typing import Dict, List, Optional
from exportAssessmentScores import flatten_business_units, get_all_assessments
from ostrichApi import OstrichApi, Assessment, AssessmentScores, BusinessUnit, Score, SubInfo


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
                f'Hierarchy: {hierarchy}, ParentBusinessUnit: {business_unit.get('parent', dict()).get('name', 'N/A')}, BusinessUnit: {assessment['businessUnitName']}, Assessment: {assessment['assessmentName']}, PercentDone: {summary.get('percentDone', 'N/A')}%, QuestionCount: {summary['questionCount']}')
            for sub in summary.get('subs', set()):
                sub_info: SubInfo = api_client.get_sub_info(sub['subId'])
                print(
                    f'\tSub: {sub_info['displayName']}, Email: {sub_info['email']}, PercentDone: {sub.get('percentDone', 'N/A')}%, Answered: {sub.get('answerCount', 'N/A')}/{sub['questionCount']}')
                csv_rows.append({
                    'Hierarchy': hierarchy,
                    'ParentBusinessUnit': business_unit.get('parent', dict()).get('name', 'N/A'),
                    'BusinessUnit': assessment['businessUnitName'],
                    'Assessment': assessment['assessmentName'],
                    'Sub': sub_info['displayName'],
                    'Email': sub_info['email'],
                    'PercentDone': sub.get('percentDone', '(N/A)'),
                    'Answered': f'{sub.get('answerCount', '(N/A)')}/{sub['questionCount']}'})
        except Exception as e:
            print(f'Error handling assessment {assessment.get('assessmentName', 'Unknown Assessment')}: {e}', file=sys.stderr)

    print('End Report. Saving to OstrichAssessmentReport.csv')
    with open('OstrichAssessmentReport.csv', 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=csv_rows[0].keys())
        writer.writeheader()
        writer.writerows(csv_rows)


def extract_summary(assessment_scores: AssessmentScores) -> Optional[Score]:
    summary: Optional[Score] = None
    for score in assessment_scores.get('scores', set()):
        if score['itemId'] == 'summary':
            summary = score
            break
    else:
        print(f'summary wasn\'t found in assessment_scores: {assessment_scores}', file=sys.stderr)

    return summary


def flatten_business_unit(root_business_unit: BusinessUnit) -> List[BusinessUnit]:
    business_units: List[BusinessUnit] = [root_business_unit]
    children_business_units: List[BusinessUnit] = root_business_unit.get('businessUnits', list())
    for child_business_unit in children_business_units:
        child_business_unit['parent'] = root_business_unit
        business_units.extend(flatten_business_unit(child_business_unit))

    return business_units


if __name__ == '__main__':
    main()
