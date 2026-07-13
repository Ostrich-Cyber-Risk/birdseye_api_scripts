# Import CSAT Scores Script

A python script that uses the Birdseye Api to upload CIS Controls safeguard scores from a
CSAT tool CSV export into a Birdseye assessment. Run it once per business unit.

The export scores each safeguard from 0 to 100 in steps of 25, which matches the Birdseye
"process" aspect option values exactly, so scores are uploaded as-is with no conversion.

## Expected CSV

The CSAT export is read by column name. These columns are used:

| Column                | Used for                                                                    |
|-----------------------|-----------------------------------------------------------------------------|
| `Number`              | The CIS safeguard number (e.g. `1.1`), matched to the assessment.           |
| `Average`             | The safeguard score. Must be one of 0, 25, 50, 75, 100.                     |
| `Applicable`          | `Yes` / `No`. `No` safeguards are marked ignored (see below).               |
| `Discussion Comments` | Imported as a note on the safeguard (unless `--skipNotes`).                 |
| `History`             | Appended to the same note (unless `--skipNotes`).                           |

See `csat export example.csv` for the format.

## Setup

1. Install python 3.12 or higher
2. Install the required packages using `pip install -r requirements.txt`
3. Have an Api Key whose associated user has the assessment practitioner role on the target
   business unit, and make sure that business unit is subscribed to the assessment content type.

## Run

```
python importCsatScores.py --csv "path/to/export.csv" --businessUnitId <businessUnitId>
```

Preview without writing anything:

```
python importCsatScores.py --csv "path/to/export.csv" --businessUnitId <businessUnitId> --dryRun
```

If no assessment of the target type exists on the business unit, one is created.

### Options

- `--assessmentTypeId` — assessment content type to target (default `CIS 8.1`).
- `--assessmentName` — name used if a new assessment has to be created.
- `--scoreNotApplicable` — also upload scores for safeguards marked `Applicable = No`.
  By default those safeguards are marked ignored on the assessment instead of being scored.
- `--skipNotes` — do not import the `Discussion Comments` and `History` columns as notes.
- `--dryRun` — report what would happen without writing.
