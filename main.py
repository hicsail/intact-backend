import csv
import datetime
import enum
from bson.objectid import ObjectId
from contextlib import asynccontextmanager
from typing import Annotated, Union

from fastapi import FastAPI, File, Response, status
from fastapi.responses import FileResponse
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


class VisualPairedAssociatesResult(BaseModel):
    """
    - vpa_split_times: Time-to-answer per picture question. Should be length <=20. In... milliseconds? Will put Int for now.
    - vpa_split_scores: Correct-or-wrong per picture question. Should be length <=20.
    - vpa_total_score: Number correct out of 20.

    (The split lists will be length <20 when the participant times out before finishing all 20 questions.)
    """

    vpa_split_times: list[int]
    vpa_split_scores: list[bool]
    vpa_total_score: int


class ChoiceReactionTimeResult(BaseModel):
    """
    - crt_split_times: Reaction-time per question. Variable length. In... milliseconds? Will put Int for now.
    - crt_split_scores: Correct-or-wrong per question. Variable length.
    - crt_lefthand_correct: Number of times <left> was the correct answer and participant hit <left>.
    - crt_lefthand_attempted: Number of times <left> was the correct answer and participant answered something.
    - crt_righthand_correct: Number of times <right> was the correct answer and participant hit <right>.
    - crt_righthand_attempted: Number of times <right> was the correct answer and participant answered something.
    - crt_total_correct: Number of times participant answered correctly.
    - crt_total_attempted: Number of times participant answered something.

    (The participant will time out after 90 seconds, so the "attempted" counts will vary, and the split lists will vary in length.)
    """

    crt_split_times: list[int]
    crt_split_scores: list[bool]
    crt_lefthand_correct: int
    crt_lefthand_attempted: int
    crt_righthand_correct: int
    crt_righthand_attempted: int
    crt_total_correct: int
    crt_total_attempted: int


class DigitSymbolMatchingResult(BaseModel):
    """
    - dsm_split_times: Reaction-time per question. Variable length. In... milliseconds? Will put Int for now.
    - dsm_split_scores: Correct-or-wrong per question. Variable length.
    - dsm_total_correct: Number of times participant answered correctly.
    - dsm_total_attempted: Number of times participant answered something.

    (The participant will time out after 90 seconds, so the "attempted" count will vary, and the split lists will vary in length.)
    """

    dsm_split_times: list[int]
    dsm_split_scores: list[bool]
    dsm_total_correct: int
    dsm_total_attempted: int


class ImmediateRecallResult(BaseModel):
    """
    - ir_split_times: Time-to-answer per attempt. Variable length of 1 or 2. In... milliseconds? Will put Int for now.
    - ir_score: 2 pts if correct on first attempt, 1 pt if on second attempt, 0 pts if failed both attempts.
    """

    ir_split_times: list[int]
    ir_score: int


class DelayedRecallResult(BaseModel):
    """
    - dr_time: Time-to-answer for the one attempt. In... milliseconds? Will put Int for now.
    - dr_score: 0-5 pts corresponding to number of animals correctly recalled.
    """

    dr_time: int
    dr_score: int


class SpatialMemoryResult(BaseModel):
    """
    - sm_split_times: Time-to-answer per puzzle. Variable length <=5. In... milliseconds? Will put Int for now.
    - sm_split_scores: Correct-or-wrong per puzzle. Variable length <=5.
    - sm_total_correct: 0-5 pts.

    (No total-attempted field because this may be fewer than 5 if participant timed out, but never more than 5.)
    """

    sm_split_times: list[int]
    sm_split_scores: list[bool]
    sm_total_correct: int


class Test(BaseModel):
    # Let DB maintain _id field; manage test_id separately.
    # No strong reason except it slightly simplifies CSV export by removing the need to rename the field.
    test_id: str
    # study: Study # Embed or nah?
    study_id: str
    time_started: datetime.datetime
    device_info: str
    test_type: TestType
    # Optional field for potential msgs like "participant timed out" (added by frontend/client) or
    # "could not find study" (added by backend/server) or any other such.
    # (So the server - this codebase - should append to this field, not replace it.)
    notes: Union[str, None] = None
    result: Union[
        VisualPairedAssociatesResult,
        ChoiceReactionTimeResult,
        DigitSymbolMatchingResult,
        ImmediateRecallResult,
        DelayedRecallResult,
        SpatialMemoryResult,
        None,
    ] = None


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


@app.get("/studies/")
def get_studies_as_list():
    studies = db.get_collection("studies")
    all_studies = studies.find({}, {"_id": 0})  # Exclude _id field

    return [s for s in all_studies]


@app.get("/studies/download-file")
def get_studies_as_csv_file():
    studies = db.get_collection("studies")
    all_studies = studies.find({}, {"_id": 0})  # Exclude _id field

    with open("studies.csv", "w", newline="") as csvfile:
        fieldnames = Study.model_fields.keys()
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for s in all_studies:
            writer.writerow(s)

    return FileResponse("studies.csv")


@app.post("/tests/")
def insert_test(test: Test):
    # TODO: Check test.study_id and update corresponding Study
    try:
        tests = db.get_collection("tests")
        tests.insert_one(test.dict())
        return test.dict()
    except Exception as e:
        raise Exception("Unable to insert test: ", e)


@app.get("/tests/")
def get_tests_as_list():
    tests = db.get_collection("tests")
    all_tests = tests.find({}, {"_id": 0})  # Exclude _id field

    return [t for t in all_tests]


@app.get("/tests/download-file")
def get_tests_as_csv_file():
    tests = db.get_collection("tests")
    all_tests = tests.find({}, {"_id": 0})  # Exclude _id field

    with open("tests.csv", "w", newline="") as csvfile:

        # Get the fieldnames, but throw out the "result" field.
        fields = Test.model_fields
        fields.pop("result")
        fieldnames = fields.keys()
        # Instead, normalize the result fields into the fieldnames.
        # (This is why, in the xyzResults class fields, all the field names are prefixed.)
        fieldnames ^= VisualPairedAssociatesResult.model_fields.keys()
        fieldnames ^= ChoiceReactionTimeResult.model_fields.keys()
        fieldnames ^= DigitSymbolMatchingResult.model_fields.keys()
        fieldnames ^= ImmediateRecallResult.model_fields.keys()
        fieldnames ^= DelayedRecallResult.model_fields.keys()
        fieldnames ^= SpatialMemoryResult.model_fields.keys()

        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        # TODO: Also hoist the study info into here
        for test in all_tests:
            testresult = test.pop("result")
            test.update(testresult)
            writer.writerow(test)

    return FileResponse("tests.csv")
