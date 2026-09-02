# Import CIS Workbook Script

A python script that uses the Birdseye Api to import CIS safeguard scores from a CIS
internal-controls workbook (`.xlsx`) into a Birdseye assessment. Run it once per business unit.

It prompts through every step and explains each one, so you can see how a workbook judgement
becomes a score before anything is written. Nothing is uploaded until the final confirmation.

For the CSV export produced by the CIS CSAT tool, use `importCsatScores`.

## Setup

1. Install python 3.12 or higher
2. Install the required packages using `pip install -r requirements.txt`

## Before you start

Three things have to be true, or the run stops partway:

1. **The assessment type is available on the business unit.** A `CIS 8.1` assessment can only
   be created where that content type is subscribed, on the business unit itself or on one of
   its parents.
2. **The business unit is a leaf.** A business unit with children rolls its scores up from
   them, so there is nothing to score directly.
3. **The Api Key holds `Manager` and `PractitionerAssessments` on that business unit**, and so
   does the user the key belongs to. See [Roles](#roles) for why both.

## Run

```
python importCisWorkbook.py
```

That is the whole command, and each of the six steps explains itself before asking. To answer a
prompt up front, pass its flag:

```
python importCisWorkbook.py --workbook "cis-internal-controls.xlsx"
```

which leaves six answers to give. Every yes-or-no prompt defaults to yes, so Enter accepts and
`n` stops. The counts shown as `nn` below are read from your own workbook:

```
------------------------------------------------------------------------------
 Step 1 of 6: workbook and sheet
------------------------------------------------------------------------------

cis-internal-controls.xlsx has 9 sheets:
   1. Instructions
   2. Safeguard Catalogue
   3. CIS-Internal Controls  <- default
   ...
Which sheet holds the safeguards? [Enter for the default]        <- Enter

Read nnn safeguards from "CIS-Internal Controls".

------------------------------------------------------------------------------
 Step 2 of 6: how each status becomes a score
------------------------------------------------------------------------------
  Assessment Status becomes                      in this workbook
  Met              process score 100                          nn
  Partially Met    process score 75                            nn
  Not Met          process score 0                             nn
  Not Assessed     process score 0                             nn
  Not Applicable   left untouched, no score                    nn

Is that the conversion you want? [Y/n]                           <- Enter

------------------------------------------------------------------------------
 Step 3 of 6: coverage
------------------------------------------------------------------------------
Coverage:                                                        <- Enter for 80

Enter your Api Key (not echoed):                                 <- paste, nothing shows

------------------------------------------------------------------------------
 Step 4 of 6: business unit
------------------------------------------------------------------------------
   1. Example Business Unit  (aBcDeFgHiJkLmNoPqRsT)  <- default
Which business unit? [Enter for the default]                     <- Enter

------------------------------------------------------------------------------
 Step 5 of 6: assessment
------------------------------------------------------------------------------
This business unit has no "CIS 8.1" assessments yet.
Name for the new assessment:                                     <- a name
Create it? [Y/n]                                                 <- Enter

The assessment content exposes nnn CIS safeguards.

------------------------------------------------------------------------------
 Step 6 of 6: review before upload
------------------------------------------------------------------------------
   nnn safeguards scored
         nn at 100
         nn at 75
         nn at 0
     n left untouched, the workbook gives them no score: n.n
   nnn coverage aspects set to 80
    nn notes from "Observations"

Upload to "..." now? [Y/n]                                       <- Enter
```

Check the step 2 counts against the spreadsheet before you answer. If they disagree, stop
there.

Add `--dryRun` to walk the same steps and see the summary without writing. A dry run against a
business unit with no assessment of the target type stops at step 5, because there is no
assessment to read the content from. To rehearse the whole thing including the safeguard
mapping, create the assessment for real and decline the upload at step 6.

## Expected workbook

One row per CIS safeguard, on a single sheet (`CIS-Internal Controls` by default):

| Column              | Required | Used for                                                     |
|---------------------|----------|--------------------------------------------------------------|
| `CIS Safeguard`     | yes      | The safeguard number, e.g. `1.1`, matched to the assessment  |
| `Assessment Status` | yes      | The judgement that becomes the process score                 |
| `Safeguard Score`   | no       | Cross-checked against the status; disagreements are reported |
| `Observations`      | no       | Imported as a note on the safeguard                          |

Every other column is ignored.

## How a status becomes a score

Birdseye scores the process aspect of each safeguard from 0 to 100 in steps of 25. The workbook
records a judgement instead, so `Assessment Status` is converted:

| `Assessment Status` | Becomes                  |
|---------------------|--------------------------|
| Met                 | process score `100`      |
| Partially Met       | process score `75`       |
| Not Met             | process score `0`        |
| Not Assessed        | process score `0`        |
| Not Applicable      | left untouched, no score |

A safeguard the workbook scores is imported at that score. `Not Applicable` carries no score in
the workbook, so it is left alone rather than marked ignored: ignoring applies to every
assessment of the type on the business unit, not just the one being imported.

`Assessment Status` is read rather than the `Safeguard Score` band, because the band collapses
`Not Met` and `Not Assessed` into the same value and cannot express "no score at all".

A status outside that list stops the import and names the rows instead of skipping them.

## Coverage

Each safeguard also has a coverage aspect: how much of the organisation the control reaches. It
only ever scales the process score down, so `100` applies no reduction and a lower value
discounts the score proportionally. `unknown` drops the aspect out of the average rather than
counting it as a zero.

The workbook does not measure coverage, so one value is applied to every safeguard: a multiple
of 5 in `0`-`100`, or `unknown`. The prompt defaults to `80`.

## Assessments

Assessment names are unique per business unit. Entering the name of an existing assessment of
the same type reuses it and overwrites the scores of every safeguard in the workbook, which the
script makes you confirm by typing `UPDATE`. Any other name creates a new assessment.

If a safeguard in the workbook is not in the assessment content, the import stops rather than
uploading a partial set. That normally means the assessment type is a different CIS version.

## Roles

The Api Key needs both roles on the target business unit, because the endpoints split:

| Step                  | Needs                     |
|-----------------------|---------------------------|
| Create the assessment | `Manager`                 |
| Read its content      | either role               |
| Save scores           | `PractitionerAssessments` |
| Save notes            | either role               |

A key with only one role fails partway through. `Manager` does not grant score saving, and
neither does superuser.

`PractitionerAssessments` does not inherit from a parent business unit, so it has to be granted
on the leaf itself. Saving scores also checks the role twice, once on the key and again on the
user account the key was created under. Both need it, on that leaf business unit.

## Options

- `--workbook`, path to the `.xlsx`.
- `--sheet`, sheet holding the safeguards (default `CIS-Internal Controls`).
- `--businessUnitId`, id of the (leaf) business unit to upload to.
- `--assessmentName`, assessment to reuse, or to create if it does not exist.
- `--assessmentTypeId`, assessment content type (default `CIS 8.1`).
- `--coverage`, a multiple of 5 in `0`-`100`, or `unknown` (default `80`).
- `--apiKey`, omit this to be prompted for the key without it being echoed or landing in your
  shell history.
- `--skipNotes`, do not import the `Observations` column as notes.
- `--dryRun`, walk every step and print the summary without writing.
- `--yes`, accept every prompt, for scripted runs. Needs the answers passed as flags.

## Troubleshooting

| What you see                                                      | What it means                                                                                                                                |
|-------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------|
| `That Api Key was rejected`                                       | The key is expired or wrong. Check it in Birdseye under the business unit's Api Keys.                                                        |
| `403 ... does not have the assessments.scores:create permission`  | The key, or the user it belongs to, is missing `PractitionerAssessments` on that leaf business unit. The role does not inherit from a parent. |
| `400 Invalid Request Data format` on create                       | The assessment name is already taken on the business unit. Names must be unique per business unit.                                           |
| `N safeguards in the workbook are not in this assessment content` | The assessment type is a different CIS version from the one the workbook was built against. Nothing was uploaded.                            |
| `N rows have a status outside [...]`                              | A row's `Assessment Status` is not one of the five the workbook allows. The message names the rows. Fix the spreadsheet.                      |
| `WARNING: N rows where Safeguard Score does not match ...`        | One of the two columns was hand-edited. The import uses `Assessment Status` and continues. Check the named rows.                              |

## Tests

```
python -m unittest test_importCisWorkbook
```
