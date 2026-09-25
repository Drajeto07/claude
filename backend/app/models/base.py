from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base of everything the API sends or receives. In the OpenAPI schema, a
    response field with a default counts as required, since it is always sent;
    the frontend's generated types (frontend/types/generated/api.ts) then don't
    mark it optional. Changes the schema only, never validation or output."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
