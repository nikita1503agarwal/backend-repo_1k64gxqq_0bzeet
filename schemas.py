"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

# Core mailbox domain schemas

class Email(BaseModel):
    """
    Emails collection schema
    Collection name: "email"
    """
    subject: str = Field(..., description="Email subject line")
    sender: str = Field(..., description="Sender email address")
    recipient: str = Field(..., description="Recipient email address")
    preview: Optional[str] = Field(None, description="Short preview snippet of the body")
    body: Optional[str] = Field(None, description="Full email body (HTML or text)")
    folder: str = Field("inbox", description="Folder name: inbox, sent, archive, trash, etc.")
    tags: List[str] = Field(default_factory=list, description="List of tag names")
    is_read: bool = Field(False, description="Whether the email has been read")
    is_archived: bool = Field(False, description="Whether the email is archived")
    is_deleted: bool = Field(False, description="Soft delete flag")
    received_at: Optional[datetime] = Field(None, description="When the email was received")

class Tag(BaseModel):
    """
    Tags collection schema
    Collection name: "tag"
    """
    name: str = Field(..., description="Tag name")
    color: str = Field("#60a5fa", description="Hex color for the tag badge")

class Folder(BaseModel):
    """
    Folders collection schema
    Collection name: "folder"
    """
    name: str = Field(..., description="Folder name (inbox, sent, archive, trash, custom)")
    icon: Optional[str] = Field(None, description="Icon key for UI")

class Event(BaseModel):
    """
    Calendar events
    Collection name: "event"
    """
    title: str = Field(..., description="Event title")
    starts_at: datetime = Field(..., description="Start datetime (UTC)")
    ends_at: Optional[datetime] = Field(None, description="End datetime (UTC)")
    notes: Optional[str] = Field(None, description="Notes or description")

# Example legacy schemas retained for reference (unused by mailbox app)
class User(BaseModel):
    name: str
    email: str
    address: str
    age: Optional[int] = None
    is_active: bool = True

class Product(BaseModel):
    title: str
    description: Optional[str] = None
    price: float
    category: str
    in_stock: bool = True
