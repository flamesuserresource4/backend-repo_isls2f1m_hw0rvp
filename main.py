import os
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import (
    Seller,
    Storefront,
    DigitalProduct,
    LicenseKey,
    Order,
    Payment,
    RiskEvent,
    PublicProduct,
)

app = FastAPI(title="Digital Goods Platform API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Utilities ----------

def serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    out = {}
    for k, v in doc.items():
        if k == "_id":
            try:
                from bson import ObjectId  # type: ignore
                out["id"] = str(v)
            except Exception:
                out["id"] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.astimezone(timezone.utc).isoformat()
        else:
            out[k] = v
    return out


def risk_score_from_request(signal: Dict[str, Any]) -> float:
    email: str = signal.get("email", "")
    currency: str = signal.get("currency", "USD")
    device_fp: str = signal.get("device_fp", "")
    high_risk_domains = {"mailinator.com", "tempmail.com", "10minutemail.com"}
    domain = email.split("@")[-1].lower() if "@" in email else ""

    score = 0.1
    if domain in high_risk_domains:
        score += 0.6
    if currency not in {"USD", "EUR", "GBP", "JPY", "AUD", "CAD"}:
        score += 0.1
    if not device_fp:
        score += 0.1
    return min(1.0, max(0.0, score))


# ---------- Basic Routes ----------

@app.get("/")
def read_root():
    return {"message": "Digital Goods Platform API is running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": [],
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, "name") else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:  # pragma: no cover
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:  # pragma: no cover
        response["database"] = f"❌ Error: {str(e)[:50]}"

    return response


# ---------- Schema Introspection ----------

class SchemaResponse(BaseModel):
    name: str
    collection: str
    schema: Dict[str, Any]


@app.get("/schema", response_model=List[SchemaResponse])
def get_schema():
    models = [
        Seller,
        Storefront,
        DigitalProduct,
        LicenseKey,
        Order,
        Payment,
        RiskEvent,
    ]
    payload: List[SchemaResponse] = []
    for m in models:
        payload.append(
            SchemaResponse(
                name=m.__name__,
                collection=m.__name__.lower(),
                schema=m.model_json_schema(),
            )
        )
    return payload


# ---------- Public Catalog ----------

@app.get("/products", response_model=List[PublicProduct])
def list_products(seller_id: Optional[str] = None, limit: int = 20):
    filt: Dict[str, Any] = {"is_active": True}
    if seller_id:
        filt["seller_id"] = seller_id
    docs = get_documents("digitalproduct", filt, limit)
    products: List[PublicProduct] = []
    for d in docs:
        d = serialize_doc(d)
        products.append(
            PublicProduct(
                id=d.get("id", ""),
                title=d.get("title", ""),
                description=d.get("description"),
                price=float(d.get("price", 0)),
                currency=d.get("currency", "USD"),
                category=d.get("category", "software"),
            )
        )
    return products


# ---------- Orders & Payments (Demo) ----------

class CreateOrderRequest(BaseModel):
    product_id: str
    buyer_email: str
    currency: Optional[str] = "USD"
    device_fp: Optional[str] = None


class CreateOrderResponse(BaseModel):
    order_id: str
    status: str
    client_secret: str
    risk_score: float
    action: str


@app.post("/orders", response_model=CreateOrderResponse)
def create_order(body: CreateOrderRequest):
    from bson import ObjectId  # type: ignore

    try:
        product = db["digitalproduct"].find_one({"_id": ObjectId(body.product_id)})
    except Exception:
        product = None
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    prod = serialize_doc(product)

    amount = float(prod.get("price", 0.0))
    currency = body.currency or prod.get("currency", "USD")

    score = risk_score_from_request(
        {"email": body.buyer_email, "currency": currency, "device_fp": body.device_fp or ""}
    )
    action = "allow" if score < 0.6 else ("review" if score < 0.8 else "block")

    order = Order(
        seller_id=prod.get("seller_id", ""),
        product_id=prod.get("id", ""),
        buyer_email=body.buyer_email,
        amount=amount,
        currency=currency,
        status="pending" if action != "block" else "failed",
        delivery=None,
    )
    order_id = create_document("order", order)

    client_secret = secrets.token_urlsafe(24)

    return CreateOrderResponse(
        order_id=order_id,
        status=order.status,
        client_secret=client_secret,
        risk_score=score,
        action=action,
    )


class WebhookEvent(BaseModel):
    type: str
    data: Dict[str, Any]


@app.post("/payments/webhook")
def payment_webhook(event: WebhookEvent):
    # Demo webhook to mark order paid and fulfill
    evt_type = event.type
    data = event.data or {}

    if evt_type != "payment.succeeded":
        return {"received": True}

    order_id = data.get("order_id")
    amount = float(data.get("amount", 0))
    currency = data.get("currency", "USD")
    processor = data.get("processor", "card")

    if not order_id:
        raise HTTPException(status_code=400, detail="order_id missing")

    from bson import ObjectId  # type: ignore

    order_doc = db["order"].find_one({"_id": ObjectId(order_id)})
    if not order_doc:
        raise HTTPException(status_code=404, detail="Order not found")

    product = (
        db["digitalproduct"].find_one({"_id": ObjectId(order_doc.get("product_id"))})
        if order_doc.get("product_id")
        else None
    )

    # Record payment
    payment = Payment(
        order_id=order_id,
        processor=processor,
        processor_ref=data.get("processor_ref"),
        amount=amount,
        currency=currency,
        status="succeeded",
    )
    _ = create_document("payment", payment)

    delivery: Dict[str, Any] = {}
    if product:
        prod = serialize_doc(product)
        if prod.get("delivery_type") == "license_key":
            key = secrets.token_urlsafe(16).upper()
            lic = LicenseKey(product_id=prod.get("id", ""), order_id=order_id, key=key, status="active")
            _ = create_document("licensekey", lic)
            delivery = {"type": "license_key", "key": key}
        elif prod.get("delivery_type") == "download" and prod.get("file_url"):
            delivery = {"type": "download", "url": prod.get("file_url")}
        elif prod.get("delivery_type") == "api":
            delivery = {"type": "api", "note": "Delivered via API callback"}
        else:
            delivery = {"type": "manual", "note": "Seller will complete delivery"}
    else:
        delivery = {"type": "manual"}

    db["order"].update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {"status": "paid", "delivery": delivery, "updated_at": datetime.now(timezone.utc)}},
    )

    return {"ok": True, "order_id": order_id, "delivery": delivery}


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    from bson import ObjectId  # type: ignore

    try:
        doc = db["order"].find_one({"_id": ObjectId(order_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid order id")
    if not doc:
        raise HTTPException(status_code=404, detail="Order not found")
    return serialize_doc(doc)


# ---------- Seed helper for demo ----------

@app.post("/seed")
def seed_demo():
    """Create a demo seller + product for testing the flow."""
    seller = Seller(name="Acme Digital", email="owner@example.com", plan="pro")
    seller_id = create_document("seller", seller)

    product = DigitalProduct(
        seller_id=seller_id,
        title="Pro Script Bundle",
        description="A curated set of automation scripts for developers",
        price=29.0,
        currency="USD",
        category="script",
        delivery_type="license_key",
        file_url=None,
        is_active=True,
    )
    product_id = create_document("digitalproduct", product)

    return {"seller_id": seller_id, "product_id": product_id}


# Developer utilities: simple echo webhook tester
@app.post("/webhooks/echo")
def echo_webhook(req: Request):
    return {"headers": dict(req.headers), "query": dict(req.query_params)}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
