import sys
from functools import cache
from typing import TypedDict, NotRequired, List, Any, Final, Optional

import requests


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


class Score(TypedDict):
    itemId: str
    aspectPercentDone: NotRequired[float]
    aspectTotalAnswerCount: NotRequired[int]
    aspectTotalCount: NotRequired[int]
    answerCount: NotRequired[int]
    percentDone: NotRequired[float]
    questionCount: NotRequired[int]
    score: NotRequired['Score']
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


class User(TypedDict):
    displayName: str
    email: str


def _handle_response(response: requests.Response) -> Any:
    if response.status_code != 200:
        print(response.status_code, response.json(), file=sys.stderr)
        response.raise_for_status()
    return response.json()['response']


class OstrichApi:
    def __init__(self, api_key: str, base_url: str = 'https://api.ostrichcyber-risk.com'):
        self._base_url: Final[str] = base_url
        self._token = self.__get_token_from_key(api_key)

    def __get_token_from_key(self, api_key: str) -> str:
        response = requests.post(f'{self._base_url}/v1/auth/token', json={'apiKey': api_key})
        return _handle_response(response)['token']

    @cache
    def __make_api_call(self, url: str, method=requests.get):
        response = method(url, headers={'Authorization': f'Bearer {self._token}'})
        if response.status_code == 500:
            response.raise_for_status()
        return response

    def get_business_units(self) -> List[BusinessUnit]:
        response = self.__make_api_call(f'{self._base_url}/v1/businessUnits/')
        return _handle_response(response)['businessUnits']

    def get_assessments(self, business_unit_id: str) -> List[Assessment]:
        response = self.__make_api_call(f'{self._base_url}/v1/businessUnits/{business_unit_id}/assessments')
        return _handle_response(response)['assessments']

    def get_assessment_scores(self, business_unit_id: str, assessment_id: str) -> AssessmentScores:
        response = self.__make_api_call(f'{self._base_url}/v1/businessUnits/{business_unit_id}/assessments/{assessment_id}/scores')
        return _handle_response(response)

    def get_user(self, user_id: str) -> User:
        response = self.__make_api_call(f'{self._base_url}/v1/users/{user_id}')
        return _handle_response(response)

    def get_sub_info(self, sub_id: str) -> SubInfo:
        try:
            # If the score strategy is override all scores will show as being saved by "override-scores"
            if sub_id == 'override-scores' or sub_id == 'override-targets':
                return {
                    'subId': sub_id,
                    'displayName': sub_id,
                    'email': 'N/A'
                }
            # Subs can be business_unit_id::assessment_id if the assessment is a rollup
            # Or in a legacy format that has just business_unit_id
            # Or they are a user
            if '::' in sub_id:
                business_unit_id, assessment_id = sub_id.split("::")
                sub: Optional[Assessment] = next((assessment for assessment in self.get_assessments(business_unit_id) if assessment['assessmentId'] == assessment_id), None)
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
            elif len(sub_id) == 20:
                return {
                    'subId': sub_id,
                    'displayName': sub_id,
                    'email': 'N/A'
                }

            user_info: User = self.get_user(sub_id)
            return {
                'subId': sub_id,
                'displayName': user_info.get('displayName', 'N/A'),
                'email': user_info.get('email', 'N/A')
            }
        except Exception as e:
            print(f'Error retrieving sub/user with id {sub_id}: {e}', file=sys.stderr)
            return {
                'subId': sub_id,
                'displayName': sub_id,
                'email': 'N/A'
            }
