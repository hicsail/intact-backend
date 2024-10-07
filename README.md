# intact-backend

This is the backend server for INTACT. It uses FastAPI and MongoDB.

## Configuration

Copy `.env.example` to `.env` and edit the file with your own configuration values.
For documentation and defaults for each variable, see the `Settings` class in `main.py`.

## Set up for local dev

`pyenv virtualenv 3.12.4 intact-backend`

`pyenv activate intact-backend`

`poetry install`

(or equivalent)

Recommended: Set up your IDE or a pre-commit hook to Blacken files automatically.
Otherwise, remember to Blacken everything manually before committing.

Run in development mode:
`fastapi dev`

Run in production mode:
`fastapi run`

View OpenAPI/Swagger docs: go to http://localhost:8000/docs

View admin page: go to http://localhost:8000/admin

## Or run a local compose stack

`docker compose up` and go to http://localhost:1333/docs (OpenAPI) or http://localhost:1333/admin (admin page).

You will probably want to delete/comment out the `backup` service for this use case.


# Workflow

The INTACT backend interacts with two entities: (1) researchers/administrators who are running the study, and (2) study participants. Admins interact with the backend through the admin page `/admin`; study participants interact with the *front*-end, and the front-end interacts with a single endpoint, POST /tests/.

Neither admins nor study participants authenticate to the server. Admins submit an admin password (see/configure `ADMIN_PASSWORD` above) via HTML form/POST request; study participants pass a `study_id` (*not* a `participant_id` - each `participant_id` is linked to one or more *baseline* or *follow-up* studies) via URL.

Admin-facing instructions can be found by loading `/admin`. The following is an outline of the expected general sequence of events.

### 1. Admin generates a list of participant IDs (not using the server)

The participant IDs must be alphanumeric. They can be listed in a .txt or .csv file as a newline-separated list.
Here is an example of a possible participant ID list.

```
bob
alice
s87gfdkak2
abcdef1234
banana
```

### 2. Admin generates studies and distributes URLs to participants

The admin form presents the option of submitting the participant ID list directly as plaintext (this will submit to POST /studies/), or as a .txt or .csv file (this will submit to POST /studies/upload-file).

The default query parameters will generate one baseline and one follow-up study per participant. Adjust as desired.

The POST /studies/ and POST /studies/upload-file/ endpoints  will return the newly generated studies as a JSON list. POST /studies/download-file will retrieve _all_ studies (that is, including any previously generated) and return them as a .csv file.

A research admin can use the CSV study list to distribute the baseline and follow-up study URLs to each participant (at the appropriate times/time intervals).

### 3. Participants do studies; front-end posts test results to the server

The front-end will use POST /tests/ to register a new test result. This should be done by the front-end client every time a participant completes a test. Refer to the example input value and consult the Schemas at the bottom of the OpenAPI page to find out what fields are expected for each different kind of test. The `study_id` field of the test must match the `study_id` of one of the studies previously generated.

### 4. Admin retrieves test data

Through the admin form, the admin can use POST /tests/zip-archive/download-file to get all test data as a ZIP archive of CSV files, or POST /tests/single-test-type/download-file to get data for a single test type as a single CSV. This data can be filtered by participant ID.

It is expected that the participants will take their studies at different, staggered times (as opposed to a coordinated baseline date followed by a coordinated follow-up date), and that the admin(s) will retrieve the data repeatedly and periodically.
