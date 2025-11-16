import os
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import Email as EmailSchema, Tag as TagSchema, Folder as FolderSchema, Event as EventSchema

app = FastAPI(title="HoloMail API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------
# Utils
# ---------------------------

def to_object_id(id_str: str) -> ObjectId:
    return ObjectId(id_str)


def serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    d = dict(doc)
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    # Convert datetimes to isoformat strings
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


async def broadcast(event: Dict[str, Any]):
    removable = []
    for ws in active_connections:
        try:
            await ws.send_json(event)
        except Exception:
            removable.append(ws)
    for ws in removable:
        try:
            active_connections.remove(ws)
        except Exception:
            pass


# ---------------------------
# WebSocket for realtime notifications
# ---------------------------
active_connections: List[WebSocket] = []


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        await websocket.send_json({"type": "connected", "message": "Realtime channel ready"})
        while True:
            # We don't expect messages from client; keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in active_connections:
            active_connections.remove(websocket)


# ---------------------------
# Health & test
# ---------------------------
@app.get("/")
def read_root():
    return {"message": "HoloMail backend running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    return response


# ---------------------------
# Schemas endpoint (for database viewer tooling)
# ---------------------------
class SchemaInfo(BaseModel):
    name: str
    json_schema: Dict[str, Any]


@app.get("/schema", response_model=List[SchemaInfo])
def get_schema():
    models = [
        ("email", EmailSchema),
        ("tag", TagSchema),
        ("folder", FolderSchema),
        ("event", EventSchema),
    ]
    out = []
    for name, model in models:
        out.append({
            "name": name,
            "json_schema": model.model_json_schema(),
        })
    return out


# ---------------------------
# Mailbox API
# ---------------------------
class EmailCreate(BaseModel):
    subject: str
    sender: str
    recipient: str
    body: Optional[str] = None
    preview: Optional[str] = None
    folder: str = "inbox"
    tags: List[str] = []
    is_read: bool = False


@app.get("/api/emails")
def list_emails(
    q: Optional[str] = Query(None, description="Search term"),
    folder: Optional[str] = None,
    tag: Optional[str] = None,
    is_read: Optional[bool] = None,
    page: int = 1,
    limit: int = 20,
):
    filter_dict: Dict[str, Any] = {"is_deleted": {"$ne": True}}
    if folder:
        filter_dict["folder"] = folder
    if tag:
        filter_dict["tags"] = tag
    if is_read is not None:
        filter_dict["is_read"] = is_read
    if q:
        filter_dict["$or"] = [
            {"subject": {"$regex": q, "$options": "i"}},
            {"sender": {"$regex": q, "$options": "i"}},
            {"preview": {"$regex": q, "$options": "i"}},
        ]

    cursor = db["email"].find(filter_dict).sort("received_at", -1).skip((page - 1) * limit).limit(limit)
    items = [serialize_doc(d) for d in cursor]
    return {"items": items, "page": page, "limit": limit}


@app.post("/api/emails")
async def create_email(payload: EmailCreate):
    data = payload.model_dump()
    if not data.get("preview") and data.get("body"):
        data["preview"] = (data["body"] or "")[:140]
    if not data.get("received_at"):
        data["received_at"] = datetime.now(timezone.utc)
    inserted_id = create_document("email", data)
    doc = db["email"].find_one({"_id": ObjectId(inserted_id)})
    serialized = serialize_doc(doc)
    await broadcast({"type": "email_created", "email": serialized})
    return {"id": inserted_id, "email": serialized}


class BulkAction(BaseModel):
    ids: List[str] = Field(..., description="List of email ids")
    action: str = Field(..., description="archive|delete|mark_read|mark_unread|move_folder|add_tag|remove_tag")
    folder: Optional[str] = None
    tag: Optional[str] = None


@app.patch("/api/emails/bulk")
async def bulk_update(payload: BulkAction):
    ids = [to_object_id(i) for i in payload.ids]
    filt = {"_id": {"$in": ids}}

    update: Dict[str, Any] = {}
    if payload.action == "archive":
        update = {"$set": {"is_archived": True, "folder": "archive"}}
    elif payload.action == "delete":
        update = {"$set": {"is_deleted": True, "folder": "trash"}}
    elif payload.action == "mark_read":
        update = {"$set": {"is_read": True}}
    elif payload.action == "mark_unread":
        update = {"$set": {"is_read": False}}
    elif payload.action == "move_folder" and payload.folder:
        update = {"$set": {"folder": payload.folder}}
    elif payload.action == "add_tag" and payload.tag:
        update = {"$addToSet": {"tags": payload.tag}}
    elif payload.action == "remove_tag" and payload.tag:
        update = {"$pull": {"tags": payload.tag}}
    else:
        return {"updated": 0, "message": "No valid action provided"}

    result = db["email"].update_many(filt, update)
    await broadcast({"type": "emails_updated", "action": payload.action, "count": result.modified_count})
    return {"updated": result.modified_count}


# ---------------------------
# Tags & Folders
# ---------------------------
class TagCreate(BaseModel):
    name: str
    color: str = "#60a5fa"


@app.get("/api/tags")
def list_tags():
    docs = get_documents("tag")
    return [serialize_doc(d) for d in docs]


@app.post("/api/tags")
def create_tag(payload: TagCreate):
    tag_id = create_document("tag", payload)
    return {"id": tag_id}


class FolderCreate(BaseModel):
    name: str
    icon: Optional[str] = None


@app.get("/api/folders")
def list_folders():
    docs = get_documents("folder")
    return [serialize_doc(d) for d in docs]


@app.post("/api/folders")
def create_folder(payload: FolderCreate):
    folder_id = create_document("folder", payload)
    return {"id": folder_id}


# ---------------------------
# Calendar Events
# ---------------------------
class EventCreate(BaseModel):
    title: str
    starts_at: datetime
    ends_at: Optional[datetime] = None
    notes: Optional[str] = None


@app.get("/api/events")
def list_events(limit: int = 20):
    docs = db["event"].find({}).sort("starts_at", -1).limit(limit)
    return [serialize_doc(d) for d in docs]


@app.post("/api/events")
def create_event(payload: EventCreate):
    event_id = create_document("event", payload)
    return {"id": event_id}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
