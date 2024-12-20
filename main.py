import asyncio
import csv
import datetime
import enum
import functools
import os
import random
from bson.objectid import ObjectId
from contextlib import asynccontextmanager
from typing import Annotated, Union
from zipfile import ZipFile

from fastapi import BackgroundTasks, FastAPI, File, Form, Response, status, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from pymongo import MongoClient
from sqids import Sqids


class Settings(BaseSettings):
    # STUDY_URL_PREFIX will be combined with study_ids to make the study_urls
    # that are given to participants. Usually this is the hostname of the
    # front-end, plus any necessary path prefix.
    study_url_prefix: str = "https://intact.sail.codes"

    # Details for the MongoDB to be used by this server.
    db_connection_str: str = "mongodb://localhost:27017/"
    db_name: str = "intact"

    # ADMIN_PASSWORD is the password that researchers will use to interact
    # with this server (it is not e.g. a database admin password).
    admin_password: str = "password"

    # Set allowed CORS origins.
    # CORS_FRONTEND_ORIGIN should be set to the hostname of the front-end.
    cors_frontend_origin: str = "https://intact.sail.codes"
    # For development purposes, you may want to set CORS_LOCALHOST_ORIGIN.
    # Note that setting CORS_FRONTEND_ORIGIN *or* CORS_LOCALHOST_ORIGIN to "*"
    # will allow *all* origins (localhost or otherwise).
    cors_localhost_origin: Union[str, None] = None

    # In development, read settings from .env.
    # In production, just set environment variables.
    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()

client = MongoClient(settings.db_connection_str)
db = client.get_database(settings.db_name)

