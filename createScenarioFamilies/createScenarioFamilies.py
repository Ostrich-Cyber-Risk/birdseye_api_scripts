import csv
import sys
from typing import List
from ostrichApi import OstrichApi, ScenarioFamilyRequestInfo

def main():
    major_version = sys.version_info.major
    minor_version = sys.version_info.minor
    if major_version != 3 or minor_version < 12:
        raise Exception(f"Running in Python {major_version}.{minor_version} ... Minimum required Python version is 3.12")

    api_key: str = input('Enter your Api Key:\n').strip()
    api_client = OstrichApi(api_key=api_key)

    scenario_families: List[ScenarioFamilyRequestInfo] = []

    with open("create scenario family example.csv", mode='r') as csv_file:
        csv_reader = csv.DictReader(csv_file)
        for row in csv_reader:
            scenario_families.append({
                'businessUnitId': row['businessUnitId'],
                'name': row['name'],
                'description': row['description']
            })

    for family in scenario_families:
        api_client.create_scenario_family_api_call(family.get('name'), family.get('description'), family.get('businessUnitId'))


if __name__ == '__main__':
    main()
