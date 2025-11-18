"""
Database Schemas for Digital Goods Platform

Each Pydantic model maps to a MongoDB collection named after the lowercase
class name (e.g., DigitalProduct -> "digitalproduct").

These are used for validation and for the database viewer via GET /schema.
"""

from pydantic import BaseModel, Field, HttpUrl, EmailStr
from typing import Optional, List, Literal, Dict, Any
from datetime import datetime


class Seller(BaseModel):
    name: str = Field(..., description="Seller or organization name")
    email: EmailStr = Field(..., description="Primary contact email")
    domain: Optional[str] = Field(None, description="Custom domain for storefront")
    plan: Literal["free", "pro", "enterprise"] = Field("free", description="Subscription plan")
    webhook_url: Optional[HttpUrl] = Field(None, description="Default webhook destination for events")
    is_active: bool = Field(True, description="Whether seller is active")


class Storefront(BaseModel):
    seller_id: str = Field(..., description="Reference to seller _id")
    name: str = Field(..., description="Storefront display name")
    theme: Literal["light", "dark"] = Field("dark", description="Theme preference")
    brand_color: str = Field("#3b82f6", description="Primary brand hex color")
    custom_domain: Optional[str] = Field(None, description="Custom domain bound to this storefront")


class DigitalProduct(BaseModel):
    seller_id: str = Field(..., description="Reference to seller _id")
    title: str = Field(..., description="Product title")
    description: Optional[str] = Field(None, description="Product description")
    price: float = Field(..., ge=0, description="Price in major currency units (e.g., USD)")
    currency: str = Field("USD", description="ISO currency code")
    category: Literal["software", "script", "file", "account", "subscription", "service"] = Field(
        "software", description="Digital product category"
    )
    delivery_type: Literal["license_key", "download", "api", "manual"] = Field(
        "download", description="How fulfillment is delivered"
    )
    file_url: Optional[HttpUrl] = Field(None, description="Encrypted or pre-signed file URL for delivery")
    max_keys: Optional[int] = Field(None, ge=1, description="Cap on license keys to generate (optional)")
    is_active: bool = Field(True, description="Whether product is live")


class LicenseKey(BaseModel):
    product_id: str = Field(..., description="Reference to product _id")
    order_id: str = Field(..., description="Reference to order _id")
    key: str = Field(..., description="Generated license key value")
    status: Literal["active", "revoked"] = Field("active", description="Key status")
    expires_at: Optional[datetime] = Field(None, description="Optional expiration timestamp")


class Order(BaseModel):
    seller_id: str = Field(..., description="Reference to seller _id")
    product_id: str = Field(..., description="Reference to product _id")
    buyer_email: EmailStr = Field(..., description="Buyer email for receipt and delivery")
    amount: float = Field(..., ge=0, description="Order amount in major units")
    currency: str = Field("USD", description="ISO currency code")
    status: Literal["pending", "paid", "refunded", "failed"] = Field("pending", description="Order status")
    delivery: Optional[Dict[str, Any]] = Field(None, description="Fulfillment details like link or license key")


class Payment(BaseModel):
    order_id: str = Field(..., description="Reference to order _id")
    processor: Literal["card", "paypal", "crypto", "bank"] = Field("card", description="Payment method type")
    processor_ref: Optional[str] = Field(None, description="External processor reference/ID")
    amount: float = Field(..., ge=0, description="Paid amount")
    currency: str = Field("USD", description="ISO currency")
    status: Literal["initiated", "succeeded", "failed", "refunded"] = Field(
        "initiated", description="Payment status"
    )


class RiskEvent(BaseModel):
    order_id: Optional[str] = Field(None, description="Related order if known")
    score: float = Field(..., ge=0, le=1, description="Risk score between 0 and 1")
    signals: Dict[str, Any] = Field(default_factory=dict, description="Signals used for the score")
    action: Literal["allow", "review", "block"] = Field("allow", description="Suggested action")


# Optional lightweight public schemas (responses)
class PublicProduct(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    price: float
    currency: str
    category: str