sqids = Sqids(alphabet="abcdefghijklmnopqrstuvwxyz", min_length=4)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    A MongoClient is a pool of db connections, so is shared across requests.
    This lifespan context manager closes the client on app shutdown.
    """
    yield
    client.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_frontend_origin]
    + ([settings.cors_localhost_origin] if settings.cors_localhost_origin else []),
    allow_methods=["*"],
    allow_headers=["*"],
)


def clean_up_files():
    """
    Delete all .csv and .zip files. Called as BackgroundTask after path operations
    which generate files to return to the user.

    This function assumes that the server never generates .csv or .zip files that it
    wants to keep; if this changes, rewrite this function.
    """
    for f in os.listdir():
        if f.endswith((".csv", ".zip")):
            os.remove(f)


def check_admin_password(path_op):
    @functools.wraps(path_op)
    async def wrapper(**kwargs):
        if kwargs["password"] != settings.admin_password:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"message": "Wrong admin password"},
            )
        else:
            rv = path_op(**kwargs)
            if asyncio.iscoroutine(rv):
                return await rv
            else:
                return rv

    return wrapper


class StudyType(enum.StrEnum):
    BASELINE = enum.auto()
    FOLLOWUP = enum.auto()


class TestType(enum.StrEnum):
    IMMEDIATE_RECALL = enum.auto()
    DELAYED_RECALL = enum.auto()
    CHOICE_REACTION_TIME = enum.auto()
    VISUAL_PAIRED_ASSOCIATES = enum.auto()
    DIGIT_SYMBOL_MATCHING = enum.auto()
    SPATIAL_MEMORY = enum.auto()


class Study(BaseModel):
    # Let DB maintain _id field; manage study_id separately.
    # No strong reason except it slightly simplifies CSV export by removing the need to rename the field.
    study_id: str
    participant_id: str
    url: str
    study_type: StudyType


class VisualPairedAssociatesResult(BaseModel):
    """
    Represents the participant's response to one question in a Visual Paired Associates test.

    - vpa_rt: Time-to-answer, in milliseconds.
    - vpa_correct: True if participant answered correctly, false otherwise.
    - vpa_response: Participant's response (image filename).

    A Test of type VISUAL_PAIRED_ASSOCIATES should have a list of VisualPairedAssociatesResults of length <=20; there are 20 questions to a test, but the participant may time out before finishing.
    """

    vpa_rt: int
    vpa_correct: bool
    vpa_response: str


class ChoiceReactionTimeResult(BaseModel):
    """
    Represents the participant's response to one question in a Choice Reaction Time test.

    - crt_rt: Reaction time, in milliseconds.
    - crt_correct: True if participant answered correctly, false otherwise.
    - crt_response: Participant's response ("right" or "left").
    - crt_dwell: Length of time the response key was pressed/held, in milliseconds.

    A Test of type CHOICE_REACTION_TIME should have a list of ChoiceReactionTimeResults, the length of which will vary according to how many questions the participant attempts in the 90 seconds allotted.
    """

    class RightOrLeft(enum.StrEnum):
        RIGHT = enum.auto()
        LEFT = enum.auto()

    crt_rt: int
    crt_correct: bool
    crt_response: RightOrLeft
    crt_dwell: int


class DigitSymbolMatchingResult(BaseModel):
    """
    Represents the participant's response to one question in a Digit Symbol Matching test.

    - dsm_rt: Reaction time, in milliseconds.
    - dsm_correct: True if participant answered correctly, false otherwise.
    - dsm_response: Participant's response (1, 2, or 3).

    A Test of type DIGIT_SYMBOL_MATCHING should have a list of DigitSymbolMatchingResults, the length of which will vary according to how many questions the participant attempts in the 90 seconds allotted.
    """

    class OneTwoOrThree(enum.IntEnum):
        ONE = 1
        TWO = 2
        THREE = 3

    dsm_rt: int
    dsm_correct: bool
    dsm_response: OneTwoOrThree


class ImmediateRecallResult(BaseModel):
    """
    Represents the participant's response to the sole question in an Immediate Recall test, at which they get two attempts.

    - ir_rt_first: Time-to-answer for first attempt, in milliseconds.
    - ir_rt_second: Time-to-answer for second attempt, in milliseconds. Optional (use only when second attempt was made).
    - ir_score: 2 pts if correct on first attempt, 1 pt if correct on second attempt, 0 pts if failed both attempts.

    A Test of type IMMEDIATE_RECALL should have one single ImmediateRecallResult.
    """

    class ZeroOneOrTwo(enum.IntEnum):
        ZERO = 0
        ONE = 1
        TWO = 2

    ir_rt_first: int
    ir_rt_second: Union[int, None] = None
    ir_score: ZeroOneOrTwo


class DelayedRecallResult(BaseModel):
    """
    Represents the participant's response to the sole question in a Delayed Recall test.

    - dr_rt: Time-to-answer, in milliseconds.
    - dr_score: 0-5 pts corresponding to number of animals correctly recalled.

    A Test of type DELAYED_RECALL should have one single DelayedRecallResult.
    """

    class OneToFive(enum.IntEnum):
        ONE = 1
        TWO = 2
        THREE = 3
        FOUR = 4
        FIVE = 5

    dr_rt: int
    dr_score: OneToFive


class SpatialMemoryResult(BaseModel):
    """
    Represents the participant's response to one question in a Spatial Memory test.

    - sm_rt: Time-to-answer, in milliseconds.
    - sm_correct: True if participant answered correctly, false otherwise.

    A Test of type SPATIAL_MEMORY should have a list of SpatialMemoryResults of length 0 to 5; there are 5 questions to a test, but the participant may time out before finishing.
    """

    sm_rt: int
    sm_correct: bool


class TestIn(BaseModel):
    """
    The subset of Test fields that the user/client specifies.
    """

    study_id: str
    time_started: datetime.datetime
    time_elapsed_milliseconds: int  # or timedelta, if desired...
    device_info: str
    result: Union[
        list[VisualPairedAssociatesResult],
        list[ChoiceReactionTimeResult],
        list[DigitSymbolMatchingResult],
        ImmediateRecallResult,
        DelayedRecallResult,
        list[SpatialMemoryResult],
    ]


class Test(TestIn):
    """
    The subset of Test fields that this server provides.
    """

    # Let DB maintain _id field; manage test_id separately.
    # No strong reason except it slightly simplifies CSV export by removing the need to rename the field.
    test_id: str
    test_type: TestType


class ErrorMessage(BaseModel):
    message: str


test_type_to_result_type = {
    TestType.IMMEDIATE_RECALL: ImmediateRecallResult,
    TestType.DELAYED_RECALL: DelayedRecallResult,
    TestType.CHOICE_REACTION_TIME: ChoiceReactionTimeResult,
    TestType.VISUAL_PAIRED_ASSOCIATES: VisualPairedAssociatesResult,
    TestType.DIGIT_SYMBOL_MATCHING: DigitSymbolMatchingResult,
    TestType.SPATIAL_MEMORY: SpatialMemoryResult,
}

result_type_to_test_type = {
    ImmediateRecallResult: TestType.IMMEDIATE_RECALL,
    DelayedRecallResult: TestType.DELAYED_RECALL,
    ChoiceReactionTimeResult: TestType.CHOICE_REACTION_TIME,
    VisualPairedAssociatesResult: TestType.VISUAL_PAIRED_ASSOCIATES,
    DigitSymbolMatchingResult: TestType.DIGIT_SYMBOL_MATCHING,
    SpatialMemoryResult: TestType.SPATIAL_MEMORY,
}


@app.get("/")
def read_root():
    return "This is the INTACT backend. Please visit /docs if you are a developer or /admin if you are a researcher."


@app.get(
    "/studies/{study_id}",
    responses={404: {"model": ErrorMessage}},
)
def get_study(study_id: str):
    """
    Endpoint intended for use by the front-end to check that a given study_id is valid.
    Does not list all study_ids.
    """
    # Dev note: Securing this endpoint against e.g. enumeration attacks
    # does not make sense unless the POST /tests endpoint is similarly secured.
    studies = db.get_collection("studies")
    study = studies.find_one({"study_id": study_id}, {"study_type": 1, "_id": 0})
    if not study:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"message": f"study_id {study_id} does not exist"},
        )
    return study


@app.post(
    "/studies",
    response_model=list[Study],
    responses={400: {"model": ErrorMessage}, 401: {"model": ErrorMessage}},
)
@check_admin_password
def create_studies_from_list(
    password: Annotated[str, Form()],
    participant_ids: Annotated[str, Form()],
    response: Response,
    baselines_per_participant: Annotated[int, Form()] = 1,
    followups_per_participant: Annotated[int, Form()] = 1,
):
    """
    Given a newline-separated list of alphanumeric participant IDs, generate and return a list of studies with corresponding URLs.
    If baselines_per_participant or followups_per_participant is specified (default 1),
    generate that many baseline or followup studies per participant.

    NB: If this is called more than once, it will generate additional studies (it is not idempotent).
    """
    try:
        # rows = [s.strip() for s in participant_ids.split(",")] # if people like comma-separated better
        rows = [s.strip() for s in participant_ids.splitlines()]
    except:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "message": "Could not parse participant_id list; make sure it contains only a newline-separated list of alphanumeric participant IDs."
            },
        )
    return create_studies(
        rows, response, baselines_per_participant, followups_per_participant
    )


@app.post(
    "/studies/upload-file",
    response_model=list[Study],
    responses={400: {"model": ErrorMessage}, 401: {"model": ErrorMessage}},
)
@check_admin_password
async def create_studies_via_file_upload(
    password: Annotated[str, Form()],
    participant_ids_file: Annotated[UploadFile, File()],
    response: Response,
    baselines_per_participant: Annotated[int, Form()] = 1,
    followups_per_participant: Annotated[int, Form()] = 1,
):
    """
    Like create_studies, but participant IDs are given via file upload.
    The uploaded file should contain only a newline-separated list of alphanumeric participant IDs.
    Blank lines will be ignored.
    """
    try:
        participant_ids = await participant_ids_file.read()
        rows = [s.strip() for s in str(participant_ids, encoding="utf-8").splitlines()]
    except:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "message": "Could not read file; make sure it is a .txt or .csv file and contains only a newline-separated list of alphanumeric participant IDs."
            },
        )

    return create_studies(
        rows, response, baselines_per_participant, followups_per_participant
    )


def generate_new_study_ids(number):
    """
    Returns a set of <number> new study_ids.

    PI would like to have short study IDs that are easy to hand-copy.
    Since only a small number of studies is expected to be created - in the low
    hundreds - and study creation happens in infrequent batches, we will just
    generate random ids and manually check for collisions.
    At which point, for good measure, let's make them strictly lowercase
    letters and filter for accidental profanities.

    Because new studies are added to the db in batches (see create_studies),
    new study_ids must be generated by this function in batches - or else
    theoretically it could generate "abcd" twice in a row, and the first one
    would not have made it to the db yet, so the collision would not be caught.
    """
    studies = db.get_collection("studies")
    new_study_ids = set()

    while len(new_study_ids) < number:
        new_study_id = sqids.encode([random.randint(0, 10_000)])
        if list(studies.find({"study_id": new_study_id})):
            continue
        new_study_ids.add(new_study_id)

    return new_study_ids


def create_studies(
    participant_ids: list[str],
    response,
    baselines_per_participant,
    followups_per_participant,
):

    if baselines_per_participant < 0 or followups_per_participant < 0:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "message": "baselines_per_participant and followups_per_participant must be nonnegative"
            },
        )
    if baselines_per_participant == 0 and followups_per_participant == 0:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "message": "At least one of baselines_per_participant and followups_per_participant must be nonzero"
            },
        )
    if len(participant_ids) == 0:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": "Received empty participant list"},
        )
    if (
        len(participant_ids) * (baselines_per_participant + followups_per_participant)
        > 1000
    ):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "message": "Too many studies requested, or too many empty lines in file; please contact SAIL for assistance."
            },
        )

    studies = db.get_collection("studies")

    new_study_ids = generate_new_study_ids(
        len(participant_ids) * (baselines_per_participant + followups_per_participant)
    )
    records_to_insert = []
    for pid in participant_ids:
        if len(pid) == 0:
            # Ignore empty lines, most likely found at end of file.
            continue
        if not pid.isalnum():
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"message": "Non-alphanumeric participant IDs are not allowed"},
            )

        for b in range(baselines_per_participant):
            study_id = new_study_ids.pop()
            new_baseline_study = Study(
                study_id=study_id,
                url=settings.study_url_prefix.rstrip("/") + "/" + str(study_id),
                participant_id=pid,
                study_type=StudyType.BASELINE,
            )
            records_to_insert.append(new_baseline_study.dict())
        for f in range(followups_per_participant):
            study_id = new_study_ids.pop()
            new_followup_study = Study(
                study_id=study_id,
                url=settings.study_url_prefix.rstrip("/") + "/" + str(study_id),
                participant_id=pid,
                study_type=StudyType.FOLLOWUP,
            )
            records_to_insert.append(new_followup_study.dict())
    try:
        ins_res = studies.insert_many(records_to_insert)
        return records_to_insert
    except Exception as e:
        raise Exception("Unable to complete study generation: ", e)


@app.post("/studies/download-file", responses={401: {"model": ErrorMessage}})
@check_admin_password
def get_studies_as_csv_file(
    background_tasks: BackgroundTasks,
    password: Annotated[str, Form()],
) -> FileResponse:
    studies = db.get_collection("studies")
    all_studies = studies.find({}, {"_id": 0})  # Exclude _id field

    with open("studies.csv", "w", newline="") as csvfile:
        fieldnames = Study.model_fields.keys()
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for s in all_studies:
            writer.writerow(s)
    background_tasks.add_task(clean_up_files)

    return FileResponse("studies.csv")


@app.post("/tests", response_model=Test, responses={400: {"model": ErrorMessage}})
def insert_test(test: TestIn, response: Response):
    # Starting from the TestIn fields,
    new_test_dict = test.dict()

    # infer the test_type...
    if isinstance(test.result, list):
        new_test_dict.update(
            {"test_type": result_type_to_test_type[type(test.result[0])]}
        )
    else:
        new_test_dict.update({"test_type": result_type_to_test_type[type(test.result)]})

    # check that the study_id corresponds to an existing study...
    # (note: does _not_ check for an existing submitted test result of this type for this study)
    studies = db.get_collection("studies")
    matched_study = studies.find_one({"study_id": test.study_id})
    if not matched_study:
        # Or maybe this should be lenient and add the record anyway?
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": f"Could not find study with id {test.study_id}"},
        )

    # All OK; give it a test_id...
    new_test_dict.update({"test_id": str(ObjectId())})

    try:
        tests = db.get_collection("tests")
        # Validate/filter against the Test model
        validated_test_dict = Test(**new_test_dict).dict()
        tests.insert_one(validated_test_dict)
        return validated_test_dict
    except Exception as e:
        raise Exception("Unable to insert test: ", e)


def write_single_test_type_to_csv_file(
    csvfile,
    test_type: TestType,
    participant_id: str = None,
):
    studies = db.get_collection("studies")
    tests = db.get_collection("tests")
    all_tests = tests.find({"test_type": test_type}, {"_id": 0})  # Exclude _id field

    # Get the fieldnames, but throw out the "result" and "study_id" fields.
    # (The study_id field will get added back in below, along with all the other study fields.)
    fields = Test.model_fields.copy()
    fields.pop("result")
    fields.pop("study_id")
    fieldnames = fields.keys()

    # Add the result (sub)fields for the requested test type into the fieldnames.
    fieldnames ^= test_type_to_result_type[test_type].model_fields.keys()

    # Also normalize the study fields into the fieldnames.
    fieldnames ^= Study.model_fields.keys()

    writer = csv.DictWriter(csvfile, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
    writer.writeheader()

    for test in all_tests:
        study_id = test.pop("study_id")
        study = studies.find_one({"study_id": study_id})
        if participant_id and study["participant_id"] != participant_id:
            continue
        study.pop("_id")

        test_result = test.pop("result")

        if isinstance(test_result, list):
            for question in test_result:
                test.update(question)
                test.update(study)
                writer.writerow(test)
        else:
            test.update(test_result)
            test.update(study)
            writer.writerow(test)


@app.post("/tests/zip-archive/download-file", responses={401: {"model": ErrorMessage}})
@check_admin_password
def get_tests_as_csv_zip_archive(
    background_tasks: BackgroundTasks,
    password: Annotated[str, Form()],
    participant_id: Annotated[str, Form()] = None,
) -> FileResponse:
    """
    Download results data on all test types, one CSV file per test type, combined into a ZIP archive.

    If `participant_id` is given, restrict the results to those concerning that `participant_id`.

    If no tests are found for a particular test_type or participant_id, an empty CSV file is generated, containing just the header (field names).
    """

    with ZipFile("all-tests.zip", "w") as zipfile:
        for test_type in TestType:
            csv_filename = test_type.value + ".csv"
            with open(csv_filename, "w", newline="") as csvfile:
                write_single_test_type_to_csv_file(csvfile, test_type, participant_id)
            zipfile.write(csv_filename)
    background_tasks.add_task(clean_up_files)

    return FileResponse("all-tests.zip")


@app.post(
    "/tests/single-test-type/download-file", responses={401: {"model": ErrorMessage}}
)
@check_admin_password
def get_single_test_type_as_csv_file(
    background_tasks: BackgroundTasks,
    password: Annotated[str, Form()],
    test_type: Annotated[TestType, Form()],
    participant_id: Annotated[str, Form()] = None,
) -> FileResponse:
    """
    Download results data on one test type, returned in a CSV file.

    If `participant_id` is given, restrict the results to those concerning that `participant_id`.

    If no tests are found for a particular test_type or participant_id, an empty CSV file is generated, containing just the header (field names).
    """

    with open("test.csv", "w", newline="") as csvfile:
        write_single_test_type_to_csv_file(csvfile, test_type, participant_id)
    background_tasks.add_task(clean_up_files)

    return FileResponse("test.csv")


@app.get("/admin", response_class=HTMLResponse)
def admin_form():
    with open("adminpage.html", "r") as f:
        data = f.read()
        return data
