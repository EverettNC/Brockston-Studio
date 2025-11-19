"""
BROCKSTON Studio API Models

Pydantic models for request/response validation.
"""

from typing import List, Dict, Optional
from pydantic import BaseModel, Field


# File operation models

class OpenFileResponse(BaseModel):
    """Response for opening a file."""
    path: str = Field(..., description="Path to the opened file")
    content: str = Field(..., description="File contents as a string")


class SaveFileRequest(BaseModel):
    """Request to save a file."""
    path: str = Field(..., description="Path to the file to save")
    content: str = Field(..., description="Updated file contents")


class SaveFileResponse(BaseModel):
    """Response for saving a file."""
    status: str = Field(default="ok", description="Operation status")
    path: Optional[str] = Field(None, description="Path to saved file")


# BROCKSTON chat models

class ChatMessage(BaseModel):
    """Single chat message."""
    role: str = Field(..., description="Role: 'system', 'user', or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatContext(BaseModel):
    """Context information for chat."""
    path: Optional[str] = Field(None, description="Current file path")
    code: Optional[str] = Field(None, description="Current file contents")


class ChatRequest(BaseModel):
    """Request to chat with BROCKSTON."""
    messages: List[ChatMessage] = Field(..., description="Conversation messages")
    context: Optional[ChatContext] = Field(None, description="Current file context")


class ChatResponse(BaseModel):
    """Response from BROCKSTON chat."""
    reply: str = Field(..., description="BROCKSTON's reply")


# BROCKSTON code suggestion models

class SuggestFixRequest(BaseModel):
    """Request for BROCKSTON to suggest code improvements."""
    instruction: str = Field(..., description="What to do (e.g., 'refactor for clarity')")
    path: Optional[str] = Field(None, description="Current file path")
    code: str = Field(..., description="Current file contents")


class SuggestFixResponse(BaseModel):
    """Response with suggested code improvements."""
    proposed_code: str = Field(..., description="Full rewritten version of the file")
    summary: str = Field(..., description="Short description of changes")


# Git operation models

class CloneRepoRequest(BaseModel):
    """Request to clone a Git repository."""
    git_url: str = Field(..., description="Git repository URL (HTTPS)")
    folder_name: Optional[str] = Field(None, description="Optional custom folder name")


class CloneRepoResponse(BaseModel):
    """Response for cloning a repository."""
    status: str = Field(default="ok", description="Operation status")
    local_path: str = Field(..., description="Absolute path to cloned repository")
    workspace_name: str = Field(..., description="Name of the cloned repository folder")


# Error response model

class ErrorResponse(BaseModel):
    """Error response."""
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Additional error details")
