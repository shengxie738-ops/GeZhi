from pydantic import BaseModel, Field
from typing import List, Literal, Optional

class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    sessionId: Optional[str] = None
    agent_mode: Optional[str] = None
    agent_id: Optional[str] = None
    agent_model: Optional[str] = None
    agent_prompt: Optional[str] = None
    conversation_id: Optional[str] = None
    project_id: Optional[str] = None
    repository_id: Optional[str] = None
    force_rag: bool = False
    is_diagnosis: Optional[bool] = False
    problem_id: Optional[str] = None
    problem_title: Optional[str] = None
    user_code: Optional[str] = None
    course_dataset_ids: Optional[List[str]] = None
    skill_ids: Optional[List[Literal["academic-review"]]] = Field(default=None, max_length=1)
