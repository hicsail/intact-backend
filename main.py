import datetime
import enum
from contextlib import asynccontextmanager
from typing import Union

from fastapi import FastAPI
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
    study_id: str
    participant_id: str
    url: str
    study_type: StudyType
    status: StudyStatus
    combined_score: float


class Test(BaseModel):
    # study: Study
    study_id: str
    time_started: datetime.datetime
    device_info: str
    test_type: TestType
    notes: Union[str, None] = None


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.post("/tests/")
def insert_test(test: Test):
    # TODO: Check test.study_id and update corresponding Study
    try:
        tests = db.get_collection("tests")
        tests.insert_one(test.dict())
        return test.dict()
    except Exception as e:
        raise Exception("Unable to insert test: ", e)
