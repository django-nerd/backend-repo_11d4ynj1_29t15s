import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
from datetime import datetime

from database import db, create_document, get_documents
from schemas import Plan as PlanSchema, Order as OrderSchema
from bson import ObjectId

app = FastAPI(title="Will Writing Service API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "Will Writing Service Backend Running"}


# --------- Helpers ---------

def oid(oid_str: str) -> ObjectId:
    try:
        return ObjectId(oid_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ID format")


def ensure_default_plans() -> List[dict]:
    """Seed default plans if none exist and return list of plans"""
    existing = list(db["plan"].find({})) if db else []
    if not existing and db is not None:
        defaults = [
            {
                "name": "Essential Will",
                "description": "A legally valid simple Will for a single person.",
                "price": 79.0,
                "features": [
                    "Legally valid simple Will",
                    "Appointment of executors",
                    "Basic gifts and bequests",
                ],
            },
            {
                "name": "Couples Will",
                "description": "Mirror Wills for couples with aligned wishes.",
                "price": 129.0,
                "features": [
                    "Two matching Wills",
                    "Guardians for children",
                    "Replacement executors",
                ],
            },
            {
                "name": "Premium Estate Plan",
                "description": "Comprehensive Will with additional estate planning guidance.",
                "price": 199.0,
                "features": [
                    "Complex gifts and trusts",
                    "Digital asset wishes",
                    "One review session",
                ],
            },
        ]
        for d in defaults:
            d["created_at"] = datetime.utcnow()
            d["updated_at"] = datetime.utcnow()
        db["plan"].insert_many(defaults)
        existing = list(db["plan"].find({}))
    return existing


# --------- Schemas (request bodies) ---------

class CreateOrderBody(BaseModel):
    plan_id: str
    first_name: str
    last_name: str
    email: EmailStr
    phone: Optional[str] = None
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: Optional[str] = None
    postal_code: str
    country: str
    notes: Optional[str] = None


class PaymentBody(BaseModel):
    method: str = Field(default="card")
    token: Optional[str] = None  # For real integrations


# --------- Routes ---------

@app.get("/api/plans")
def list_plans():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    plans = ensure_default_plans()
    # Convert ObjectId to string
    for p in plans:
        p["id"] = str(p["_id"]) if "_id" in p else None
        p.pop("_id", None)
    return {"plans": plans}


@app.post("/api/orders")
def create_order(body: CreateOrderBody):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    # Get plan
    plan_doc = db["plan"].find_one({"_id": oid(body.plan_id)})
    if not plan_doc:
        raise HTTPException(status_code=404, detail="Plan not found")

    order = OrderSchema(
        plan_id=str(plan_doc["_id"]),
        plan_name=plan_doc["name"],
        plan_price=float(plan_doc["price"]),
        first_name=body.first_name,
        last_name=body.last_name,
        email=str(body.email),
        phone=body.phone,
        address_line1=body.address_line1,
        address_line2=body.address_line2,
        city=body.city,
        state=body.state,
        postal_code=body.postal_code,
        country=body.country,
        notes=body.notes,
        total=float(plan_doc["price"])  # no extras for now
    )

    inserted_id = create_document("order", order)
    created = db["order"].find_one({"_id": ObjectId(inserted_id)})
    created["id"] = str(created["_id"]) ; created.pop("_id", None)
    return {"order": created}


@app.get("/api/orders/{order_id}")
def get_order(order_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    doc = db["order"].find_one({"_id": oid(order_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Order not found")
    doc["id"] = str(doc["_id"]) ; doc.pop("_id", None)
    return {"order": doc}


@app.post("/api/orders/{order_id}/pay")
def pay_order(order_id: str, body: PaymentBody):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    doc = db["order"].find_one({"_id": oid(order_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Order not found")

    # Mock payment approval
    payment_ref = f"PMT-{order_id[-6:].upper()}-{int(datetime.utcnow().timestamp())}"

    db["order"].update_one(
        {"_id": oid(order_id)},
        {"$set": {"status": "paid", "payment_reference": payment_ref, "updated_at": datetime.utcnow()}}
    )

    updated = db["order"].find_one({"_id": oid(order_id)})
    updated["id"] = str(updated["_id"]) ; updated.pop("_id", None)
    return {"order": updated}


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
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
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"

    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
