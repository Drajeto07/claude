from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    # NIST SP 800-63B: a length floor, no composition rules. The ceiling only bounds request size.
    password: str = Field(min_length=8, max_length=256)
    fullName: str | None = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserResponse(BaseModel):
    id: str
    email: str
    fullName: str | None
    workspaceId: str
