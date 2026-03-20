import sys
from functools import cache
from typing import TypedDict, Any, Final

import requests


class ScenarioFamilyRequestInfo(TypedDict):
    businessUnitId: str
    name: str
    description: str


def _handle_response(response: requests.Response) -> Any:
    if response.status_code != 200:
        print(response.status_code, response.json(), file=sys.stderr)
        response.raise_for_status()
    return response.json()['response']


class OstrichApi:
    def __init__(self, api_key: str, base_url: str = 'https://api.ostrichcyber-risk.com'):
        self._base_url: Final[str] = base_url
        self._api_key: str = api_key
        self._token = self.__get_token_from_key(api_key)

    def __get_token_from_key(self, api_key: str) -> str:
        url = f'{self._base_url}/v1/auth/token'
        response = requests.post(url, json={'apiKey': api_key})
        return _handle_response(response)['token']


    @cache
    def create_scenario_family_api_call(self, name: str, description: str, bu_id: str):
        url = f'{self._base_url}/v1/businessUnits/{bu_id}/scenarioFamilies'
        response = requests.post(url, headers={'Authorization': f'Bearer {self._token}'}, json={'scenarioFamily': {'name': name, 'description': description}})
        if response.status_code == 401:
            print("unauthorized - regenerating token and retrying")
            self._token = self.__get_token_from_key(self._api_key)
            response = requests.post(url, headers={'Authorization': f'Bearer {self._token}'}, json={'scenarioFamily': {'name': name, 'description': description}})
        if response.status_code != 200:
            print('Failed to create family: ', response.status_code, response.json(), file=sys.stderr)
