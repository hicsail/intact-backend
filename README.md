# intact-backend

This is the backend server for INTACT. It uses FastAPI and MongoDB.

## Set up for local dev

`pyenv virtualenv 3.12.4 intact-backend`
`pyenv activate intact-backend`
`poetry install`

(or equivalent)

Copy `.env.example` to `.env` and edit the `DB_CONNECTION_STR` and `DB_NAME` to connect to your preferred local/Dockerized Mongo DB. The `HOSTNAME` will determine the hostname in the study URLs given to participants, so should point to the front-end.

Recommended: Set up your IDE or a pre-commit hook to Blacken files automatically.
Otherwise, remember to Blacken everything manually before committing.

Run in development mode:
`fastapi dev`

Run in production mode:
`fastapi run`

View OpenAPI/Swagger docs: go to http://localhost:8000/docs

## Or run a local compose stack

`docker compose up` and go to http://localhost:8000/docs


# Workflow

### 1. Generate a list of participant IDs (not using the server)

The participant IDs must be alphanumeric. You can list them in a .txt or .csv file as a newline-separated list.
Here is an example of a possible participant ID list.

```
bob
alice
s87gfdkak2
abcdef1234
banana
```

### 2. Generate studies and distribute URLs to participants

Use POST /studies/ if you want to pass in a JSON list of participant IDs; use POST /studies/upload-file/ if you want to pass in a file like the example above.

The default query parameters will generate one baseline and one followup study per participant. Adjust as desired.

The POST /studies/ and POST /studies/upload-file/ endpoints  will return the newly generated studies as a JSON list. To retrieve _all_ studies (that is, including any previously generated), use GET /studies/ for a JSON list, or use GET /studies/download-file for a CSV.

An RA can use the CSV study list to get the baseline and followup study URLs for each participant.

### 3. Post test results to the server

Use POST /tests/ to register a new test result. This should be done by the front-end client every time a participant completes a test. Refer to the example input value and consult the Schemas at the bottom of the OpenAPI page to find out what fields are expected for each different kind of test. The `study_id` field of the test must match the `study_id` of one of the studies previously generated.

### 4. Retrieve test data

Use GET /tests/ to get test data as a JSON list. Use GET /tests/download-file to get test data as a CSV.
