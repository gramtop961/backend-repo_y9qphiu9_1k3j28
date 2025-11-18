import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from bson import ObjectId
from datetime import datetime

from database import db, create_document, get_documents
from schemas import Coach, Athlete, Review, Booking

app = FastAPI(title="Coach Marketplace API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Coach Marketplace API"}

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
                response["database"] = f"⚠️  Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response

# ---------- Coaches ----------

@app.post("/coaches", response_model=dict)
def create_coach(coach: Coach):
    coach_id = create_document("coach", coach)
    return {"id": coach_id}

class CoachQuery(BaseModel):
    sport: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    q: Optional[str] = None

@app.post("/coaches/search")
def search_coaches(query: CoachQuery):
    filt = {}
    if query.sport:
        filt["sports"] = query.sport
    if query.city:
        filt["location_city"] = {"$regex": query.city, "$options": "i"}
    if query.state:
        filt["location_state"] = {"$regex": query.state, "$options": "i"}
    if query.q:
        # search in name or bio
        filt["$or"] = [
            {"full_name": {"$regex": query.q, "$options": "i"}},
            {"bio": {"$regex": query.q, "$options": "i"}},
        ]
    coaches = get_documents("coach", filt, limit=50)
    for c in coaches:
        c["id"] = str(c.get("_id"))
        c.pop("_id", None)
    return {"items": coaches}

@app.get("/coaches/{coach_id}")
def get_coach(coach_id: str):
    try:
        doc = db["coach"].find_one({"_id": ObjectId(coach_id)})
        if not doc:
            raise HTTPException(status_code=404, detail="Coach not found")
        doc["id"] = str(doc["_id"]) 
        doc.pop("_id", None)
        return doc
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid coach id")

# ---------- Reviews ----------

@app.post("/reviews", response_model=dict)
def create_review(review: Review):
    # attach server timestamp
    data = review.model_dump()
    data.setdefault("created_at", datetime.utcnow())
    review_id = create_document("review", data)
    # update coach aggregates
    try:
        coach_oid = ObjectId(review.coach_id)
        reviews = list(db["review"].find({"coach_id": review.coach_id}))
        if reviews:
            avg = sum(r.get("rating", 0) for r in reviews) / len(reviews)
            db["coach"].update_one({"_id": coach_oid}, {"$set": {"average_rating": round(avg, 2), "review_count": len(reviews)}})
    except Exception:
        pass
    return {"id": review_id}

@app.get("/coaches/{coach_id}/reviews")
def list_reviews(coach_id: str):
    items = list(db["review"].find({"coach_id": coach_id}).sort("created_at", -1))
    for r in items:
        r["id"] = str(r.get("_id"))
        r.pop("_id", None)
    return {"items": items}

# ---------- Bookings ----------

@app.post("/bookings", response_model=dict)
def create_booking(booking: Booking):
    # basic validation on adult/parent
    if booking.user_type == "adult":
        if booking.athlete_age is not None and booking.athlete_age < 18:
            raise HTTPException(status_code=400, detail="Adults must be 18+")
    else:
        if booking.athlete_age is None or booking.athlete_age >= 18:
            raise HTTPException(status_code=400, detail="Provide athlete_age for parent bookings and must be < 18")
    booking_id = create_document("booking", booking)
    return {"id": booking_id}

@app.get("/coaches/{coach_id}/bookings")
def list_bookings_for_coach(coach_id: str):
    items = list(db["booking"].find({"coach_id": coach_id}).sort("created_at", -1))
    for b in items:
        b["id"] = str(b.get("_id"))
        b.pop("_id", None)
    return {"items": items}

# Monetization suggestions endpoint (static for now)
@app.get("/monetization")
def monetization_models():
    return {
        "models": [
            {
                "name": "Commission per booking",
                "summary": "Take 10-20% fee on each completed session",
                "pros": ["Aligned with platform value", "No upfront cost for users"],
                "cons": ["Requires dispute handling", "Dependent on volume"]
            },
            {
                "name": "Subscription for coaches",
                "summary": "Coaches pay monthly for listing, promotion, and tools",
                "pros": ["Predictable revenue", "Can bundle premium features"],
                "cons": ["Coach churn risk", "Need clear ROI"]
            },
            {
                "name": "Lead credits",
                "summary": "Coaches buy credits to bid/accept leads",
                "pros": ["Cash up-front", "Scales with demand"],
                "cons": ["Two-sided friction", "Potentially complex UX"]
            },
            {
                "name": "Payment processing markup",
                "summary": "Add ~3% service fee to cover processing + margin",
                "pros": ["Simple to explain", "Covers costs"],
                "cons": ["Price sensitive users", "Must be transparent"]
            }
        ]
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
