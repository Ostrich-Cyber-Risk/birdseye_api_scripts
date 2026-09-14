import sys
import time
from typing import TypedDict, NotRequired, List, Any, Final, Dict

import requests


class BusinessUnit(TypedDict):
    name: str
    businessUnitId: str
    businessUnits: NotRequired[List['BusinessUnit']]


class Assessment(TypedDict):
    businessUnitId: str
    assessmentId: str
    assessmentName: str
    assessmentTypeId: str


def _handle_response(response: requests.Response) -> Any:
    if response.status_code != 200:
        print(response.status_code, response.text, file=sys.stderr)
        response.raise_for_status()
    return response.json()['response']


class OstrichApi:
    def __init__(self, api_key: str, base_url: str = 'https://api.ostrichcyber-risk.com'):
        self._base_url: Final[str] = base_url
        self._api_key: str = api_key
        self._token = self.__get_token_from_key(api_key)
        # Tokens are valid for one hour; refresh a little before that.
        self._token_deadline: float = time.time() + 55 * 60

    def __get_token_from_key(self, api_key: str) -> str:
        url = f'{self._base_url}/v1/auth/token'
        response = requests.post(url, json={'apiKey': api_key})
        return _handle_response(response)['token']

    def __headers(self) -> Dict[str, str]:
        if time.time() >= self._token_deadline:
            self._token = self.__get_token_from_key(self._api_key)
            self._token_deadline = time.time() + 55 * 60
        return {'Authorization': f'Bearer {self._token}'}

    def __call(self, method, url: str, **kwargs) -> requests.Response:
        response = method(url, headers=self.__headers(), **kwargs)
        if response.status_code == 401:
            print('unauthorized - regenerating token and retrying')
            self._token = self.__get_token_from_key(self._api_key)
            self._token_deadline = time.time() + 55 * 60
            response = method(url, headers=self.__headers(), **kwargs)
        return response

    def get_business_units(self) -> List[BusinessUnit]:
        response = self.__call(requests.get, f'{self._base_url}/v1/businessUnits/')
        return _handle_response(response)['businessUnits']

    def get_assessments(self, business_unit_id: str) -> List[Assessment]:
        response = self.__call(requests.get, f'{self._base_url}/v1/businessUnits/{business_unit_id}/assessments')
        if response.status_code == 403:
            return []
        return _handle_response(response)['assessments']

    def create_assessment(self, business_unit_id: str, name: str, assessment_type_id: str,
                          start_date: str, due_date: str) -> None:
        url = f'{self._base_url}/v1/businessUnits/{business_unit_id}/assessments'
        body = {'assessment': {
            'assessmentName': name,
            'assessmentTypeId': assessment_type_id,
            'startDate': start_date,
            'dueDate': due_date,
            'notificationsOn': False,
        }}
        _handle_response(self.__call(requests.post, url, json=body))

    def get_assessment_content(self, business_unit_id: str, assessment_id: str) -> dict:
        url = f'{self._base_url}/v1/businessUnits/{business_unit_id}/assessments/{assessment_id}/content'
        return _handle_response(self.__call(requests.get, url))

    def save_scores(self, business_unit_id: str, assessment_id: str, scores: List[dict]) -> None:
        url = f'{self._base_url}/v1/businessUnits/{business_unit_id}/assessments/{assessment_id}/scores'
        _handle_response(self.__call(requests.put, url, json={'scores': scores}))

    def save_notes(self, business_unit_id: str, assessment_id: str, notes: List[dict]) -> None:
        url = f'{self._base_url}/v1/businessUnits/{business_unit_id}/assessments/{assessment_id}/notes'
        _handle_response(self.__call(requests.put, url, json={'notes': notes}))

    def save_ignored_questions(self, business_unit_id: str, assessment_type_id: str,
                               ignored_questions: List[dict]) -> None:
        url = f'{self._base_url}/v1/businessUnits/{business_unit_id}/ignoredQuestions/{assessment_type_id}'
        _handle_response(self.__call(requests.put, url, json={'ignoredQuestions': ignored_questions}))
