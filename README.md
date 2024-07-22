# intact-backend

This is the backend server for INTACT. It uses FastAPI and MongoDB.

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
