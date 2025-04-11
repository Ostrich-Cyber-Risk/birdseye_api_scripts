import csv
import requests
import sys
from typing import Final, TypedDict, List, NotRequired, Any, Optional, Dict
from functools import cache

base_url: Final[str] = 'https://api.ostrichcyber-risk.com'


class BusinessUnit(TypedDict):
    name: str
    businessUnitId: str
    businessUnits: NotRequired['BusinessUnit']
    parent: NotRequired['BusinessUnit']


class Assessment(TypedDict):
    businessUnitId: str
    businessUnitName: str
    assessmentId: str
    assessmentName: str
    assessmentTypeId: str
    businessUnit: 'BusinessUnit'


class AssessmentScores(TypedDict):
    businessUnitId: str
    assessmentId: str
    assessmentTypeId: str
    scoreLabels: List
    targetLabels: List
    scores: List['Score']


class User(TypedDict):
    displayName: str
    email: str


class Score(TypedDict):
    itemId: str
    aspectPercentDone: float
    aspectTotalAnswerCount: int
    aspectTotalCount: int
    percentDone: float
    questionCount: int
    subs: NotRequired[List['Sub']]


class Sub(TypedDict):
    subId: str
    answerCount: int
    percentDone: NotRequired[float]
    questionCount: int


class SubInfo(TypedDict):
    displayName: str
    subId: str
    email: str


def main():
    api_key: str = input('Enter your Api Key:\n').strip()
    token: str = get_token_from_key(api_key)

    print('Retrieving Business Units...')
    business_units: List[BusinessUnit] = get_business_units(token)
    flat_business_units: List[BusinessUnit] = []
    for business_unit in business_units:
        flat_business_units.extend(flatten_business_unit(business_unit))
    mapped_business_units: Dict[str, BusinessUnit] = {bu['businessUnitId']: bu for bu in flat_business_units}

    print('Retrieving Assessments...')
    flat_assessments: List[Assessment] = []
    for business_unit in flat_business_units:
        print(f"Getting Assessments for {business_unit.get('name', 'Unknown Business Unit')}")
        bu_assessments = get_assessments(business_unit['businessUnitId'], token)
        print(f'\tFound {len(bu_assessments)} Assessment(s)')
        flat_assessments.extend(bu_assessments)

    print('Retrieving Scores and beginning report...')
    csv_rows: List[dict] = []
    for assessment in flat_assessments:
        try:
            assessment_scores: AssessmentScores = get_assessment_scores(assessment['businessUnitId'], assessment['assessmentId'], token)
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
                sub_info: SubInfo = get_sub_info(sub['subId'], token)
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


def handle_response(response: requests.Response) -> Any:
    if response.status_code != 200:
        print(response.status_code, response.json(), file=sys.stderr)
        response.raise_for_status()
    return response.json()['response']


def get_token_from_key(api_key: str) -> str:
    response = requests.post(f'{base_url}/v1/auth/token', json={'apiKey': api_key})
    return handle_response(response)['token']


def get_business_units(token: str) -> List[BusinessUnit]:
    response = requests.get(f'{base_url}/v1/businessUnits/', headers={'Authorization': f'Bearer {token}'})
    return handle_response(response)['businessUnits']


@cache
def get_assessments(business_unit_id: str, token: str) -> List[Assessment]:
    response = requests.get(f'{base_url}/v1/businessUnits/{business_unit_id}/assessments', headers={'Authorization': f'Bearer {token}'})
    return handle_response(response)['assessments']


def get_assessment_scores(business_unit_id: str, assessment_id: str, token: str) -> AssessmentScores:
    response = requests.get(f'{base_url}/v1/businessUnits/{business_unit_id}/assessments/{assessment_id}/scores', headers={'Authorization': f'Bearer {token}'})
    return handle_response(response)


@cache
def get_user(user_id: str, token: str) -> User:
    response = requests.get(f'{base_url}/v1/users/{user_id}', headers={'Authorization': f'Bearer {token}'})
    return handle_response(response)


def extract_summary(assessment_scores: AssessmentScores) -> Optional[Score]:
    summary: Optional[Score] = None
    for score in assessment_scores.get('scores', set()):
        if score['itemId'] == 'summary':
            summary = score
            break
    else:
        print(f'summary wasn\'t found in assessment_scores: {assessment_scores}', file=sys.stderr)

    return summary


def get_sub_info(sub_id: str, token: str) -> SubInfo:
    if '::' in sub_id:
        business_unit_id, assessment_id = sub_id.split("::")
        sub: Optional[Assessment] = next((assessment for assessment in get_assessments(business_unit_id, token) if assessment['assessmentId'] == assessment_id), None)
        if sub is None:
            return {
                'subId': sub_id,
                'displayName': 'Unknown Assessment',
                'email': 'N/A'
            }
        return {
            'subId': sub_id,
            'displayName': f"{sub.get('businessUnitName', 'UnknownBusinessUnit')}::{sub.get('assessmentName', 'UnknownAssessmentName')}",
            'email': 'N/A'
        }

    user_info: User = get_user(sub_id, token)
    return {
        'subId': sub_id,
        'displayName': user_info.get('displayName', 'N/A'),
        'email': user_info.get('email', 'N/A')
    }


def flatten_business_unit(root_business_unit: BusinessUnit) -> List[BusinessUnit]:
    business_units: List[BusinessUnit] = [root_business_unit]
    children_business_units: List[BusinessUnit] = root_business_unit.get('businessUnits', list())
    for child_business_unit in children_business_units:
        child_business_unit['parent'] = root_business_unit
        business_units.extend(flatten_business_unit(child_business_unit))

    return business_units


if __name__ == '__main__':
    main()
