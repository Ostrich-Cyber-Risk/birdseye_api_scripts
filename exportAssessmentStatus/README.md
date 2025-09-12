# Export Assessment Status Script
A python script that uses the Birdseye Api to export the status for all assessments available under the provided Api Key. 

## Setup
1. Install python 3.12 or higher
2. Install the required packages using `pip install -r requirements.txt`

## Run
- To export the summarized scores and status of all assessments run `python exportAssessmentStatus.py`
- To export the full score data for all assessments and practitioners run `python exportAssessmentScores.py`
- Exporting scores also supports optional regex filters. <br>
This would retrieve only score items with an itemId containing "PROCESS" and assessments with a name containing "NIST CSF"
`python exportAssessmentScores.py --itemFilter .*PROCESS.* --assessmentFilter ".*NIST CSF.*"` <br>
  Another example of an itemFilter would be `.*\..*(-.*){2}` which would match on aspect ids like `GV.OV-2-PROCESS` or `ID.AM-7-COVERAGE` but not on ids like`GV` or `ID.AM-7`
