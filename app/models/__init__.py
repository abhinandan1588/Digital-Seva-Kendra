"""SQLAlchemy models for the Digital Seva Kendra portal.

Importing this package imports every model so Flask-Migrate/Alembic can
detect all tables and relationship graph.
"""
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy import JSON

# JSONB on PostgreSQL; plain JSON variant so the test suite can run on SQLite.
JSONB = PG_JSONB().with_variant(JSON(), "sqlite")

from .admin import AdminUser
from .customer import Customer
from .category import ServiceCategory
from .subcategory import ServiceSubcategory
from .service import Service, ServiceFormField, ServiceDocumentRequirement
from .exam import ExamCycle
from .document_template import DocumentTemplate
from .order import Order, OrderItem, StatusHistory, Counter
from .application import Application, ApplicationFieldValue
from .payment import Payment
from .document import UploadedDocument
from .notification import Notification
from .audit_log import AdminAuditLog
from .settings import WebsiteSetting
from .search import SearchAlias, SearchQueryStat, OfficialPortal

__all__ = [
    "AdminUser", "Customer", "ServiceCategory", "ServiceSubcategory",
    "Service", "ServiceFormField", "ServiceDocumentRequirement",
    "ExamCycle", "DocumentTemplate", "OfficialPortal",
    "SearchAlias", "SearchQueryStat",
    "Order", "OrderItem", "StatusHistory", "Counter",
    "Application", "ApplicationFieldValue", "Payment", "UploadedDocument",
    "Notification", "AdminAuditLog", "WebsiteSetting",
]
