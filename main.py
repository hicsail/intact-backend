import datetime
import enum
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
app = FastAPI()

client = MongoClient(settings.db_connection_str)

try:
    database = client.get_database(settings.db_name)
    mangoes = database.get_collection("mangoes")

    query = {"color": "red"}
    mango = mangoes.find_one(query)

    print(f"Your red mango is: {mango}")

    client.close()

except Exception as e:
    raise Exception("Unable to find the document due to the following error: ", e)


# Should we use Enums?
class StudyType(enum.Enum):
    BASELINE = 1
    FOLLOWUP = 2


class StudyStatus(enum.Enum):
    NOT_STARTED = 1
    IN_PROGRESS = 2
    COMPLETE = 3


# Or maybe these should be StrEnums.
class TestType(enum.StrEnum):
    IMMEDIATE_RECALL = enum.auto()
    # If we care about underscores in python vs dashes in the csv:
    DELAYED_RECALL = "delayed-recall"
    CHOICE_REACTION_TIME = enum.auto()
    VISUAL_PAIRED_ASSOCIATES = enum.auto()
    DIGIT_SYMBOL_MATCHING = enum.auto()
    SPATIAL_MEMORY = enum.auto()


class Study(BaseModel):
    study_id: str
    participant_id: str
    url: str
    study_type: StudyType
    status: StudyStatus
    combined_score: float


class Test(BaseModel):
    study: Study
    time_started: datetime.datetime
    device_info: str
    test_type: TestType
    notes: Union[str, None] = None


class Item(BaseModel):
    name: str
    price: float
    is_offer: Union[bool, None] = None


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.get("/items/{item_id}")
def read_item(item_id: int, q: Union[str, None] = None):
    return {"item_id": item_id, "q": q}


@app.put("/items/{item_id}")
def update_item(item_id: int, item: Item):
    return {"item_name": item.name, "item_id": item_id}
