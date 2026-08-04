import sys
from typing import Any, Dict, Final, List, NotRequired, Optional, Tuple, TypedDict

import requests

PROD_BASE_URL: Final[str] = 'https://api.ostrichcyber-risk.com'
SUMMARY_ITEM_ID: Final[str] = 'summary'
WEIGHTS: Final[Tuple[str, ...]] = ('LOW', 'MED-LOW', 'MEDIUM', 'MED-HIGH', 'HIGH')
OVERRIDE_STRATEGY: Final[str] = 'override'


class BusinessUnit(TypedDict):
    businessUnitId: str
    name: str
    businessUnits: NotRequired[List['BusinessUnit']]
    parent: NotRequired['BusinessUnit']


class Assessment(TypedDict):
    businessUnitId: str
    businessUnitName: str
    assessmentId: str
    assessmentName: str
    assessmentTypeId: str
    assessments: NotRequired[List['Assessment']]


class TargetRequest(TypedDict):
    aspectId: str
    target: NotRequired[int]
    weight: NotRequired[str]


class Contributor(TypedDict):
    subId: str
    name: str
    aspectCount: int


class ApiError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f'HTTP {status_code} - {message}')
        self.status_code = status_code
        self.message = message


def _error_message(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()
    if isinstance(body, dict) and 'message' in body:
        return str(body['message'])
    return str(body)


class OstrichApi:
    def __init__(self, api_key: str, base_url: str = PROD_BASE_URL) -> None:
        self._base_url: Final[str] = base_url.rstrip('/')
        self._api_key: str = api_key
        self._token: str = self._mint_token()

    def _mint_token(self) -> str:
        response = requests.post(f'{self._base_url}/v1/auth/token', json={'apiKey': self._api_key})
        if response.status_code != 200:
            raise ApiError(response.status_code, _error_message(response))
        return response.json()['response']['token']

    def _request(self, method: str, path: str, body: Optional[dict] = None,
                 tolerate: Tuple[int, ...] = ()) -> Any:
        url = f'{self._base_url}{path}'
        response = requests.request(method, url, json=body,
                                    headers={'Authorization': f'Bearer {self._token}'})
        if response.status_code == 401:
            print('  token rejected, requesting a new one', file=sys.stderr)
            self._token = self._mint_token()
            response = requests.request(method, url, json=body,
                                        headers={'Authorization': f'Bearer {self._token}'})
        if response.status_code in tolerate:
            return None
        if response.status_code != 200:
            raise ApiError(response.status_code, _error_message(response))
        return response.json()['response']

    def get_business_units(self) -> List[BusinessUnit]:
        return self._request('GET', '/v1/businessUnits/')['businessUnits']

    def get_business_unit(self, business_unit_id: str) -> dict:
        return self._request('GET', f'/v1/businessUnits/{business_unit_id}')

    def get_assessments(self, business_unit_id: str) -> List[Assessment]:
        # A key sees the whole business unit tree, so a 403 means the key was not granted
        # anything on this one rather than that something went wrong.
        payload = self._request('GET', f'/v1/businessUnits/{business_unit_id}/assessments',
                                tolerate=(403,))
        return [] if payload is None else payload['assessments']

    def get_assessment_content(self, business_unit_id: str, assessment_id: str) -> dict:
        path = f'/v1/businessUnits/{business_unit_id}/assessments/{assessment_id}/content'
        return self._request('GET', path)['content']

    def get_scores(self, business_unit_id: str, assessment_id: str) -> dict:
        path = f'/v1/businessUnits/{business_unit_id}/assessments/{assessment_id}/scores'
        return self._request('GET', path)

    def save_targets(self, business_unit_id: str, assessment_id: str,
                     targets: List[TargetRequest]) -> None:
        path = f'/v1/businessUnits/{business_unit_id}/assessments/{assessment_id}/targets'
        self._request('PUT', path, {'targets': targets})


def flatten_business_units(root_units: List[BusinessUnit]) -> List[BusinessUnit]:
    flattened: List[BusinessUnit] = []
    for unit in root_units:
        flattened.append(unit)
        for child in unit.get('businessUnits', []):
            child['parent'] = unit
            flattened.extend(flatten_business_units([child]))
    return flattened


def business_unit_path(unit: BusinessUnit) -> str:
    names = [unit.get('name', 'Unknown')]
    current = unit
    while current.get('parent') is not None:
        current = current['parent']
        names.append(current.get('name', 'Unknown'))
    return ' > '.join(reversed(names))


def leaf_assessments(assessments: List[Assessment]) -> List[Assessment]:
    """Only leaf assessments accept targets. A rollup assessment derives its targets from its
    sub-assessments, and those sub-assessments are listed again under their own business units."""
    return [assessment for assessment in assessments if not assessment.get('assessments')]


def aspect_ids(content: dict, scores: dict) -> List[str]:
    """The scores payload holds one entry per function, category, question and aspect. The content
    payload's "nodes" keys are exactly the functions, categories and questions, so removing them
    and the summary row leaves the aspect ids, which are the only ids a target can be saved against.
    Deriving the list this way rather than pattern-matching the ids keeps it correct for custom
    content, where aspect ids do not follow the shape used by the built-in frameworks."""
    node_ids = set(content.get('nodes', {}))
    return [item['itemId'] for item in scores.get('scores', [])
            if item['itemId'] not in node_ids and item['itemId'] != SUMMARY_ITEM_ID]


def aspect_subs(scores: dict, aspect_id: str) -> List[dict]:
    for item in scores.get('scores', []):
        if item['itemId'] == aspect_id:
            return item.get('subs', [])
    return []


def target_contributors(scores: dict, aspects: List[str]) -> List[Contributor]:
    names = {label['subId']: label.get('name') or label['subId']
             for label in scores.get('targetLabels', [])}
    aspect_set = set(aspects)
    counts: Dict[str, int] = {}
    for item in scores.get('scores', []):
        if item['itemId'] not in aspect_set:
            continue
        for sub in item.get('subs', []):
            if sub.get('target') is not None:
                counts[sub['subId']] = counts.get(sub['subId'], 0) + 1
    return [{'subId': sub_id, 'name': names.get(sub_id, sub_id), 'aspectCount': count}
            for sub_id, count in sorted(counts.items(), key=lambda entry: (-entry[1], entry[0]))]


def current_targets(scores: dict, aspects: List[str]) -> Dict[str, Tuple[Any, Any]]:
    aspect_set = set(aspects)
    return {item['itemId']: (item.get('target'), item.get('weightLabel'))
            for item in scores.get('scores', []) if item['itemId'] in aspect_set}
