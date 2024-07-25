import datetime
import enum
from bson.objectid import ObjectId
from contextlib import asynccontextmanager
from typing import Annotated, Union

from fastapi import FastAPI, File, Response, status
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from pymongo import MongoClient


class Settings(BaseSettings):
    hostname: str = "localhost"
    db_connection_str: str = "mongodb://localhost:27017/"
    db_name: str = "intact"

    # In development, read settings from .env.
    # In production, just set environment variables.
    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()

client = MongoClient(settings.db_connection_str)
db = client.get_database(settings.db_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    A MongoClient is a pool of db connections, so is shared across requests.
    This lifespan context manager closes the client on app shutdown.
    """
    yield
    client.close()


app = FastAPI(lifespan=lifespan)


class StudyType(enum.StrEnum):
    BASELINE = "baseline"
    FOLLOWUP = "followup"


class StudyStatus(enum.StrEnum):
    NOT_STARTED = "not-started"
    IN_PROGRESS = "in-progress"
    COMPLETE = "complete"


class TestType(enum.StrEnum):
    IMMEDIATE_RECALL = "immediate-recall"
    DELAYED_RECALL = "delayed-recall"
    CHOICE_REACTION_TIME = "choice-reaction-time"
    VISUAL_PAIRED_ASSOCIATES = "visual-paired-associates"
    DIGIT_SYMBOL_MATCHING = "digit-symbol-matching"
    SPATIAL_MEMORY = "spatial-memory"


class Study(BaseModel):
    # Let DB maintain _id field; manage study_id separately.
    # No strong reason except it slightly simplifies CSV export by removing the need to rename the field.
    study_id: str
    participant_id: str
    url: str
    study_type: StudyType
    study_status: StudyStatus
    combined_score: Union[float, None] = None


class Test(BaseModel):
    # Let DB maintain _id field; manage test_id separately.
    # No strong reason except it slightly simplifies CSV export by removing the need to rename the field.
    test_id: str
    # study: Study # Embed or nah?
    study_id: str
    time_started: datetime.datetime
    device_info: str
    test_type: TestType
    notes: Union[str, None] = None


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.post("/studies/")
def create_studies_from_list(
    participant_ids: list[str],
    response: Response,
    baselines_per_participant: int = 1,
    followups_per_participant: int = 1,
):
    """
    Given a list of alphanumeric participant IDs, generate and return a list of studies with corresponding URLs.
    If baselines_per_participant or followups_per_participant is specified (default 1),
    generate that many baseline or followup studies per participant.

    (If it turns out we do not want to track participant IDs and do not want to link baselines to followups,
    then just give this endpoint a list of ints, get back a list of study IDs/URLs, and throw out the participant IDs
    and the baseline/followup column.)

    NB: If this is called more than once, it will generate additional studies (it is not idempotent).
    """
    return create_studies(
        participant_ids, response, baselines_per_participant, followups_per_participant
    )


@app.post("/studies/upload-file/")
def create_studies_via_file_upload(
    participant_ids: Annotated[bytes, File()],
    response: Response,
    baselines_per_participant: int = 1,
    followups_per_participant: int = 1,
):
    """
    Like create_studies, but participant IDs are given via file upload.
    The uploaded file should contain only a newline-separated list of alphanumeric participant IDs.
    Blank lines will be ignored.
    """
    # Developer note: This uses the File class and not the UploadFile class; it stores the whole file in memory.
    # This works well for small files. If files get too big, switch to UploadFile.

    rows = str(participant_ids, encoding="utf-8").splitlines()
    return create_studies(
        rows, response, baselines_per_participant, followups_per_participant
    )


def create_studies(
    participant_ids: list[str],
    response,
    baselines_per_participant,
    followups_per_participant,
):
    studies = db.get_collection("studies")

    records_to_insert = []
    for pid in participant_ids:
        if len(pid) == 0:
            # Ignore empty lines, most likely found at end of file.
            continue
        if not pid.isalnum():
            response.status_code = status.HTTP_400_BAD_REQUEST
            return "Non-alphanumeric participant IDs are not allowed"

        for b in range(baselines_per_participant):
            study_id = str(ObjectId())
            new_baseline_study = Study(
                study_id=study_id,
                # TODO: Confirm URL structure
                url=settings.hostname.rstrip("/") + "/" + str(study_id),
                participant_id=pid,
                study_type=StudyType.BASELINE,
                study_status=StudyStatus.NOT_STARTED,
            )
            records_to_insert.append(new_baseline_study.dict())
        for f in range(followups_per_participant):
            study_id = str(ObjectId())
            new_followup_study = Study(
                study_id=study_id,
                # TODO: Confirm URL structure
                url=settings.hostname.rstrip("/") + "/" + str(study_id),
                participant_id=pid,
                study_type=StudyType.FOLLOWUP,
                study_status=StudyStatus.NOT_STARTED,
            )
            records_to_insert.append(new_followup_study.dict())
    try:
        ins_res = studies.insert_many(records_to_insert)
        # insert_many adds _id to dicts; remove them.
        # Tried filtering with FastAPI response model but no dice?
        for i in records_to_insert:
            i.pop("_id")
        return records_to_insert
    except Exception as e:
        raise Exception("Unable to complete study generation: ", e)


@app.post("/tests/")
def insert_test(test: Test):
    # TODO: Check test.study_id and update corresponding Study
    try:
        tests = db.get_collection("tests")
        tests.insert_one(test.dict())
        return test.dict()
    except Exception as e:
        raise Exception("Unable to insert test: ", e)
