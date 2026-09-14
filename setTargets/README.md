# Set Targets Script

A python script that uses the Birdseye API to read and write assessment targets in bulk, instead of
setting them one control at a time in the app.

It runs in two passes. `--template` writes a CSV of every aspect the key can reach, with the target
currently on it. You fill in the values you want. `--apply` sends them back.

## Setup

1. Install python 3.12 or higher
2. Install the required packages with `pip install -r requirements.txt`

## Generate an API key

The script asks for a key when it starts, without showing it as you type. For an unattended run, put
it in the `OSTRICH_API_KEY` environment variable instead. Do not pipe it in on standard input, because
the script also reads your answers to its prompts from there.

To create a key in Birdseye:

1. Go to **Account info**
2. Find the **API keys** section and choose **Generate key**. The first time, you also have to accept
   the API terms of use.
3. Name the key and pick an expiration date
4. Grant the key the **Manager** role on every business unit whose assessments you plan to change
5. Copy the key immediately. It is shown once and cannot be retrieved afterwards.

Two things about roles:

- Saving a target requires the **Manager** role on the business unit. None of the other roles an API
  key can hold are enough, so a key granted only practitioner roles gets a 403 on every save.
- Your own account needs the API access role on a business unit before you can create keys against
  it. A Birdseye administrator at your organization grants that.

Targets are recorded against the account that created the key, not against the key itself. That
matters when a business unit averages targets, described next.

## How targets are stored

Every business unit uses one of two target strategies, which you can see and change on the business
unit's settings.

| Strategy      | How a target is stored                                                                      |
|---------------|---------------------------------------------------------------------------------------------|
| **Aggregate** | Each manager keeps their own target for a control. The value shown is the average of those. |
| **Override**  | One target per control for the whole assessment, whoever sets it.                           |

On an **aggregate** business unit, saving through this script replaces the targets belonging to the
account that owns the key and leaves everyone else's in the average. If you are the only manager who
has ever set targets, the values you load are the values the assessment shows. If other managers have
set them, your values are averaged with theirs. The script reads who already has targets on each
assessment and asks before saving so you find this out before the write, not after.

On an **override** business unit, the values you load are the values the assessment shows.

Changing the strategy after loading targets is not a neutral operation:

- Aggregate to override carries the current averaged values over, but only on assessments that have
  never been on override before. If an assessment held override targets at some earlier point, those
  older values come back instead.
- Override to aggregate carries nothing over. The override values stop being shown and any older
  per-manager values reappear.

Pick the strategy you want first, then load targets.

## Run

Write a template covering everything the key can reach:

```
python setTargets.py --template
```

Narrow it down with regex filters on business unit and assessment names:

```
python setTargets.py --template --businessUnitFilter ".*Region.*" --assessmentFilter "2026 .*"
```

Both filters match the whole name, so wrap them in `.*` to match part of one.

The template goes to `OstrichTargetTemplate.csv` unless you name a file, as in `--template targets.csv`.
It will not replace a file that already exists, so a half-filled template cannot be lost by re-running
the command. Pass `--overwrite` when replacing it is what you want.

Fill in the `target` and `weight` columns, then check the file without sending anything:

```
python setTargets.py --apply OstrichTargetTemplate.csv --dryRun
```

When the dry run looks right, drop the flag:

```
python setTargets.py --apply OstrichTargetTemplate.csv
```

Rows with both `target` and `weight` left blank are skipped, so you can fill in part of a template and
leave the rest alone.

For an unattended run, pass `--yes`. That answers the shared-targets prompt described below. Without a
terminal to answer it, the script refuses to start rather than stopping partway through.

If you edit the file in Excel, save it with **File, Save As, CSV UTF-8 (comma delimited)**. Other CSV
options write a file the script cannot read when any business unit or assessment name contains an
accented or non-Latin character.

## CSV format

Only three columns are required, plus at least one of `target` and `weight`:

