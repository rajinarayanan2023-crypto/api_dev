from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    """Base for response schemas read off SQLAlchemy ORM objects."""

    model_config = ConfigDict(from_attributes=True)


class Message(BaseModel):
    detail: str
