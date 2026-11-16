from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Priority = Literal['alta', 'media', 'baja']

class TaskCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: Title
    description: str | None = Field(default=None, max_length=255)
    completed: bool = False
    priority: Priority = 'media'

class TaskStatusUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    completed: bool

class TaskResponse(TaskCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int

class LoginRequest(BaseModel):
    username: Username
    password: str = Field(min_length=1, max_length=128)

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    name: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    expires_in: int
    user: UserResponse

NewPassword = Annotated[str, StringConstraints(min_length=15, max_length=128)]

class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=50, pattern=r'^[a-zA-Z0-9_.-]+$')]
    password: NewPassword
    confirm_password: str = Field(max_length=128)

    @field_validator('username')
    @classmethod
    def normalize_username(cls, value):
        value = value.lower()
        if value == 'demo':
            raise ValueError('Elegí otro usuario; demo está reservado.')
        return value

    @model_validator(mode='after')
    def validate_passwords(self):
        if not self.password.strip():
            raise ValueError('La contraseña no puede contener solo espacios.')
        if self.password != self.confirm_password:
            raise ValueError('Las contraseñas no coinciden.')
        return self

class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: str = Field(min_length=1, max_length=128)
    new_password: NewPassword
    confirm_password: str = Field(max_length=128)

    @model_validator(mode='after')
    def validate_passwords(self):
        if not self.new_password.strip():
            raise ValueError('La contraseña no puede contener solo espacios.')
        if self.new_password != self.confirm_password:
            raise ValueError('Las contraseñas no coinciden.')
        if self.current_password == self.new_password:
            raise ValueError('Elegí una contraseña diferente de la actual.')
        return self