| Column           | Required | Notes                                                  |
|------------------|----------|--------------------------------------------------------|
| `businessUnitId` | yes      | From the template, or the business unit URL in the app |
| `assessmentId`   | yes      | From the template, or the assessment URL in the app    |
| `aspectId`       | yes      | For example `GV.OC-1-PROCESS`                          |
| `target`         | one of   | Whole number                                           |
| `weight`         | one of   | `LOW`, `MED-LOW`, `MEDIUM`, `MED-HIGH`, `HIGH`         |

`set targets example.csv` is the smallest file that works. Any other column is ignored, which is why
the template can carry `businessUnit`, `assessment`, `currentTarget` and `currentWeight` for reading
and still be fed straight back in.

Valid targets depend on the control. Maturity-style aspects take 0 to 100 in steps of 5. Aspects
answered by picking an option only take the values of those options. The script does not try to
predict this; the API validates each value and names the aspect it rejected.

Weight is case-insensitive on input. A blank weight leaves the existing weight alone.

## What the script checks before saving

The API saves one assessment's targets as a single unit: if it rejects anything in the request, none of
it is saved. The script works the same way, so a file with one bad row never leaves an assessment
half-loaded.

- Every `aspectId` exists on that assessment. If any does not, that assessment is skipped and nothing
  is sent for it.
- No aspect id appears twice for the same assessment, which the API also rejects.
- Every `target` is a whole number and every `weight` is one of the five labels. **A single bad row
  skips its whole assessment**, so fix the row and re-run rather than expecting the other rows to have
  gone in.
- Whether anyone already has targets on the assessment, and who.

After each save it re-reads the assessment and reports any requested value that is not there. On an
aggregate business unit the API does not say which manager a value belongs to, so this confirms the
value is present on the assessment rather than proving it is recorded against your account.

The script exits non-zero if any row was rejected, any assessment was skipped or failed, or any saved
value did not read back, so a wrapper script can rely on the exit status.

## API calls

| Purpose                           | Call                                                                        |
|-----------------------------------|-----------------------------------------------------------------------------|
| Exchange the key for a token      | `POST /v1/auth/token`                                                       |
| List business units               | `GET /v1/businessUnits/`                                                    |
| Read the target strategy          | `GET /v1/businessUnits/{businessUnitId}`                                    |
| List assessments                  | `GET /v1/businessUnits/{businessUnitId}/assessments`                        |
| List the aspects of an assessment | `GET /v1/businessUnits/{businessUnitId}/assessments/{assessmentId}/content` |
| Read current targets              | `GET /v1/businessUnits/{businessUnitId}/assessments/{assessmentId}/scores`  |
| Save targets                      | `PUT /v1/businessUnits/{businessUnitId}/assessments/{assessmentId}/targets` |

The token from `/v1/auth/token` expires. When a call comes back 401 the script requests a new token
and retries once, so long runs do not need restarting. Every call has a three minute timeout.

`--baseUrl` points the script at a different Birdseye deployment. It has to be `https`, since the key
and the token both cross that connection.

The set of aspects comes from combining two calls. `/scores` returns one entry per function,
category, question and aspect, and the `nodes` map in `/content` holds every function, category and
question, so what is left after removing them is the aspects. Custom content does not always follow
the id shape the built-in frameworks use, which is why the script derives the list instead of
matching a pattern against the ids.

## Errors

| Message                                                | What to do                                                          |
|--------------------------------------------------------|---------------------------------------------------------------------|
| 403 naming a role the key is missing                   | Add the Manager role to the key on that business unit               |
| `Cannot save scores or targets on a closed assessment` | Reopen the assessment, or pick a different one                      |
| `Cannot set targets on ignored questions`              | The control is ignored on that business unit, so remove the row     |
| `Invalid aspect id: X`                                 | The id does not exist on the assessment, so take it from a template |
| `Invalid target of N for aspect id: X`                 | The control does not accept that value                              |
| `Invalid weight: X`                                    | Use one of the five weight labels                                   |
| `Cannot have duplicate aspect ids: X`                  | The same aspect appears twice for one assessment                    |

## What it does not do

- It does not set scores. Targets and scores are separate, and this only writes targets.
- It does not clear a target. Sending a row sets a value; there is no way to remove one through
  this script.
- It only writes to leaf assessments. A rollup assessment takes its targets from its
  sub-assessments, which appear under their own business units in the template.
