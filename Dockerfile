# Dockerized based on https://fastapi.tiangolo.com/deployment/docker/#docker-image-with-poetry

FROM python:3.12 as requirements-stage

WORKDIR /tmp

RUN pip install poetry

COPY ./pyproject.toml ./poetry.lock* /tmp/

RUN poetry export -f requirements.txt --output requirements.txt --without-hashes



FROM python:3.12

WORKDIR /code

COPY --from=requirements-stage /tmp/requirements.txt /code/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# no /app folder, just a main.py and adminpage.html
COPY ./main.py /code/main.py
COPY ./adminpage.html /code/adminpage.html

# The fastapi process will need to write temporary .csv files in this dir.
# To make this possible on an OpenShift deployment, the dir needs to
# be owned by the root group (already the case here) and be r/w-able by same:
RUN chmod g+rw /code

CMD ["fastapi", "run", "main.py", "--port", "8000"]
