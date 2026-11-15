from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ORMModel, UserBrief


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class WorkspaceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class JoinIn(BaseModel):
    invite_code: str = Field(min_length=4, max_length=32)


class AddMemberIn(BaseModel):
    email: EmailStr


class MemberUpdate(BaseModel):
    nicknames: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("nicknames")
    @classmethod
    def clean(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for n in v:
            n = n.strip()[:50]
            if n and n.lower() not in {x.lower() for x in out}:
                out.append(n)
        return out


class MemberOut(ORMModel):
    user: UserBrief
    role: str
    nicknames: list[str]
    joined_at: datetime


class BoardBrief(ORMModel):
    id: int
    name: str


class WorkspaceSummary(BaseModel):
    id: int
    name: str
    my_role: str
    member_count: int
    board_count: int


class WorkspaceDetail(BaseModel):
    id: int
    name: str
    owner_id: int
    invite_code: str
    my_role: str
    members: list[MemberOut]
    boards: list[BoardBrief]
