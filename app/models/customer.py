"""Customer model.

Customers never register or log in: their identity is collected at
checkout (name + mobile) and de-duplicated by mobile number so the shop
owner can see all orders of a returning customer.
"""
from sqlalchemy import String, Boolean, Text, DateTime, Index

from ..extensions import db
from .admin import utcnow


class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    mobile = db.Column(db.String(15), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=True)
    address = db.Column(db.Text, nullable=True)
    consent_given = db.Column(db.Boolean, nullable=False, default=False)
    consent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    orders = db.relationship("Order", back_populates="customer", order_by="Order.created_at.desc()")

    @property
    def masked_mobile(self) -> str:
        """Display form that hides most digits in admin lists."""
        if len(self.mobile) >= 4:
            return "XXXXXX" + self.mobile[-4:]
        return "XXXXXX"

    def __repr__(self):  # pragma: no cover
        return f"<Customer {self.masked_mobile}>"


Index("ix_customers_name_mobile", Customer.name, Customer.mobile)
