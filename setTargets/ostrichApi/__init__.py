import sys
from typing import Any, Dict, Final, List, NotRequired, Optional, Tuple, TypedDict
from urllib.parse import urlparse

import requests

PROD_BASE_URL: Final[str] = 'https://api.ostrichcyber-risk.com'
SUMMARY_ITEM_ID: Final[str] = 'summary'
WEIGHTS: Final[Tuple[str, ...]] = ('LOW', 'MED-LOW', 'MEDIUM', 'MED-HIGH', 'HIGH')
OVERRIDE_STRATEGY: Final[str] = 'override'
REQUEST_TIMEOUT: Final[int] = 180
LOCAL_HOSTS: Final[Tuple[str, ...]] = ('localhost', '127.0.0.1')


class BusinessUnit(TypedDict):
    businessUnitId: str
    name: str
    businessUnits: NotRequired[List['BusinessUnit']]


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


def _require_secure_url(base_url: str) -> str:
    # The API key and the bearer token derived from it both cross this connection.
    trimmed = base_url.rstrip('/')
    parsed = urlparse(trimmed)
    if parsed.scheme != 'https' and parsed.hostname not in LOCAL_HOSTS:
        raise ValueError(f'{trimmed} is not https, so the API key would be sent in the clear.')
    return trimmed


class OstrichApi:
    def __init__(self, api_key: str, base_url: str = PROD_BASE_URL) -> None:
        self._base_url: Final[str] = _require_secure_url(base_url)
        self._api_key: str = api_key
        self._token: str = self._mint_token()

    def _mint_token(self) -> str:
        response = requests.post(f'{self._base_url}/v1/auth/token', json={'apiKey': self._api_key},
                                 timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            raise ApiError(response.status_code, _error_message(response))
        return response.json()['response']['token']

    def _request(self, method: str, path: str, body: Optional[dict] = None,
                 tolerate: Tuple[int, ...] = (), has_response_body: bool = True) -> Any:
        url = f'{self._base_url}{path}'
        response = requests.request(method, url, json=body, timeout=REQUEST_TIMEOUT,
                                    headers={'Authorization': f'Bearer {self._token}'})
        if response.status_code == 401:
            print('  token rejected, requesting a new one', file=sys.stderr)
            self._token = self._mint_token()
            response = requests.request(method, url, json=body, timeout=REQUEST_TIMEOUT,
                                        headers={'Authorization': f'Bearer {self._token}'})
        if response.status_code in tolerate:
            return None
        if response.status_code != 200:
            raise ApiError(response.status_code, _error_message(response))
        # Save-targets only ever returns {"message": ...}, no "response" envelope. Every read
        # endpoint returns one, so this is opt-out rather than opt-in.
        return response.json()['response'] if has_response_body else None

    def get_business_units(self) -> List[BusinessUnit]:
        return self._request('GET', '/v1/businessUnits/')['businessUnits']

    def get_business_unit(self, business_unit_id: str) -> dict:
        return self._request('GET', f'/v1/businessUnits/{business_unit_id}')

    def get_assessments(self, business_unit_id: str) -> Optional[List[Assessment]]:
        """None means the key holds no roles on this business unit. A key can see the whole tree but
        is granted roles on part of it, so that is an expected answer rather than a failure."""
        payload = self._request('GET', f'/v1/businessUnits/{business_unit_id}/assessments',
                                tolerate=(403,))
        return None if payload is None else payload['assessments']

    def get_assessment_content(self, business_unit_id: str, assessment_id: str) -> dict:
        path = f'/v1/businessUnits/{business_unit_id}/assessments/{assessment_id}/content'
        return self._request('GET', path)['content']

    def get_scores(self, business_unit_id: str, assessment_id: str) -> dict:
        path = f'/v1/businessUnits/{business_unit_id}/assessments/{assessment_id}/scores'
        return self._request('GET', path)

    def save_targets(self, business_unit_id: str, assessment_id: str,
                     targets: List[TargetRequest]) -> None:
        path = f'/v1/businessUnits/{business_unit_id}/assessments/{assessment_id}/targets'
        self._request('PUT', path, {'targets': targets}, has_response_body=False)


def flatten_business_units(root_units: List[BusinessUnit],
                           parent_path: str = '') -> List[Tuple[str, BusinessUnit]]:
    """Each unit paired with its full path through the hierarchy, for display. The path is built on
    the way down rather than stored on the units, so the payload from the API is left alone."""
    flattened: List[Tuple[str, BusinessUnit]] = []
    for unit in root_units:
        name = unit.get('name', 'Unknown')
        path = f'{parent_path} > {name}' if parent_path else name
        flattened.append((path, unit))
        flattened.extend(flatten_business_units(unit.get('businessUnits', []), path))
    return flattened


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


def sub_holds(sub: dict, target: TargetRequest) -> bool:
    """Whether a single contributor holds everything the request asked for. Target and weight have to
    come from the same contributor, otherwise one manager's target paired with another's weight would
    read back as a match."""
    if 'target' in target:
        saved = sub.get('target')
        if saved is None or float(saved) != float(target['target']):
            return False
    if 'weight' in target and sub.get('weightLabel') != target['weight']:
        return False
    return True


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
